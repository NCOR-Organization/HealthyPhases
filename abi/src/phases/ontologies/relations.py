from __future__ import annotations
from typing import Annotated, Any, ClassVar, List, Optional, Union
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


class InferredLabelRelation(RDFEntity):
    """
    A probabilistic relation inferred between two canonical label texts from chunk-level co-occurrence and axiom directional evidence.
    """

    _class_uri: ClassVar[str] = (
        "http://purl.obolibrary.org/obo/phases/relations.owl#InferredLabelRelation"
    )
    _name: ClassVar[str] = "inferred label relation"
    _property_uris: ClassVar[dict] = {
        "belongs_confidence": "http://purl.obolibrary.org/obo/phases/relations.owl#belongs_confidence",
        "best_alternative_support": "http://purl.obolibrary.org/obo/phases/relations.owl#best_alternative_support",
        "best_alternative_target": "http://purl.obolibrary.org/obo/phases/relations.owl#best_alternative_target",
        "cooccurrence_count": "http://purl.obolibrary.org/obo/phases/relations.owl#co_occurrence_count",
        "cooccurrence_score": "http://purl.obolibrary.org/obo/phases/relations.owl#co_occurrence_score",
        "created": "http://purl.org/dc/terms/created",
        "creation_time": "http://purl.obolibrary.org/obo/phases/relations.owl#creation_time",
        "creator": "http://purl.org/dc/terms/creator",
        "directional_score": "http://purl.obolibrary.org/obo/phases/relations.owl#directional_score",
        "evidence_paths_count": "http://purl.obolibrary.org/obo/phases/relations.owl#evidence_paths_count",
        "exclusive_to_target_confidence": "http://purl.obolibrary.org/obo/phases/relations.owl#exclusive_to_target_confidence",
        "forward_axiom_votes": "http://purl.obolibrary.org/obo/phases/relations.owl#forward_axiom_votes",
        "label": "http://www.w3.org/2000/01/rdf-schema#label",
        "relation_from_label": "http://purl.obolibrary.org/obo/phases/relations.owl#relation_from_label",
        "relation_id": "http://purl.obolibrary.org/obo/phases/relations.owl#relation_id",
        "relation_to_label": "http://purl.obolibrary.org/obo/phases/relations.owl#relation_to_label",
        "relation_type": "http://purl.obolibrary.org/obo/phases/relations.owl#relation_type",
        "reverse_axiom_votes": "http://purl.obolibrary.org/obo/phases/relations.owl#reverse_axiom_votes",
        "source_label_text": "http://purl.obolibrary.org/obo/phases/relations.owl#source_label_text",
        "stability_score": "http://purl.obolibrary.org/obo/phases/relations.owl#stability_score",
        "supported_by_axiom": "http://purl.obolibrary.org/obo/phases/relations.owl#supported_by_axiom",
        "supported_by_chunk": "http://purl.obolibrary.org/obo/phases/relations.owl#supported_by_chunk",
        "target_label_text": "http://purl.obolibrary.org/obo/phases/relations.owl#target_label_text",
    }
    _object_properties: ClassVar[set[str]] = {
        "relation_from_label",
        "relation_to_label",
        "supported_by_axiom",
        "supported_by_chunk",
    }

    # Data properties
    relation_id: Annotated[str, Field()]
    source_label_text: Annotated[str, Field()]
    target_label_text: Annotated[str, Field()]
    relation_type: Annotated[str, Field()]
    belongs_confidence: Annotated[float, Field()]
    exclusive_to_target_confidence: Annotated[float, Field()]
    cooccurrence_score: Optional[Annotated[float, Field()]] = "unknown"
    directional_score: Optional[Annotated[float, Field()]] = "unknown"
    stability_score: Optional[Annotated[float, Field()]] = "unknown"
    cooccurrence_count: Optional[Annotated[int, Field()]] = "unknown"
    forward_axiom_votes: Optional[Annotated[int, Field()]] = "unknown"
    reverse_axiom_votes: Optional[Annotated[int, Field()]] = "unknown"
    evidence_paths_count: Optional[Annotated[int, Field()]] = "unknown"
    best_alternative_target: Optional[Annotated[str, Field()]] = "unknown"
    best_alternative_support: Optional[Annotated[float, Field()]] = "unknown"
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
    relation_from_label: Optional[
        Annotated[List[Union[ExtractedLabel, URIRef, str]], Field()]
    ] = ["http://ontology.naas.ai/abi/unknown"]
    relation_to_label: Optional[
        Annotated[List[Union[ExtractedLabel, URIRef, str]], Field()]
    ] = ["http://ontology.naas.ai/abi/unknown"]
    supported_by_axiom: Optional[
        Annotated[List[Union[ExtractedAxiom, URIRef, str]], Field()]
    ] = ["http://ontology.naas.ai/abi/unknown"]
    supported_by_chunk: Optional[
        Annotated[List[Union[Chunk, URIRef, str]], Field()]
    ] = ["http://ontology.naas.ai/abi/unknown"]


# Rebuild models to resolve forward references
from phases.ontologies.documents import Chunk
from phases.ontologies.labels import ExtractedLabel
from phases.ontologies.axioms import ExtractedAxiom

InferredLabelRelation.model_rebuild(
    _types_namespace={
        "Chunk": Chunk,
        "ExtractedLabel": ExtractedLabel,
        "ExtractedAxiom": ExtractedAxiom,
    }
)
