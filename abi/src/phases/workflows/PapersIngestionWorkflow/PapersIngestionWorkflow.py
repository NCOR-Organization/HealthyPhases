from langchain_core.tools import StructuredTool
from fastapi import APIRouter
import os
from glob import glob
from naas_abi_core import logger

from phases import ABIModule
from naas_abi_core.workflow.workflow import (
    Workflow,
    WorkflowConfiguration,
    WorkflowParameters,
)
from naas_abi_core.services.object_storage.ObjectStoragePort import (
    Exceptions as ObjectStorageExceptions,
)
from naas_abi_core.services.vector_store.IVectorStorePort import SearchResult
from naas_abi_core.services.cache.CacheFactory import CacheFactory
import pymupdf.layout
import pymupdf4llm
import pathlib
import numpy as np
import uuid

import hashlib
import datetime
import rdflib

from phases.utils import embed_text


def _hash(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


from phases.ontologies.documents import (
    PDFPaperFile,
    Chunk,
    LexicalOccurrence,
    EmbeddingOccurrence,
    RDFEntity,
)


class PapersIngestionWorkflowConfiguration(WorkflowConfiguration):
    storage_path: str = "papers"


class PapersIngestionWorkflowParameters(WorkflowParameters):
    paths: list[str]
    ontology_path: str


PAPERS_GRAPH = rdflib.URIRef("http://ontology.naas.ai/graph/phases/papers")


class PapersIngestionWorkflow(Workflow[PapersIngestionWorkflowParameters]):
    module: ABIModule

    def __init__(self, configuration: PapersIngestionWorkflowConfiguration):
        super().__init__(configuration)
        self.__configuration = configuration

        self.module = ABIModule.get_instance()
        self.__cache = CacheFactory.CacheFS_find_storage(subpath="papers_ingestion")

    def _pdf_path_to_key(self, path: str) -> str:
        return f"{path.split('/')[-1]}.md"

    def _ontology_fingerprint(self, ontology_path: str) -> str:
        return _hash(pathlib.Path(ontology_path).read_bytes().decode("utf-8", "ignore"))

    def _paths_fingerprint(self, paths: list[str]) -> str:
        return _hash("\n".join(sorted(paths)))

    def pdfs_to_markdown(self, parameters: PapersIngestionWorkflowParameters):
        existing_papers: list[str] | None = None

        for path in parameters.paths:
            key = self._pdf_path_to_key(path)
            cache_key = f"md_done:{key}"

            if self.__cache.exists(cache_key):
                logger.debug(f"[cache] markdown already produced for {key}")
                continue

            # Fall back to object storage listing only on cache miss.
            if existing_papers is None:
                try:
                    existing_papers = self.module.engine.services.object_storage.list_objects(
                        self.__configuration.storage_path
                    )
                except ObjectStorageExceptions.ObjectNotFound:
                    existing_papers = []

            if any(key == paper or paper.endswith("/" + key) for paper in existing_papers):
                logger.debug(f"Paper {key} already exists in object storage")
                self.__cache.set_json(cache_key, {"path": path})
                continue

            doc = pymupdf.open(path)
            md = pymupdf4llm.to_markdown(doc)
            pathlib.Path(f"{path}.md").write_bytes(md.encode())
            self.module.engine.services.object_storage.put_object(
                self.__configuration.storage_path, key, md.encode()
            )
            self.__cache.set_json(cache_key, {"path": path})

    def markdowns_to_vectors(self, parameters: PapersIngestionWorkflowParameters):
        print(f"Markdowns to vectors: {parameters}")

        # Hoisted out of the per-path loop.
        self.module.engine.services.vector_store.ensure_collection(
            collection_name="papers", dimension=3072
        )

        for path in parameters.paths:
            print(f"Processing {path}")
            cache_key = f"vec_done:{path}"
            if self.__cache.exists(cache_key):
                logger.debug(f"[cache] vectors already produced for {path}")
                continue

            # Cache miss — fall back to a SPARQL existence check (covers cache wipe / migrations).
            query = f"""PREFIX phases-doc: <http://purl.obolibrary.org/obo/phases/documents.owl#>
SELECT ?pdf_paper_file ?id WHERE {{
    GRAPH <{PAPERS_GRAPH}> {{
        ?pdf_paper_file a phases-doc:PDFPaperFile ; phases-doc:path {rdflib.Literal(path).n3()} .
    }}
}}"""

            pdf_paper_file = self.module.engine.services.triple_store.query(query)

            if len(list(pdf_paper_file)) > 0:
                logger.debug(f"PDFPaperFile for {path} already exists")
                self.__cache.set_json(cache_key, {"path": path})
                continue
            else:
                logger.debug(f"PDFPaperFile {path} not found")

            key = self._pdf_path_to_key(path)
            md = self.module.engine.services.object_storage.get_object(
                self.__configuration.storage_path, key
            ).decode("utf-8")

            chunks, embeddings = embed_text(md)

            graph: rdflib.Graph = rdflib.Graph()

            pdf_paper_file = PDFPaperFile(
                pdfpaperfile_id=str(uuid.uuid4()),
                path=path,
                pdf_hash=hashlib.sha256(md.encode()).hexdigest(),
                creation_time=datetime.datetime.now(),
            )

            graph += pdf_paper_file.rdf()

            chunk_entities: list[Chunk] = []
            for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
                chunk_entity = Chunk(
                    chunk_id=str(uuid.uuid4()),
                    chunk_number=i,
                    chunk_hash=hashlib.sha256(chunk.encode()).hexdigest(),
                    text=chunk,
                    chunk_of=pdf_paper_file,
                )
                chunk_entities.append(chunk_entity)

                graph += chunk_entity.rdf()

            logger.debug("Inserting graph")
            self.module.engine.services.triple_store.insert(
                graph, graph_name=PAPERS_GRAPH
            )
            logger.debug("Graph inserted")

            # We need to store the embeddings in the vector store.
            self.module.engine.services.vector_store.add_documents(
                "papers",
                [chunk_entity.chunk_id for chunk_entity in chunk_entities],
                embeddings,
            )
            self.__cache.set_json(cache_key, {"path": path})

    def find_lexical_occurrences(self, parameters: PapersIngestionWorkflowParameters):
        ontology_fp = self._ontology_fingerprint(parameters.ontology_path)
        paths_fp = self._paths_fingerprint(parameters.paths)
        stage_key = f"lex_done:{ontology_fp}:{paths_fp}"
        if self.__cache.exists(stage_key):
            logger.debug("[cache] lexical occurrences stage already up-to-date — skipping")
            return

        ontology = rdflib.Graph()
        ontology.parse(parameters.ontology_path, format="xml")

        # We query all subject, label and prefLabel of all classes in the ontology.
        rows = ontology.query("""PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX owl: <http://www.w3.org/2002/07/owl#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>


SELECT ?s ?label ?prefLabel WHERE {
    ?s a owl:Class .
    OPTIONAL { ?s rdfs:label ?label }
    OPTIONAL { ?s skos:prefLabel ?prefLabel }
    
    # ?s starts with http://purl.obolibrary.org/obo/PHASES_
    FILTER(STRSTARTS(STR(?s), "http://purl.obolibrary.org/obo/PHASES_"))
}

""")

        findings = rdflib.Graph()

        for row in rows:
            subject, label, prefLabel = row
            if prefLabel:
                # For each prefLabel we want to find occurence in chunks.
                query = f"""PREFIX phases-doc: <http://purl.obolibrary.org/obo/phases/documents.owl#>
SELECT ?chunk ?chunk_id ?pdf_paper_file ?path WHERE {{
    GRAPH <{PAPERS_GRAPH}> {{
        ?chunk a phases-doc:Chunk ;
        phases-doc:text ?text ;
        phases-doc:chunk_of ?pdf_paper_file ;
        phases-doc:chunk_id ?chunk_id .
        ?pdf_paper_file phases-doc:path ?path .
        FILTER(CONTAINS(?text, "{prefLabel}"))
        # Only keep chunks where this ontology term isn't already linked via an existing LexicalOccurrence
        FILTER NOT EXISTS {{
            ?lex_occ a phases-doc:LexicalOccurrence ;
                phases-doc:lexical_occurrence_in_chunk ?chunk ;
                phases-doc:lexical_occurrence_of <{subject}> .
        }}
    }}
}}"""
                chunks = self.module.engine.services.triple_store.query(query)
                for chunk, chunk_id, pdf_paper_file, path in chunks:
                    # print(f'{prefLabel} found in {path} at chunk {chunk_id}')
                    lexical_occurrence = LexicalOccurrence(
                        matched_text=prefLabel,
                        matched_predicate=rdflib.SKOS.prefLabel,
                        # occurs_in_chunk expects a Chunk instance, but we lack full chunk data.
                        # We'll supply a 'stub' Chunk with only the URI set, and other fields as None or defaults.
                        lexical_occurrence_in_chunk=chunk,
                        lexical_occurrence_of=subject,
                    )
                    findings += lexical_occurrence.rdf()

        print(findings.serialize(format="turtle"))

        self.module.engine.services.triple_store.insert(
            findings, graph_name=PAPERS_GRAPH
        )
        self.__cache.set_json(stage_key, {"ontology": ontology_fp, "paths": paths_fp})

    def find_definition_occurrences(
        self, parameters: PapersIngestionWorkflowParameters
    ):
        ontology_fp = self._ontology_fingerprint(parameters.ontology_path)
        paths_fp = self._paths_fingerprint(parameters.paths)
        stage_key = f"def_done:{ontology_fp}:{paths_fp}"
        if self.__cache.exists(stage_key):
            logger.debug("[cache] definition occurrences stage already up-to-date — skipping")
            return

        ontology = rdflib.Graph()
        ontology.parse(parameters.ontology_path, format="xml")

        rows: rdflib.query.Result = ontology.query("""PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX owl: <http://www.w3.org/2002/07/owl#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>


SELECT ?s ?label ?definition WHERE {
    ?s a owl:Class .
    OPTIONAL { ?s rdfs:label ?label }
    ?s skos:definition ?definition .
    
    # ?s starts with http://purl.obolibrary.org/obo/PHASES_
    FILTER(STRSTARTS(STR(?s), "http://purl.obolibrary.org/obo/PHASES_"))
}

""")

        findings = rdflib.Graph()

        for row in rows:
            subject, label, definition = row
            assert definition is not None
            print(f"{subject} | {label} |\t\t{definition}")

            definition_text = str(definition)
            emb_key = f"def_emb:{subject}:{_hash(definition_text)}"
            try:
                cached = self.__cache.get(emb_key)
                chunks, embeddings = cached["chunks"], cached["embeddings"]
                logger.debug(f"[cache] reusing definition embedding for {subject}")
            except Exception:
                chunks, embeddings = embed_text(definition_text)
                self.__cache.set_pickle(
                    emb_key, {"chunks": chunks, "embeddings": embeddings}
                )
            for _, embedding in zip(chunks, embeddings):
                # Find closest matches.

                matches: list[SearchResult] = (
                    self.module.engine.services.vector_store.search_similar(
                        "papers", embedding, k=10
                    )
                )
                for match in matches:
                    print(f"{match.id} | {match.score} | {match.metadata}")

                    chunk_rows = self.module.engine.services.triple_store.query(f"""PREFIX phases-doc: <http://purl.obolibrary.org/obo/phases/documents.owl#>
SELECT ?chunk ?chunk_id ?pdf_paper_file ?path ?text WHERE {{
    GRAPH <{PAPERS_GRAPH}> {{
        ?chunk a phases-doc:Chunk ;
        phases-doc:text ?text ;
        phases-doc:chunk_of ?pdf_paper_file ;
        phases-doc:chunk_id ?chunk_id .
        ?chunk phases-doc:text ?text .
        ?pdf_paper_file phases-doc:path ?path .
        FILTER(CONTAINS(?chunk_id, "{match.id}"))
        FILTER NOT EXISTS {{
            ?embedding_occ a phases-doc:EmbeddingOccurrence ;
                phases-doc:embedding_occurrence_in_chunk ?chunk ;
                phases-doc:embedding_occurrence_of <{subject}> .
        }}
    }}
}}""")
                    chunk_rows_list = list(chunk_rows)
                    if not chunk_rows_list:
                        logger.debug(f"No chunk row found for match id: {match.id}")
                        continue

                    for (
                        chunk_uri,
                        chunk_id,
                        pdf_paper_file,
                        path,
                        text,
                    ) in chunk_rows_list:
                        print(
                            f"{text} | {path} | {chunk_id} | {pdf_paper_file} | {match.id}"
                        )
                        embedding_occurrence = EmbeddingOccurrence(
                            matched_text=definition_text,
                            matched_predicate=rdflib.SKOS.definition,
                            embedding_occurrence_in_chunk=chunk_uri,
                            embedding_occurrence_of=subject,
                        )
                        findings += embedding_occurrence.rdf()

        print(findings.serialize(format="turtle"))

        self.module.engine.services.triple_store.insert(
            findings, graph_name=PAPERS_GRAPH
        )
        self.__cache.set_json(stage_key, {"ontology": ontology_fp, "paths": paths_fp})

    def run(self, parameters: PapersIngestionWorkflowParameters):
        logger.debug("Running pipeline")

        # We convert pdfs to markdown and store them in the object storage
        self.pdfs_to_markdown(parameters)

        # We vectorize the markdown and store them in the vector store.
        self.markdowns_to_vectors(parameters)

        self.find_lexical_occurrences(parameters)

        self.find_definition_occurrences(parameters)

    def as_tools(self) -> list[StructuredTool]:
        return []

    def as_api(self, router: APIRouter):
        return []


if __name__ == "__main__":
    workflow = PapersIngestionWorkflow(PapersIngestionWorkflowConfiguration())

    papers_path = os.path.join(os.path.dirname(__file__), "..", "..", "papers")
    ontology_path = os.path.join(
        os.path.dirname(__file__), "..", "..", "ontologies", "phases.owl"
    )

    workflow.run(
        PapersIngestionWorkflowParameters(
            paths=glob(os.path.join(papers_path, "*/*.pdf"), recursive=True),
            ontology_path=ontology_path,
        )
    )
