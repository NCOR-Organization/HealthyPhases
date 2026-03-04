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


class ExtractedAxiom(RDFEntity):
    """
    An axiom statement extracted from a text chunk by an LLM.
    """

    _class_uri: ClassVar[str] = 'http://purl.obolibrary.org/obo/phases/axioms.owl#ExtractedAxiom'
    _property_uris: ClassVar[dict] = {'axiom_from_chunk': 'http://purl.obolibrary.org/obo/phases/axioms.owl#axiom_from_chunk', 'axiom_hash': 'http://purl.obolibrary.org/obo/phases/axioms.owl#axiom_hash', 'axiom_id': 'http://purl.obolibrary.org/obo/phases/axioms.owl#axiom_id', 'axiom_number': 'http://purl.obolibrary.org/obo/phases/axioms.owl#axiom_number', 'axiom_text': 'http://purl.obolibrary.org/obo/phases/axioms.owl#axiom_text', 'creation_time': 'http://purl.obolibrary.org/obo/phases/axioms.owl#creation_time', 'generated_by_model': 'http://purl.obolibrary.org/obo/phases/axioms.owl#generated_by_model', 'prompt_version': 'http://purl.obolibrary.org/obo/phases/axioms.owl#prompt_version', 'source_chunk_id': 'http://purl.obolibrary.org/obo/phases/axioms.owl#source_chunk_id'}
    _object_properties: ClassVar[set[str]] = {'axiom_from_chunk'}

    # Data properties
    axiom_hash: str = Field(...)
    axiom_id: str = Field(...)
    axiom_number: Optional[int] = Field(default=None)
    axiom_text: str = Field(...)
    creation_time: datetime.datetime = Field(...)
    generated_by_model: Optional[str] = Field(default=None)
    prompt_version: Optional[str] = Field(default=None)
    source_chunk_id: Optional[str] = Field(default=None)

    # Object properties
    axiom_from_chunk: Optional[Any] = Field(default=None)

# Rebuild models to resolve forward references
ExtractedAxiom.model_rebuild()
