from __future__ import annotations
from typing import Annotated, Any, ClassVar, List, Optional, Union, Type
from pydantic import BaseModel, Field
import uuid
import datetime
import os
from rdflib import Graph, URIRef, Literal, Namespace
from rdflib.namespace import RDF, RDFS, OWL, XSD, DCTERMS

BFO = Namespace("http://purl.obolibrary.org/obo/")
ABI = Namespace("http://ontology.naas.ai/abi/")
CCO = Namespace("https://www.commoncoreontologies.org/")


# Base class for all RDF entities
class RDFEntity(BaseModel):
    """Base class for all RDF entities with URI and namespace management"""

    _namespace: ClassVar[str] = "http://ontology.naas.ai/abi/"
    _uri: str = ""
    _object_properties: ClassVar[set[str]] = set()

    model_config = {"arbitrary_types_allowed": True, "extra": "forbid"}

    def __init__(self, **kwargs):
        uri = kwargs.pop("_uri", None)
        super().__init__(**kwargs)
        if uri is not None:
            self._uri = uri
        elif not self._uri:
            self._uri = f"{self._namespace}{uuid.uuid4()}"

    @classmethod
    def set_namespace(cls, namespace: str):
        """Set the namespace for generating URIs"""
        cls._namespace = namespace

    def rdf(
        self, subject_uri: str | None = None, visited: set[str] | None = None
    ) -> Graph:
        """Generate RDF triples for this instance

        Args:
            subject_uri: Optional URI to use as subject (defaults to self._uri)
            visited: Set of URIs that have already been processed (for cycle detection)
        """
        # Initialize visited set if not provided
        if visited is None:
            visited = set()

        g = Graph()
        g.bind("cco", CCO)
        g.bind("bfo", BFO)
        g.bind("abi", ABI)
        g.bind("rdfs", RDFS)
        g.bind("rdf", RDF)
        g.bind("owl", OWL)
        g.bind("xsd", XSD)

        # Use stored URI or provided subject_uri
        if subject_uri is None:
            subject_uri = self._uri
        subject = URIRef(subject_uri)

        # Check if we've already processed this entity (cycle detection)
        if subject_uri in visited:
            # Already processed, just return empty graph to avoid infinite recursion
            # The relationship triple will be added by the caller
            return g

        # Mark this entity as visited before processing
        visited.add(subject_uri)

        # Add class type
        if hasattr(self, "_class_uri"):
            g.add((subject, RDF.type, URIRef(self._class_uri)))

        # Add owl:NamedIndividual type
        g.add((subject, RDF.type, OWL.NamedIndividual))

        # Add label if it exists
        if hasattr(self, "label"):
            g.add((subject, RDFS.label, Literal(self.label)))

        object_props: set[str] = getattr(self, "_object_properties", set())

        # Add properties
        if hasattr(self, "_property_uris"):
            for prop_name, prop_uri in self._property_uris.items():
                is_object_prop = prop_name in object_props
                prop_value = getattr(self, prop_name, None)
                if prop_value is not None:
                    if isinstance(prop_value, list):
                        for item in prop_value:
                            if hasattr(item, "rdf") and hasattr(item, "_uri"):
                                # Check if this entity was already visited to prevent cycles
                                if item._uri not in visited:
                                    # Add triples from related object
                                    g += item.rdf(visited=visited)
                                # Always add the triple, even if already visited
                                g.add((subject, URIRef(prop_uri), URIRef(item._uri)))
                            elif is_object_prop and isinstance(item, (str, URIRef)):
                                g.add((subject, URIRef(prop_uri), URIRef(str(item))))
                            else:
                                g.add((subject, URIRef(prop_uri), Literal(item)))
                    elif hasattr(prop_value, "rdf") and hasattr(prop_value, "_uri"):
                        # Check if this entity was already visited to prevent cycles
                        if prop_value._uri not in visited:
                            # Add triples from related object
                            g += prop_value.rdf(visited=visited)
                        # Always add the triple, even if already visited
                        g.add((subject, URIRef(prop_uri), URIRef(prop_value._uri)))
                    elif is_object_prop and isinstance(prop_value, (str, URIRef)):
                        g.add((subject, URIRef(prop_uri), URIRef(str(prop_value))))
                    else:
                        g.add((subject, URIRef(prop_uri), Literal(prop_value)))

        return g


class PDFPaperFile(RDFEntity):
    """
    A PDF file representing a scientific paper (modeled as a generically dependent continuant).
    """

    _class_uri: ClassVar[str] = (
        "http://purl.obolibrary.org/obo/phases/documents.owl#PDFPaperFile"
    )
    _name: ClassVar[str] = "PDF paper file"
    _property_uris: ClassVar[dict] = {
        "created": "http://purl.org/dc/terms/created",
        "creation_time": "http://purl.obolibrary.org/obo/phases/documents.owl#creation_time",
        "creator": "http://purl.org/dc/terms/creator",
        "has_chunks": "http://purl.obolibrary.org/obo/phases/documents.owl#has_chunks",
        "label": "http://www.w3.org/2000/01/rdf-schema#label",
        "path": "http://purl.obolibrary.org/obo/phases/documents.owl#path",
        "pdf_hash": "http://purl.obolibrary.org/obo/phases/documents.owl#pdf_hash",
        "pdfpaperfile_id": "http://purl.obolibrary.org/obo/phases/documents.owl#pdfpaperfile_id",
    }
    _object_properties: ClassVar[set[str]] = {"has_chunks"}

    # Data properties
    pdfpaperfile_id: Annotated[str, Field()]
    path: Annotated[Any, Field()]
    pdf_hash: Annotated[str, Field()]
    creation_time: Annotated[datetime.datetime, Field()]
    label: Annotated[str, Field(description="Label of the resource.")]
    created: Annotated[
        Optional[datetime.datetime],
        Field(description="Date of creation of the resource."),
    ] = datetime.datetime.now()
    creator: Annotated[
        Optional[Any],
        Field(description="An entity responsible for making the resource."),
    ] = os.environ.get("USER")

    # Object properties
    has_chunks: Optional[Annotated[List[Union[Chunk, URIRef, str]], Field()]] = [
        "http://ontology.naas.ai/abi/unknown"
    ]


class Chunk(RDFEntity):
    """
    A chunk (e.g., a text segment and its vector embedding) modeled as a generically dependent continuant.
    """

    _class_uri: ClassVar[str] = (
        "http://purl.obolibrary.org/obo/phases/documents.owl#Chunk"
    )
    _name: ClassVar[str] = "chunk"
    _property_uris: ClassVar[dict] = {
        "chunk_hash": "http://purl.obolibrary.org/obo/phases/documents.owl#chunk_hash",
        "chunk_id": "http://purl.obolibrary.org/obo/phases/documents.owl#chunk_id",
        "chunk_number": "http://purl.obolibrary.org/obo/phases/documents.owl#chunk_number",
        "chunk_of": "http://purl.obolibrary.org/obo/phases/documents.owl#chunk_of",
        "created": "http://purl.org/dc/terms/created",
        "creator": "http://purl.org/dc/terms/creator",
        "has_embedding_occurrence": "http://purl.obolibrary.org/obo/phases/documents.owl#has_embedding_occurrence",
        "has_lexical_occurrence": "http://purl.obolibrary.org/obo/phases/documents.owl#has_lexical_occurrence",
        "label": "http://www.w3.org/2000/01/rdf-schema#label",
        "text": "http://purl.obolibrary.org/obo/phases/documents.owl#text",
    }
    _object_properties: ClassVar[set[str]] = {
        "chunk_of",
        "has_embedding_occurrence",
        "has_lexical_occurrence",
    }

    # Data properties
    chunk_hash: Annotated[str, Field()]
    chunk_id: Annotated[str, Field()]
    chunk_number: Optional[Annotated[int, Field()]] = "unknown"
    text: Annotated[str, Field()]
    label: Annotated[str, Field(description="Label of the resource.")]
    created: Annotated[
        Optional[datetime.datetime],
        Field(description="Date of creation of the resource."),
    ] = datetime.datetime.now()
    creator: Annotated[
        Optional[Any],
        Field(description="An entity responsible for making the resource."),
    ] = os.environ.get("USER")

    # Object properties
    chunk_of: Annotated[Union[PDFPaperFile, URIRef, str], Field()]
    has_embedding_occurrence: Optional[
        Annotated[List[Union[EmbeddingOccurrence, URIRef, str]], Field()]
    ] = ["http://ontology.naas.ai/abi/unknown"]
    has_lexical_occurrence: Optional[
        Annotated[List[Union[LexicalOccurrence, URIRef, str]], Field()]
    ] = ["http://ontology.naas.ai/abi/unknown"]


class LexicalOccurrence(RDFEntity):
    """
    An observation that a lexical form (e.g., rdfs:label / skos:prefLabel) of an ontology entity appears in a Chunk text.
    """

    _class_uri: ClassVar[str] = (
        "http://purl.obolibrary.org/obo/phases/documents.owl#LexicalOccurrence"
    )
    _name: ClassVar[str] = "lexical occurrence"
    _property_uris: ClassVar[dict] = {
        "created": "http://purl.org/dc/terms/created",
        "creator": "http://purl.org/dc/terms/creator",
        "label": "http://www.w3.org/2000/01/rdf-schema#label",
        "lexical_occurrence_in_chunk": "http://purl.obolibrary.org/obo/phases/documents.owl#lexical_occurrence_in_chunk",
        "lexical_occurrence_of": "http://purl.obolibrary.org/obo/phases/documents.owl#lexical_occurrence_of",
        "matched_predicate": "http://purl.obolibrary.org/obo/phases/documents.owl#matched_predicate",
        "matched_text": "http://purl.obolibrary.org/obo/phases/documents.owl#matched_text",
    }
    _object_properties: ClassVar[set[str]] = {
        "lexical_occurrence_in_chunk",
        "lexical_occurrence_of",
    }

    # Data properties
    matched_text: Annotated[str, Field()]
    matched_predicate: Annotated[Any, Field()]
    label: Annotated[str, Field(description="Label of the resource.")]
    created: Annotated[
        Optional[datetime.datetime],
        Field(description="Date of creation of the resource."),
    ] = datetime.datetime.now()
    creator: Annotated[
        Optional[Any],
        Field(description="An entity responsible for making the resource."),
    ] = os.environ.get("USER")

    # Object properties
    lexical_occurrence_in_chunk: Annotated[Union[Chunk, URIRef, str], Field()]
    lexical_occurrence_of: Annotated[Union[Type, URIRef, str], Field()]


class EmbeddingOccurrence(RDFEntity):
    """
    An observation that a vector embedding of an ontology entity appears in a Chunk text.
    """

    _class_uri: ClassVar[str] = (
        "http://purl.obolibrary.org/obo/phases/documents.owl#EmbeddingOccurrence"
    )
    _name: ClassVar[str] = "embedding occurrence"
    _property_uris: ClassVar[dict] = {
        "created": "http://purl.org/dc/terms/created",
        "creator": "http://purl.org/dc/terms/creator",
        "embedding_occurrence_in_chunk": "http://purl.obolibrary.org/obo/phases/documents.owl#embedding_occurrence_in_chunk",
        "embedding_occurrence_of": "http://purl.obolibrary.org/obo/phases/documents.owl#embedding_occurrence_of",
        "label": "http://www.w3.org/2000/01/rdf-schema#label",
        "matched_predicate": "http://purl.obolibrary.org/obo/phases/documents.owl#matched_predicate",
        "matched_text": "http://purl.obolibrary.org/obo/phases/documents.owl#matched_text",
    }
    _object_properties: ClassVar[set[str]] = {
        "embedding_occurrence_in_chunk",
        "embedding_occurrence_of",
    }

    # Data properties
    matched_text: Annotated[str, Field()]
    matched_predicate: Annotated[Any, Field()]
    label: Annotated[str, Field(description="Label of the resource.")]
    created: Annotated[
        Optional[datetime.datetime],
        Field(description="Date of creation of the resource."),
    ] = datetime.datetime.now()
    creator: Annotated[
        Optional[Any],
        Field(description="An entity responsible for making the resource."),
    ] = os.environ.get("USER")

    # Object properties
    embedding_occurrence_in_chunk: Annotated[Union[Chunk, URIRef, str], Field()]
    embedding_occurrence_of: Annotated[Union[Type, URIRef, str], Field()]


# Rebuild models to resolve forward references (circular dependencies)
PDFPaperFile.model_rebuild()
Chunk.model_rebuild(
    _types_namespace={
        "LexicalOccurrence": LexicalOccurrence,
        "EmbeddingOccurrence": EmbeddingOccurrence,
    }
)
LexicalOccurrence.model_rebuild(_types_namespace={"Chunk": Chunk})
EmbeddingOccurrence.model_rebuild(_types_namespace={"Chunk": Chunk})
