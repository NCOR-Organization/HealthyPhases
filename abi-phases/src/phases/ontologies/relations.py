from __future__ import annotations

import datetime
import uuid
from typing import (
    Annotated,
    Any,
    Callable,
    ClassVar,
    Iterable,
    List,
    Optional,
    Union,
    get_args,
    get_origin,
)

from pydantic import BaseModel, Field, ValidationError
from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import OWL, RDF, RDFS, XSD

from phases.ontologies.bfo_core import (
    Continuant,
    Disposition,
    GenericallyDependentContinuant,
    MaterialEntity,
    Process,
    TemporalRegion,
)

BFO = Namespace("http://purl.obolibrary.org/obo/")
ABI = Namespace("http://ontology.naas.ai/abi/")
CCO = Namespace("https://www.commoncoreontologies.org/")


# Base class for all RDF entities
class RDFEntity(BaseModel):
    """Base class for all RDF entities with URI and namespace management"""

    _namespace: ClassVar[str] = "http://ontology.naas.ai/abi/"
    _uri: str = ""
    _object_properties: ClassVar[set[str]] = set()
    _query_executor: ClassVar[Callable[[str], Iterable[object]] | None] = None

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

    @classmethod
    def set_query_executor(
        cls, query_executor: Callable[[str], Iterable[object]] | None
    ):
        """Set the SPARQL query executor used by from_iri()."""
        cls._query_executor = query_executor

    @staticmethod
    def _extract_result_value(row: object, key: str) -> object | None:
        """Extract a SPARQL binding value from a ResultRow-like object."""
        if hasattr(row, key):
            return getattr(row, key)
        try:
            return row[key]  # type: ignore[index]
        except Exception:
            pass

        labels = getattr(row, "labels", None)
        if labels and key in labels:
            try:
                return row[key]  # type: ignore[index]
            except Exception:
                pass

        if isinstance(row, (list, tuple)):
            idx = 0 if key == "p" else 1
            if len(row) > idx:
                return row[idx]

        return None

    @staticmethod
    def _coerce_rdf_value(value: object, is_object_property: bool) -> object:
        """Convert RDFLib values to python values used by generated models."""
        if value is None:
            return None
        if is_object_property:
            return str(value)
        if isinstance(value, Literal):
            return value.toPython()
        return str(value)

    @staticmethod
    def _field_expects_list(field_annotation: object) -> bool:
        """Return True when a field annotation contains a list type."""
        origin = get_origin(field_annotation)
        if origin in (list, List):
            return True
        if origin is Annotated:
            args = get_args(field_annotation)
            if args:
                return RDFEntity._field_expects_list(args[0])
            return False
        if origin is Union:
            return any(
                RDFEntity._field_expects_list(arg)
                for arg in get_args(field_annotation)
                if arg is not type(None)
            )
        return False

    @staticmethod
    def _fallback_label_from_iri(iri: str) -> str:
        """Build a best-effort label from an IRI."""
        trimmed = iri.rstrip("/")
        if "#" in trimmed:
            return trimmed.split("#")[-1] or trimmed
        return trimmed.split("/")[-1] or trimmed

    @classmethod
    def from_iri(
        cls,
        iri: str,
        query_executor: Callable[[str], Iterable[object]] | None = None,
        graph_name: str | None = None,
    ):
        """Load a class instance from an IRI using SPARQL query results."""
        iri = str(iri).strip()
        if not iri:
            raise ValueError("iri must be a non-empty string")
        if "<" in iri or ">" in iri:
            raise ValueError("iri must not contain angle brackets")
        if graph_name is not None:
            graph_name = str(graph_name).strip()
            if not graph_name:
                graph_name = None
            elif "<" in graph_name or ">" in graph_name:
                raise ValueError("graph_name must not contain angle brackets")

        executor = query_executor or cls._query_executor
        if executor is None:
            raise ValueError(
                "No query executor configured. Pass query_executor to from_iri() "
                "or set it with set_query_executor()."
            )

        if graph_name:
            sparql_query = f"""
                SELECT ?p ?o
                WHERE {{
                    GRAPH <{graph_name}> {{
                        <{iri}> ?p ?o .
                        FILTER(?p != <http://www.w3.org/1999/02/22-rdf-syntax-ns#type>)
                    }}
                }}
            """
        else:
            sparql_query = f"""
                SELECT ?p ?o
                WHERE {{
                    <{iri}> ?p ?o .
                    FILTER(?p != <http://www.w3.org/1999/02/22-rdf-syntax-ns#type>)
                }}
            """

        results = executor(sparql_query)
        reverse_property_uris = {
            prop_uri: prop_name
            for prop_name, prop_uri in getattr(cls, "_property_uris", {}).items()
        }
        object_props: set[str] = getattr(cls, "_object_properties", set())
        model_fields = getattr(cls, "model_fields", {})
        values: dict[str, Any] = {}

        for row in results:  # type: ignore[assignment]
            predicate = cls._extract_result_value(row, "p")
            obj = cls._extract_result_value(row, "o")
            if predicate is None:
                continue
            prop_name = reverse_property_uris.get(str(predicate))
            if not prop_name:
                continue

            coerced = cls._coerce_rdf_value(
                obj,
                is_object_property=prop_name in object_props,
            )
            field_info = model_fields.get(prop_name)
            expects_list = False
            if field_info is not None:
                expects_list = cls._field_expects_list(field_info.annotation)

            if prop_name not in values:
                if expects_list:
                    values[prop_name] = [coerced]
                else:
                    values[prop_name] = coerced
            else:
                existing = values[prop_name]
                if isinstance(existing, list):
                    existing.append(coerced)
                elif expects_list:
                    values[prop_name] = [existing, coerced]
                else:
                    values[prop_name] = existing

        if "label" in model_fields and "label" not in values:
            values["label"] = cls._fallback_label_from_iri(iri)

        for field_name, field_info in model_fields.items():
            if field_name in values:
                continue
            if field_info.is_required():
                if cls._field_expects_list(field_info.annotation):
                    values[field_name] = []
                else:
                    values[field_name] = None

        try:
            return cls(_uri=iri, **values)
        except ValidationError:
            # Keep loading permissive for partially populated RDF resources.
            return cls.model_construct(
                _fields_set=set(values.keys()), _uri=iri, **values
            )

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


class InferredLabelRelation(GenericallyDependentContinuant, RDFEntity):
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
        "continuant_part_of": "http://purl.obolibrary.org/obo/BFO_0000176",
        "cooccurrence_count": "http://purl.obolibrary.org/obo/phases/relations.owl#co_occurrence_count",
        "cooccurrence_score": "http://purl.obolibrary.org/obo/phases/relations.owl#co_occurrence_score",
        "created": "http://purl.org/dc/terms/created",
        "creation_time": "http://purl.obolibrary.org/obo/phases/relations.owl#creation_time",
        "creator": "http://purl.org/dc/terms/creator",
        "directional_score": "http://purl.obolibrary.org/obo/phases/relations.owl#directional_score",
        "evidence_paths_count": "http://purl.obolibrary.org/obo/phases/relations.owl#evidence_paths_count",
        "exclusive_to_target_confidence": "http://purl.obolibrary.org/obo/phases/relations.owl#exclusive_to_target_confidence",
        "exists_at": "http://purl.obolibrary.org/obo/BFO_0000108",
        "forward_axiom_votes": "http://purl.obolibrary.org/obo/phases/relations.owl#forward_axiom_votes",
        "generically_depends_on": "http://purl.obolibrary.org/obo/BFO_0000084",
        "has_continuant_part": "http://purl.obolibrary.org/obo/BFO_0000178",
        "is_concretized_by": "http://purl.obolibrary.org/obo/BFO_0000058",
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
        "continuant_part_of",
        "exists_at",
        "generically_depends_on",
        "has_continuant_part",
        "is_concretized_by",
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
    cooccurrence_score: Optional[Annotated[float, Field()]] = None
    directional_score: Optional[Annotated[float, Field()]] = None
    stability_score: Optional[Annotated[float, Field()]] = None
    cooccurrence_count: Optional[Annotated[int, Field()]] = None
    forward_axiom_votes: Optional[Annotated[int, Field()]] = None
    reverse_axiom_votes: Optional[Annotated[int, Field()]] = None
    evidence_paths_count: Optional[Annotated[int, Field()]] = None
    best_alternative_target: Optional[Annotated[str, Field()]] = None
    best_alternative_support: Optional[Annotated[float, Field()]] = None
    creation_time: Annotated[datetime.datetime, Field()]
    label: Optional[Annotated[str, Field(description="Label of the resource.")]] = None
    created: Optional[
        Annotated[
            datetime.datetime,
            Field(description="Date of creation of the resource."),
        ]
    ] = None
    creator: Optional[
        Annotated[
            Any,
            Field(description="An entity responsible for making the resource."),
        ]
    ] = None

    # Object properties
    continuant_part_of: Optional[
        Annotated[
            List[Union[Continuant, URIRef, str]],
            Field(
                description="b continuant part of c =Def b and c are continuants & there is some time t such that b and c exist at t & b continuant part of c at t"
            ),
        ]
    ] = None
    exists_at: Optional[
        Annotated[
            List[Union[TemporalRegion, URIRef, str]],
            Field(
                description="(Elucidation) exists at is a relation between a particular and some temporal region at which the particular exists"
            ),
        ]
    ] = None
    generically_depends_on: Optional[
        Annotated[
            Union[URIRef, str],
            Field(
                description="b generically depends on c =Def b is a generically dependent continuant & c is an independent continuant that is not a spatial region & at some time t there inheres in c a specifically dependent continuant which concretizes b at t"
            ),
        ]
    ] = None
    has_continuant_part: Optional[
        Annotated[
            List[Union[Continuant, URIRef, str]],
            Field(description="b has continuant part c =Def c continuant part of b"),
        ]
    ] = None
    is_concretized_by: Optional[
        Annotated[
            Union[URIRef, str],
            Field(description="c is concretized by b =Def b concretizes c"),
        ]
    ] = None
    relation_from_label: Optional[Annotated[Union[URIRef, str], Field()]] = None
    relation_to_label: Optional[Annotated[Union[URIRef, str], Field()]] = None
    supported_by_axiom: Optional[Annotated[Union[URIRef, str], Field()]] = None
    supported_by_chunk: Optional[Annotated[Union[URIRef, str], Field()]] = None


class ProbabilitymodulatingDisposition(Disposition, RDFEntity):
    """
    A BFO disposition borne by an independent continuant whose realization in a process modulates the probability that some other (target) process occurs.
    """

    _class_uri: ClassVar[str] = (
        "http://purl.obolibrary.org/obo/phases/relations.owl#ProbabilityModulatingDisposition"
    )
    _name: ClassVar[str] = "probability-modulating disposition"
    _property_uris: ClassVar[dict] = {
        "continuant_part_of": "http://purl.obolibrary.org/obo/BFO_0000176",
        "created": "http://purl.org/dc/terms/created",
        "creator": "http://purl.org/dc/terms/creator",
        "disposition_target_process": "http://purl.obolibrary.org/obo/phases/relations.owl#disposition_target_process",
        "exists_at": "http://purl.obolibrary.org/obo/BFO_0000108",
        "has_continuant_part": "http://purl.obolibrary.org/obo/BFO_0000178",
        "has_material_basis": "http://purl.obolibrary.org/obo/BFO_0000218",
        "has_realization": "http://purl.obolibrary.org/obo/BFO_0000054",
        "inheres_in": "http://purl.obolibrary.org/obo/BFO_0000197",
        "label": "http://www.w3.org/2000/01/rdf-schema#label",
        "specifically_depends_on": "http://purl.obolibrary.org/obo/BFO_0000195",
    }
    _object_properties: ClassVar[set[str]] = {
        "continuant_part_of",
        "disposition_target_process",
        "exists_at",
        "has_continuant_part",
        "has_material_basis",
        "has_realization",
        "inheres_in",
        "specifically_depends_on",
    }

    # Data properties
    label: Optional[Annotated[str, Field(description="Label of the resource.")]] = None
    created: Optional[
        Annotated[
            datetime.datetime,
            Field(description="Date of creation of the resource."),
        ]
    ] = None
    creator: Optional[
        Annotated[
            Any,
            Field(description="An entity responsible for making the resource."),
        ]
    ] = None

    # Object properties
    continuant_part_of: Optional[
        Annotated[
            List[Union[Continuant, URIRef, str]],
            Field(
                description="b continuant part of c =Def b and c are continuants & there is some time t such that b and c exist at t & b continuant part of c at t"
            ),
        ]
    ] = None
    disposition_target_process: Optional[
        Annotated[List[Union[Process, URIRef, str]], Field()]
    ] = None
    exists_at: Optional[
        Annotated[
            List[Union[TemporalRegion, URIRef, str]],
            Field(
                description="(Elucidation) exists at is a relation between a particular and some temporal region at which the particular exists"
            ),
        ]
    ] = None
    has_continuant_part: Optional[
        Annotated[
            List[Union[Continuant, URIRef, str]],
            Field(description="b has continuant part c =Def c continuant part of b"),
        ]
    ] = None
    has_material_basis: Optional[
        Annotated[
            List[Union[MaterialEntity, URIRef, str]],
            Field(
                description="b has material basis c =Def b is a disposition & c is a material entity & there is some d bearer of b & there is some time t such that c is a continuant part of d at t & d has disposition b because c is a continuant part of d at t"
            ),
        ]
    ] = None
    has_realization: Optional[
        Annotated[
            List[Union[Process, URIRef, str]],
            Field(description="b has realization c =Def c realizes b"),
        ]
    ] = None
    inheres_in: Optional[
        Annotated[
            Union[URIRef, str],
            Field(
                description="b inheres in c =Def b is a specifically dependent continuant & c is an independent continuant that is not a spatial region & b specifically depends on c"
            ),
        ]
    ] = None
    specifically_depends_on: Optional[
        Annotated[
            Union[URIRef, str],
            Field(
                description="(Elucidation) specifically depends on is a relation between a specifically dependent continuant b and specifically dependent continuant or independent continuant that is not a spatial region c such that b and c share no parts in common & b is of a nature such that at all times t it cannot exist unless c exists & b is not a boundary of c"
            ),
        ]
    ] = None


class IncreaseprobabilityDisposition(ProbabilitymodulatingDisposition, RDFEntity):
    """
    A probability-modulating disposition whose realization increases the probability that the target process occurs.
    """

    _class_uri: ClassVar[str] = (
        "http://purl.obolibrary.org/obo/phases/relations.owl#IncreaseProbabilityDisposition"
    )
    _name: ClassVar[str] = "increase-probability disposition"
    _property_uris: ClassVar[dict] = {
        "continuant_part_of": "http://purl.obolibrary.org/obo/BFO_0000176",
        "created": "http://purl.org/dc/terms/created",
        "creator": "http://purl.org/dc/terms/creator",
        "disposition_target_process": "http://purl.obolibrary.org/obo/phases/relations.owl#disposition_target_process",
        "exists_at": "http://purl.obolibrary.org/obo/BFO_0000108",
        "has_continuant_part": "http://purl.obolibrary.org/obo/BFO_0000178",
        "has_material_basis": "http://purl.obolibrary.org/obo/BFO_0000218",
        "has_realization": "http://purl.obolibrary.org/obo/BFO_0000054",
        "inheres_in": "http://purl.obolibrary.org/obo/BFO_0000197",
        "label": "http://www.w3.org/2000/01/rdf-schema#label",
        "specifically_depends_on": "http://purl.obolibrary.org/obo/BFO_0000195",
    }
    _object_properties: ClassVar[set[str]] = {
        "continuant_part_of",
        "disposition_target_process",
        "exists_at",
        "has_continuant_part",
        "has_material_basis",
        "has_realization",
        "inheres_in",
        "specifically_depends_on",
    }

    # Data properties
    label: Optional[Annotated[str, Field(description="Label of the resource.")]] = None
    created: Optional[
        Annotated[
            datetime.datetime,
            Field(description="Date of creation of the resource."),
        ]
    ] = None
    creator: Optional[
        Annotated[
            Any,
            Field(description="An entity responsible for making the resource."),
        ]
    ] = None

    # Object properties
    continuant_part_of: Optional[
        Annotated[
            List[Union[Continuant, URIRef, str]],
            Field(
                description="b continuant part of c =Def b and c are continuants & there is some time t such that b and c exist at t & b continuant part of c at t"
            ),
        ]
    ] = None
    disposition_target_process: Optional[
        Annotated[List[Union[Process, URIRef, str]], Field()]
    ] = None
    exists_at: Optional[
        Annotated[
            List[Union[TemporalRegion, URIRef, str]],
            Field(
                description="(Elucidation) exists at is a relation between a particular and some temporal region at which the particular exists"
            ),
        ]
    ] = None
    has_continuant_part: Optional[
        Annotated[
            List[Union[Continuant, URIRef, str]],
            Field(description="b has continuant part c =Def c continuant part of b"),
        ]
    ] = None
    has_material_basis: Optional[
        Annotated[
            List[Union[MaterialEntity, URIRef, str]],
            Field(
                description="b has material basis c =Def b is a disposition & c is a material entity & there is some d bearer of b & there is some time t such that c is a continuant part of d at t & d has disposition b because c is a continuant part of d at t"
            ),
        ]
    ] = None
    has_realization: Optional[
        Annotated[
            List[Union[Process, URIRef, str]],
            Field(description="b has realization c =Def c realizes b"),
        ]
    ] = None
    inheres_in: Optional[
        Annotated[
            Union[URIRef, str],
            Field(
                description="b inheres in c =Def b is a specifically dependent continuant & c is an independent continuant that is not a spatial region & b specifically depends on c"
            ),
        ]
    ] = None
    specifically_depends_on: Optional[
        Annotated[
            Union[URIRef, str],
            Field(
                description="(Elucidation) specifically depends on is a relation between a specifically dependent continuant b and specifically dependent continuant or independent continuant that is not a spatial region c such that b and c share no parts in common & b is of a nature such that at all times t it cannot exist unless c exists & b is not a boundary of c"
            ),
        ]
    ] = None


class DecreaseprobabilityDisposition(ProbabilitymodulatingDisposition, RDFEntity):
    """
    A probability-modulating disposition whose realization decreases the probability that the target process occurs.
    """

    _class_uri: ClassVar[str] = (
        "http://purl.obolibrary.org/obo/phases/relations.owl#DecreaseProbabilityDisposition"
    )
    _name: ClassVar[str] = "decrease-probability disposition"
    _property_uris: ClassVar[dict] = {
        "continuant_part_of": "http://purl.obolibrary.org/obo/BFO_0000176",
        "created": "http://purl.org/dc/terms/created",
        "creator": "http://purl.org/dc/terms/creator",
        "disposition_target_process": "http://purl.obolibrary.org/obo/phases/relations.owl#disposition_target_process",
        "exists_at": "http://purl.obolibrary.org/obo/BFO_0000108",
        "has_continuant_part": "http://purl.obolibrary.org/obo/BFO_0000178",
        "has_material_basis": "http://purl.obolibrary.org/obo/BFO_0000218",
        "has_realization": "http://purl.obolibrary.org/obo/BFO_0000054",
        "inheres_in": "http://purl.obolibrary.org/obo/BFO_0000197",
        "label": "http://www.w3.org/2000/01/rdf-schema#label",
        "specifically_depends_on": "http://purl.obolibrary.org/obo/BFO_0000195",
    }
    _object_properties: ClassVar[set[str]] = {
        "continuant_part_of",
        "disposition_target_process",
        "exists_at",
        "has_continuant_part",
        "has_material_basis",
        "has_realization",
        "inheres_in",
        "specifically_depends_on",
    }

    # Data properties
    label: Optional[Annotated[str, Field(description="Label of the resource.")]] = None
    created: Optional[
        Annotated[
            datetime.datetime,
            Field(description="Date of creation of the resource."),
        ]
    ] = None
    creator: Optional[
        Annotated[
            Any,
            Field(description="An entity responsible for making the resource."),
        ]
    ] = None

    # Object properties
    continuant_part_of: Optional[
        Annotated[
            List[Union[Continuant, URIRef, str]],
            Field(
                description="b continuant part of c =Def b and c are continuants & there is some time t such that b and c exist at t & b continuant part of c at t"
            ),
        ]
    ] = None
    disposition_target_process: Optional[
        Annotated[List[Union[Process, URIRef, str]], Field()]
    ] = None
    exists_at: Optional[
        Annotated[
            List[Union[TemporalRegion, URIRef, str]],
            Field(
                description="(Elucidation) exists at is a relation between a particular and some temporal region at which the particular exists"
            ),
        ]
    ] = None
    has_continuant_part: Optional[
        Annotated[
            List[Union[Continuant, URIRef, str]],
            Field(description="b has continuant part c =Def c continuant part of b"),
        ]
    ] = None
    has_material_basis: Optional[
        Annotated[
            List[Union[MaterialEntity, URIRef, str]],
            Field(
                description="b has material basis c =Def b is a disposition & c is a material entity & there is some d bearer of b & there is some time t such that c is a continuant part of d at t & d has disposition b because c is a continuant part of d at t"
            ),
        ]
    ] = None
    has_realization: Optional[
        Annotated[
            List[Union[Process, URIRef, str]],
            Field(description="b has realization c =Def c realizes b"),
        ]
    ] = None
    inheres_in: Optional[
        Annotated[
            Union[URIRef, str],
            Field(
                description="b inheres in c =Def b is a specifically dependent continuant & c is an independent continuant that is not a spatial region & b specifically depends on c"
            ),
        ]
    ] = None
    specifically_depends_on: Optional[
        Annotated[
            Union[URIRef, str],
            Field(
                description="(Elucidation) specifically depends on is a relation between a specifically dependent continuant b and specifically dependent continuant or independent continuant that is not a spatial region c such that b and c share no parts in common & b is of a nature such that at all times t it cannot exist unless c exists & b is not a boundary of c"
            ),
        ]
    ] = None


class NoeffectProbabilityDisposition(ProbabilitymodulatingDisposition, RDFEntity):
    """
    A probability-modulating disposition whose realization has no measurable effect on the probability that the target process occurs (used to capture explicit null findings).
    """

    _class_uri: ClassVar[str] = (
        "http://purl.obolibrary.org/obo/phases/relations.owl#NoEffectProbabilityDisposition"
    )
    _name: ClassVar[str] = "no-effect probability disposition"
    _property_uris: ClassVar[dict] = {
        "continuant_part_of": "http://purl.obolibrary.org/obo/BFO_0000176",
        "created": "http://purl.org/dc/terms/created",
        "creator": "http://purl.org/dc/terms/creator",
        "disposition_target_process": "http://purl.obolibrary.org/obo/phases/relations.owl#disposition_target_process",
        "exists_at": "http://purl.obolibrary.org/obo/BFO_0000108",
        "has_continuant_part": "http://purl.obolibrary.org/obo/BFO_0000178",
        "has_material_basis": "http://purl.obolibrary.org/obo/BFO_0000218",
        "has_realization": "http://purl.obolibrary.org/obo/BFO_0000054",
        "inheres_in": "http://purl.obolibrary.org/obo/BFO_0000197",
        "label": "http://www.w3.org/2000/01/rdf-schema#label",
        "specifically_depends_on": "http://purl.obolibrary.org/obo/BFO_0000195",
    }
    _object_properties: ClassVar[set[str]] = {
        "continuant_part_of",
        "disposition_target_process",
        "exists_at",
        "has_continuant_part",
        "has_material_basis",
        "has_realization",
        "inheres_in",
        "specifically_depends_on",
    }

    # Data properties
    label: Optional[Annotated[str, Field(description="Label of the resource.")]] = None
    created: Optional[
        Annotated[
            datetime.datetime,
            Field(description="Date of creation of the resource."),
        ]
    ] = None
    creator: Optional[
        Annotated[
            Any,
            Field(description="An entity responsible for making the resource."),
        ]
    ] = None

    # Object properties
    continuant_part_of: Optional[
        Annotated[
            List[Union[Continuant, URIRef, str]],
            Field(
                description="b continuant part of c =Def b and c are continuants & there is some time t such that b and c exist at t & b continuant part of c at t"
            ),
        ]
    ] = None
    disposition_target_process: Optional[
        Annotated[List[Union[Process, URIRef, str]], Field()]
    ] = None
    exists_at: Optional[
        Annotated[
            List[Union[TemporalRegion, URIRef, str]],
            Field(
                description="(Elucidation) exists at is a relation between a particular and some temporal region at which the particular exists"
            ),
        ]
    ] = None
    has_continuant_part: Optional[
        Annotated[
            List[Union[Continuant, URIRef, str]],
            Field(description="b has continuant part c =Def c continuant part of b"),
        ]
    ] = None
    has_material_basis: Optional[
        Annotated[
            List[Union[MaterialEntity, URIRef, str]],
            Field(
                description="b has material basis c =Def b is a disposition & c is a material entity & there is some d bearer of b & there is some time t such that c is a continuant part of d at t & d has disposition b because c is a continuant part of d at t"
            ),
        ]
    ] = None
    has_realization: Optional[
        Annotated[
            List[Union[Process, URIRef, str]],
            Field(description="b has realization c =Def c realizes b"),
        ]
    ] = None
    inheres_in: Optional[
        Annotated[
            Union[URIRef, str],
            Field(
                description="b inheres in c =Def b is a specifically dependent continuant & c is an independent continuant that is not a spatial region & b specifically depends on c"
            ),
        ]
    ] = None
    specifically_depends_on: Optional[
        Annotated[
            Union[URIRef, str],
            Field(
                description="(Elucidation) specifically depends on is a relation between a specifically dependent continuant b and specifically dependent continuant or independent continuant that is not a spatial region c such that b and c share no parts in common & b is of a nature such that at all times t it cannot exist unless c exists & b is not a boundary of c"
            ),
        ]
    ] = None


# Rebuild models to resolve forward references
InferredLabelRelation.model_rebuild()
ProbabilitymodulatingDisposition.model_rebuild()
IncreaseprobabilityDisposition.model_rebuild()
DecreaseprobabilityDisposition.model_rebuild()
NoeffectProbabilityDisposition.model_rebuild()
