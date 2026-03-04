from __future__ import annotations
from typing import Optional, List, Any, Union, ClassVar
from pydantic import BaseModel, Field, PrivateAttr
import datetime
import uuid
import rdflib
from rdflib import Graph, URIRef, Literal, Namespace
from rdflib.namespace import RDF, RDFS, OWL, XSD

# Generated classes from TTL file

# Base class for all RDF entities
class RDFEntity(BaseModel):
    """Base class for all RDF entities with URI and namespace management"""
    _namespace: ClassVar[str] = "http://example.org/instance/"
    _uri: str = ""
    _object_properties: ClassVar[set[str]] = set()
    
    model_config = {
        'arbitrary_types_allowed': True,
        'extra': 'forbid'
    }
    
    def __init__(self, **kwargs):
        uri = kwargs.pop('_uri', None)
        super().__init__(**kwargs)
        if uri is not None:
            self._uri = uri
        elif not self._uri:
            self._uri = f"{self._namespace}{uuid.uuid4()}"
    
    @classmethod
    def set_namespace(cls, namespace: str):
        """Set the namespace for generating URIs"""
        cls._namespace = namespace
        
    def rdf(self, subject_uri: str | None = None) -> Graph:
        """Generate RDF triples for this instance"""
        g = Graph()
        
        # Use stored URI or provided subject_uri
        if subject_uri is None:
            subject_uri = self._uri
        subject = URIRef(subject_uri)
        
        # Add class type
        if hasattr(self, '_class_uri'):
            g.add((subject, RDF.type, URIRef(self._class_uri)))
        
        object_props = getattr(self, '_object_properties', set())
        
        # Add properties
        if hasattr(self, '_property_uris'):
            for prop_name, prop_uri in self._property_uris.items():
                is_object_prop = prop_name in object_props
                prop_value = getattr(self, prop_name, None)
                if prop_value is not None:
                    if isinstance(prop_value, list):
                        for item in prop_value:
                            if hasattr(item, 'rdf'):
                                # Add triples from related object
                                g += item.rdf()
                                g.add((subject, URIRef(prop_uri), URIRef(item._uri)))
                            elif is_object_prop and isinstance(item, (str, URIRef)):
                                g.add((subject, URIRef(prop_uri), URIRef(str(item))))
                            else:
                                g.add((subject, URIRef(prop_uri), Literal(item)))
                    elif hasattr(prop_value, 'rdf'):
                        # Add triples from related object
                        g += prop_value.rdf()
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

    _class_uri: ClassVar[str] = 'http://purl.obolibrary.org/obo/phases/documents.owl#PDFPaperFile'
    _property_uris: ClassVar[dict] = {'creation_time': 'http://purl.obolibrary.org/obo/phases/documents.owl#creation_time', 'has_chunks': 'http://purl.obolibrary.org/obo/phases/documents.owl#has_chunks', 'path': 'http://purl.obolibrary.org/obo/phases/documents.owl#path', 'pdf_hash': 'http://purl.obolibrary.org/obo/phases/documents.owl#pdf_hash', 'pdfpaperfile_id': 'http://purl.obolibrary.org/obo/phases/documents.owl#pdfpaperfile_id'}
    _object_properties: ClassVar[set[str]] = {'has_chunks'}

    # Data properties
    creation_time: datetime.datetime = Field(...)
    path: Any = Field(...)
    pdf_hash: str = Field(...)
    pdfpaperfile_id: str = Field(...)

    # Object properties
    has_chunks: Optional[Union[str, Chunk]] = Field(default=None)

class Chunk(RDFEntity):
    """
    A chunk (e.g., a text segment and its vector embedding) modeled as a generically dependent continuant.
    """

    _class_uri: ClassVar[str] = 'http://purl.obolibrary.org/obo/phases/documents.owl#Chunk'
    _property_uris: ClassVar[dict] = {'chunk_hash': 'http://purl.obolibrary.org/obo/phases/documents.owl#chunk_hash', 'chunk_id': 'http://purl.obolibrary.org/obo/phases/documents.owl#chunk_id', 'chunk_number': 'http://purl.obolibrary.org/obo/phases/documents.owl#chunk_number', 'chunk_of': 'http://purl.obolibrary.org/obo/phases/documents.owl#chunk_of', 'has_embedding_occurrence': 'http://purl.obolibrary.org/obo/phases/documents.owl#has_embedding_occurrence', 'has_lexical_occurrence': 'http://purl.obolibrary.org/obo/phases/documents.owl#has_lexical_occurrence', 'text': 'http://purl.obolibrary.org/obo/phases/documents.owl#text'}
    _object_properties: ClassVar[set[str]] = {'chunk_of', 'has_embedding_occurrence', 'has_lexical_occurrence'}

    # Data properties
    chunk_hash: str = Field(...)
    chunk_id: str = Field(...)
    chunk_number: Optional[int] = Field(default=None)
    text: str = Field(...)

    # Object properties
    chunk_of: Union[str, PDFPaperFile] = Field(...)
    has_embedding_occurrence: Optional[Union[str, EmbeddingOccurrence]] = Field(default=None)
    has_lexical_occurrence: Optional[Union[str, LexicalOccurrence]] = Field(default=None)

class LexicalOccurrence(RDFEntity):
    """
    An observation that a lexical form (e.g., rdfs:label / skos:prefLabel) of an ontology entity appears in a Chunk text.
    """

    _class_uri: ClassVar[str] = 'http://purl.obolibrary.org/obo/phases/documents.owl#LexicalOccurrence'
    _property_uris: ClassVar[dict] = {'lexical_occurrence_in_chunk': 'http://purl.obolibrary.org/obo/phases/documents.owl#lexical_occurrence_in_chunk', 'lexical_occurrence_of': 'http://purl.obolibrary.org/obo/phases/documents.owl#lexical_occurrence_of', 'matched_predicate': 'http://purl.obolibrary.org/obo/phases/documents.owl#matched_predicate', 'matched_text': 'http://purl.obolibrary.org/obo/phases/documents.owl#matched_text'}
    _object_properties: ClassVar[set[str]] = {'lexical_occurrence_in_chunk', 'lexical_occurrence_of'}

    # Data properties
    matched_predicate: Any = Field(...)
    matched_text: str = Field(...)

    # Object properties
    lexical_occurrence_in_chunk: Union[str, Chunk] = Field(...)
    lexical_occurrence_of: Optional[Any] = Field(default=None)

class EmbeddingOccurrence(RDFEntity):
    """
    An observation that a vector embedding of an ontology entity appears in a Chunk text.
    """

    _class_uri: ClassVar[str] = 'http://purl.obolibrary.org/obo/phases/documents.owl#EmbeddingOccurrence'
    _property_uris: ClassVar[dict] = {'embedding_occurrence_in_chunk': 'http://purl.obolibrary.org/obo/phases/documents.owl#embedding_occurrence_in_chunk', 'embedding_occurrence_of': 'http://purl.obolibrary.org/obo/phases/documents.owl#embedding_occurrence_of', 'matched_predicate': 'http://purl.obolibrary.org/obo/phases/documents.owl#matched_predicate', 'matched_text': 'http://purl.obolibrary.org/obo/phases/documents.owl#matched_text'}
    _object_properties: ClassVar[set[str]] = {'embedding_occurrence_in_chunk', 'embedding_occurrence_of'}

    # Data properties
    matched_predicate: Any = Field(...)
    matched_text: str = Field(...)

    # Object properties
    embedding_occurrence_in_chunk: Union[str, Chunk] = Field(...)
    embedding_occurrence_of: Optional[Any] = Field(default=None)

# Rebuild models to resolve forward references
PDFPaperFile.model_rebuild()
Chunk.model_rebuild()
LexicalOccurrence.model_rebuild()
EmbeddingOccurrence.model_rebuild()
