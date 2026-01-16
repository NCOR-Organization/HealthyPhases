from langchain_core.tools import StructuredTool
from fastapi import APIRouter
import os
from glob import glob
from naas_abi_core import logger

from abi_phases.phases import ABIModule
from naas_abi_core.workflow.workflow import Workflow, WorkflowConfiguration, WorkflowParameters
from naas_abi_core.services.object_storage.ObjectStoragePort import Exceptions as ObjectStorageExceptions

import pymupdf.layout
import pymupdf4llm
import pathlib
import numpy as np
import uuid

import hashlib
import datetime
import rdflib


from abi_phases.phases.ontologies.documents import PDFPaperFile, Chunk, LexicalOccurrence, RDFEntity

class PapersIngestionWorkflowConfiguration(WorkflowConfiguration):
    storage_path: str = "papers"

class PapersIngestionWorkflowParameters(WorkflowParameters):
    paths: list[str]
    ontology_path: str

class PapersIngestionWorkflow(Workflow[PapersIngestionWorkflowParameters]):
    
    module: ABIModule
    
    def __init__(self, configuration: PapersIngestionWorkflowConfiguration):
        super().__init__(configuration)
        self.__configuration = configuration
        
        self.module = ABIModule.get_instance()

    def _pdf_path_to_key(self, path: str) -> str:
        return f'{path.split("/")[-1]}.md'

    def pdfs_to_markdown(self, parameters: PapersIngestionWorkflowParameters):
        try:
            existing_papers = self.module.engine.services.object_storage.list_objects(self.__configuration.storage_path)
            logger.debug(f"Existing papers: {existing_papers}")
        except ObjectStorageExceptions.ObjectNotFound:
            logger.debug("No existing papers found")
            existing_papers = []
        
        for path in parameters.paths:
            key = self._pdf_path_to_key(path)
            
            if any(key in paper for paper in existing_papers):
                logger.debug(f"Paper {key} already exists")
                continue
            
            doc = pymupdf.open(path)
            md = pymupdf4llm.to_markdown(doc)
            pathlib.Path(f'{path}.md').write_bytes(md.encode())
            self.module.engine.services.object_storage.put_object(self.__configuration.storage_path, key, md.encode())

    def markdowns_to_vectors(self, parameters: PapersIngestionWorkflowParameters):
        print(f"Markdowns to vectors: {parameters}")
        for path in parameters.paths:
            print(f"Processing {path}")
            # Check if we already have a PDFPaperFile for this path.
            query = f"""PREFIX phases-doc: <http://purl.obolibrary.org/obo/phases/documents.owl#>
SELECT ?pdf_paper_file ?id WHERE {{ ?pdf_paper_file a phases-doc:PDFPaperFile ; phases-doc:path {rdflib.Literal(path).n3()}  . }}"""




            pdf_paper_file = self.module.engine.services.triple_store.query(query)
            
            if len(list(pdf_paper_file)) > 0:
                logger.debug(f"PDFPaperFile for {path} already exists")
                continue
            else:
                logger.debug(f"PDFPaperFile {path} not found")
            
            key = self._pdf_path_to_key(path)
            md = self.module.engine.services.object_storage.get_object(self.__configuration.storage_path, key).decode("utf-8")
            
            CHUNK_SIZE = 512
            OVERLAP = 128
            
            # We need to compute embeddings for the markdown chunks.
            # Split the markdown into overlapping chunks
            def split_to_overlapping_chunks(text: str, chunk_size: int = 512, overlap: int = 128) -> list[str]:
                tokens = text.split()
                chunks = []
                start = 0
                while start < len(tokens):
                    end = start + chunk_size
                    chunk = " ".join(tokens[start:end])
                    chunks.append(chunk)
                    if end >= len(tokens):
                        break
                    start += chunk_size - overlap
                return chunks



            chunks: list[str] = split_to_overlapping_chunks(md, chunk_size=CHUNK_SIZE, overlap=OVERLAP)
            
            
            # We need to compute the embeddings for the chunks.
            def compute_embeddings(chunks: list[str], chunk_size: int = 512, overlap: int = 128) -> list[np.ndarray]:
                from langchain_openai import OpenAIEmbeddings
                embeddings = OpenAIEmbeddings(model="text-embedding-3-large", dimensions=3072)
                return [np.array(embedding) for embedding in embeddings.embed_documents(chunks)]
            
            embeddings: list[np.ndarray] = compute_embeddings(chunks, chunk_size=CHUNK_SIZE, overlap=OVERLAP)
            
            # We need to make sure the vector store has a collection.
            self.module.engine.services.vector_store.ensure_collection(collection_name="papers", dimension=3072)
            
        
            graph : rdflib.Graph = rdflib.Graph()
            
            pdf_paper_file = PDFPaperFile(
                pdfpaperfile_id=str(uuid.uuid4()),
                path=path,
                pdf_hash=hashlib.sha256(md.encode()).hexdigest(),
                creation_time=datetime.datetime.now()
            )
            
            graph += pdf_paper_file.rdf()
            
            chunk_entities: list[Chunk] = []
            for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
                chunk_entity = Chunk(
                    chunk_id=str(uuid.uuid4()),
                    chunk_number=i,
                    chunk_hash=hashlib.sha256(chunk.encode()).hexdigest(),
                    text=chunk,
                    chunk_of=pdf_paper_file
                )
                chunk_entities.append(chunk_entity)
                
                graph += chunk_entity.rdf()
            
            logger.debug("Inserting graph")
            self.module.engine.services.triple_store.insert(graph)
            logger.debug("Graph inserted")
            
            # We need to store the embeddings in the vector store.
            self.module.engine.services.vector_store.add_documents("papers", [chunk_entity.chunk_id for chunk_entity in chunk_entities], embeddings)

    def ontology_label(self, parameters: PapersIngestionWorkflowParameters):
        ontology = rdflib.Graph()
        ontology.parse(parameters.ontology_path, format="xml")
        
        rows = ontology.query("""PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX owl: <http://www.w3.org/2002/07/owl#>


SELECT ?s ?label ?prefLabel WHERE {
    ?s a owl:Class .
    OPTIONAL { ?s rdfs:label ?label }
    OPTIONAL { ?s skos:prefLabel ?prefLabel }
    
    # ?s starts with http://purl.obolibrary.org/obo/PHASES_
    # FILTER(STRSTARTS(STR(?s), "http://purl.obolibrary.org/obo/PHASES_"))
}

""")
        
        findings = rdflib.Graph()
        
        for row in rows:
            subject, label, prefLabel = row
            if prefLabel:
                # For each prefLabel we want to find occurence in chunks.
                query = f"""PREFIX phases-doc: <http://purl.obolibrary.org/obo/phases/documents.owl#>
SELECT ?chunk ?chunk_id ?pdf_paper_file ?path WHERE {{
    ?chunk a phases-doc:Chunk ;
    phases-doc:text ?text ;
    phases-doc:chunk_of ?pdf_paper_file ;
    phases-doc:chunk_id ?chunk_id .
    ?pdf_paper_file phases-doc:path ?path .
    FILTER(CONTAINS(?text, "{prefLabel}"))
    # Only keep chunks where this ontology term isn't already linked via an existing LexicalOccurrence
    FILTER NOT EXISTS {{
        ?lex_occ a phases-doc:LexicalOccurrence ;
            phases-doc:occurs_in_chunk ?chunk ;
            phases-doc:occurrence_of <{subject}> .
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
                        occurs_in_chunk=chunk,
                        occurrence_of=subject
                    )
                    findings += lexical_occurrence.rdf()
        
        print(findings.serialize(format="turtle"))
        
        self.module.engine.services.triple_store.insert(findings)

    def run(self, parameters: PapersIngestionWorkflowParameters):
        logger.debug("Running pipeline")
        
        # We convert pdfs to markdown and store them in the object storage
        self.pdfs_to_markdown(parameters)
        
        # We vectorize the markdown and store them in the vector store.
        self.markdowns_to_vectors(parameters)
        
        self.ontology_label(parameters)
            
    def as_tools(self) -> list[StructuredTool]:
        return []
    
    def as_api(self, router: APIRouter):
        return []
    
if __name__ == "__main__":
    workflow = PapersIngestionWorkflow(PapersIngestionWorkflowConfiguration())
    
    papers_path = os.path.join(os.path.dirname(__file__), "..", "..", "papers")
    ontology_path = os.path.join(os.path.dirname(__file__), "..", "..", "ontologies", "phases.owl")
    
    workflow.run(PapersIngestionWorkflowParameters(paths=glob(os.path.join(papers_path, "*/*.pdf"), recursive=True), ontology_path=ontology_path))