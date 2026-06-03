from __future__ import annotations

import datetime
import os
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


class Entity(RDFEntity):
    """
    entity
    """

    _class_uri: ClassVar[str] = "http://purl.obolibrary.org/obo/BFO_0000001"
    _name: ClassVar[str] = "entity"
    _property_uris: ClassVar[dict] = {
        "created": "http://purl.org/dc/terms/created",
        "creator": "http://purl.org/dc/terms/creator",
        "exists_at": "http://purl.obolibrary.org/obo/BFO_0000108",
        "label": "http://www.w3.org/2000/01/rdf-schema#label",
    }
    _object_properties: ClassVar[set[str]] = {"exists_at"}

    # Data properties
    label: Optional[Annotated[str, Field(description="Label of the resource.")]] = None
    created: Annotated[
        Optional[datetime.datetime],
        Field(description="Date of creation of the resource."),
    ] = datetime.datetime.now()
    creator: Annotated[
        Optional[Any],
        Field(description="An entity responsible for making the resource."),
    ] = os.environ.get("USER")

    # Object properties
    exists_at: Optional[
        Annotated[
            List[Union[TemporalRegion, URIRef, str]],
            Field(
                description="(Elucidation) exists at is a relation between a particular and some temporal region at which the particular exists"
            ),
        ]
    ] = None


class Continuant(Entity, RDFEntity):
    """
    continuant
    """

    _class_uri: ClassVar[str] = "http://purl.obolibrary.org/obo/BFO_0000002"
    _name: ClassVar[str] = "continuant"
    _property_uris: ClassVar[dict] = {
        "continuant_part_of": "http://purl.obolibrary.org/obo/BFO_0000176",
        "created": "http://purl.org/dc/terms/created",
        "creator": "http://purl.org/dc/terms/creator",
        "exists_at": "http://purl.obolibrary.org/obo/BFO_0000108",
        "has_continuant_part": "http://purl.obolibrary.org/obo/BFO_0000178",
        "label": "http://www.w3.org/2000/01/rdf-schema#label",
    }
    _object_properties: ClassVar[set[str]] = {
        "continuant_part_of",
        "exists_at",
        "has_continuant_part",
    }

    # Data properties
    label: Optional[Annotated[str, Field(description="Label of the resource.")]] = None
    created: Annotated[
        Optional[datetime.datetime],
        Field(description="Date of creation of the resource."),
    ] = datetime.datetime.now()
    creator: Annotated[
        Optional[Any],
        Field(description="An entity responsible for making the resource."),
    ] = os.environ.get("USER")

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
    has_continuant_part: Optional[
        Annotated[
            List[Union[Continuant, URIRef, str]],
            Field(description="b has continuant part c =Def c continuant part of b"),
        ]
    ] = None


class Occurrent(Entity, RDFEntity):
    """
    occurrent
    """

    _class_uri: ClassVar[str] = "http://purl.obolibrary.org/obo/BFO_0000003"
    _name: ClassVar[str] = "occurrent"
    _property_uris: ClassVar[dict] = {
        "created": "http://purl.org/dc/terms/created",
        "creator": "http://purl.org/dc/terms/creator",
        "exists_at": "http://purl.obolibrary.org/obo/BFO_0000108",
        "has_occurrent_part": "http://purl.obolibrary.org/obo/BFO_0000117",
        "has_temporal_part": "http://purl.obolibrary.org/obo/BFO_0000121",
        "label": "http://www.w3.org/2000/01/rdf-schema#label",
        "occurrent_part_of": "http://purl.obolibrary.org/obo/BFO_0000132",
        "preceded_by": "http://purl.obolibrary.org/obo/BFO_0000062",
        "precedes": "http://purl.obolibrary.org/obo/BFO_0000063",
        "temporal_part_of": "http://purl.obolibrary.org/obo/BFO_0000139",
    }
    _object_properties: ClassVar[set[str]] = {
        "exists_at",
        "has_occurrent_part",
        "has_temporal_part",
        "occurrent_part_of",
        "preceded_by",
        "precedes",
        "temporal_part_of",
    }

    # Data properties
    label: Optional[Annotated[str, Field(description="Label of the resource.")]] = None
    created: Annotated[
        Optional[datetime.datetime],
        Field(description="Date of creation of the resource."),
    ] = datetime.datetime.now()
    creator: Annotated[
        Optional[Any],
        Field(description="An entity responsible for making the resource."),
    ] = os.environ.get("USER")

    # Object properties
    exists_at: Optional[
        Annotated[
            List[Union[TemporalRegion, URIRef, str]],
            Field(
                description="(Elucidation) exists at is a relation between a particular and some temporal region at which the particular exists"
            ),
        ]
    ] = None
    has_occurrent_part: Optional[
        Annotated[
            List[Union[Occurrent, URIRef, str]],
            Field(description="b has occurrent part c =Def c occurrent part of b"),
        ]
    ] = None
    has_temporal_part: Optional[
        Annotated[
            List[Union[Occurrent, URIRef, str]],
            Field(description="b has temporal part c =Def c temporal part of b"),
        ]
    ] = None
    occurrent_part_of: Optional[
        Annotated[
            List[Union[Occurrent, URIRef, str]],
            Field(
                description="(Elucidation) occurrent part of is a relation between occurrents b and c when b is part of c"
            ),
        ]
    ] = None
    preceded_by: Optional[
        Annotated[
            List[Union[Occurrent, URIRef, str]],
            Field(description="b preceded by c =Def b precedes c"),
        ]
    ] = None
    precedes: Optional[
        Annotated[
            List[Union[Occurrent, URIRef, str]],
            Field(
                description="(Elucidation) precedes is a relation between occurrents o, o' such that if t is the temporal extent of o & t' is the temporal extent of o' then either the last instant of o is before the first instant of o' or the last instant of o is the first instant of o' & neither o nor o' are temporal instants"
            ),
        ]
    ] = None
    temporal_part_of: Optional[
        Annotated[
            List[Union[Occurrent, URIRef, str]],
            Field(
                description="b temporal part of c =Def b occurrent part of c & (b and c are temporal regions) or (b and c are spatiotemporal regions & b temporally projects onto an occurrent part of the temporal region that c temporally projects onto) or (b and c are processes or process boundaries & b occupies a temporal region that is an occurrent part of the temporal region that c occupies)"
            ),
        ]
    ] = None


class IndependentContinuant(Continuant, RDFEntity):
    """
    independent continuant
    """

    _class_uri: ClassVar[str] = "http://purl.obolibrary.org/obo/BFO_0000004"
    _name: ClassVar[str] = "independent continuant"
    _property_uris: ClassVar[dict] = {
        "continuant_part_of": "http://purl.obolibrary.org/obo/BFO_0000176",
        "created": "http://purl.org/dc/terms/created",
        "creator": "http://purl.org/dc/terms/creator",
        "exists_at": "http://purl.obolibrary.org/obo/BFO_0000108",
        "has_continuant_part": "http://purl.obolibrary.org/obo/BFO_0000178",
        "label": "http://www.w3.org/2000/01/rdf-schema#label",
    }
    _object_properties: ClassVar[set[str]] = {
        "continuant_part_of",
        "exists_at",
        "has_continuant_part",
    }

    # Data properties
    label: Optional[Annotated[str, Field(description="Label of the resource.")]] = None
    created: Annotated[
        Optional[datetime.datetime],
        Field(description="Date of creation of the resource."),
    ] = datetime.datetime.now()
    creator: Annotated[
        Optional[Any],
        Field(description="An entity responsible for making the resource."),
    ] = os.environ.get("USER")

    # Object properties
    continuant_part_of: Optional[
        Annotated[
            List[Union[IndependentContinuant, URIRef, str]],
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
    has_continuant_part: Optional[
        Annotated[
            List[Union[Continuant, URIRef, str]],
            Field(description="b has continuant part c =Def c continuant part of b"),
        ]
    ] = None


class TemporalRegion(Occurrent, RDFEntity):
    """
    temporal region
    """

    _class_uri: ClassVar[str] = "http://purl.obolibrary.org/obo/BFO_0000008"
    _name: ClassVar[str] = "temporal region"
    _property_uris: ClassVar[dict] = {
        "created": "http://purl.org/dc/terms/created",
        "creator": "http://purl.org/dc/terms/creator",
        "exists_at": "http://purl.obolibrary.org/obo/BFO_0000108",
        "has_first_instant": "http://purl.obolibrary.org/obo/BFO_0000222",
        "has_last_instant": "http://purl.obolibrary.org/obo/BFO_0000224",
        "has_occurrent_part": "http://purl.obolibrary.org/obo/BFO_0000117",
        "has_temporal_part": "http://purl.obolibrary.org/obo/BFO_0000121",
        "label": "http://www.w3.org/2000/01/rdf-schema#label",
        "occurrent_part_of": "http://purl.obolibrary.org/obo/BFO_0000132",
        "preceded_by": "http://purl.obolibrary.org/obo/BFO_0000062",
        "precedes": "http://purl.obolibrary.org/obo/BFO_0000063",
        "temporal_part_of": "http://purl.obolibrary.org/obo/BFO_0000139",
    }
    _object_properties: ClassVar[set[str]] = {
        "exists_at",
        "has_first_instant",
        "has_last_instant",
        "has_occurrent_part",
        "has_temporal_part",
        "occurrent_part_of",
        "preceded_by",
        "precedes",
        "temporal_part_of",
    }

    # Data properties
    label: Optional[Annotated[str, Field(description="Label of the resource.")]] = None
    created: Annotated[
        Optional[datetime.datetime],
        Field(description="Date of creation of the resource."),
    ] = datetime.datetime.now()
    creator: Annotated[
        Optional[Any],
        Field(description="An entity responsible for making the resource."),
    ] = os.environ.get("USER")

    # Object properties
    exists_at: Optional[
        Annotated[
            List[Union[TemporalRegion, URIRef, str]],
            Field(
                description="(Elucidation) exists at is a relation between a particular and some temporal region at which the particular exists"
            ),
        ]
    ] = None
    has_first_instant: Optional[
        Annotated[
            List[Union[TemporalInstant, URIRef, str]],
            Field(description="t has first instant t' =Def t' first instant of t"),
        ]
    ] = None
    has_last_instant: Optional[
        Annotated[
            List[Union[TemporalInstant, URIRef, str]],
            Field(description="t has last instant t' =Def t' last instant of t"),
        ]
    ] = None
    has_occurrent_part: Optional[
        Annotated[
            List[Union[Occurrent, URIRef, str]],
            Field(description="b has occurrent part c =Def c occurrent part of b"),
        ]
    ] = None
    has_temporal_part: Optional[
        Annotated[
            List[Union[Occurrent, URIRef, str]],
            Field(description="b has temporal part c =Def c temporal part of b"),
        ]
    ] = None
    occurrent_part_of: Optional[
        Annotated[
            List[Union[TemporalRegion, URIRef, str]],
            Field(
                description="(Elucidation) occurrent part of is a relation between occurrents b and c when b is part of c"
            ),
        ]
    ] = None
    preceded_by: Optional[
        Annotated[
            List[Union[Occurrent, URIRef, str]],
            Field(description="b preceded by c =Def b precedes c"),
        ]
    ] = None
    precedes: Optional[
        Annotated[
            List[Union[Occurrent, URIRef, str]],
            Field(
                description="(Elucidation) precedes is a relation between occurrents o, o' such that if t is the temporal extent of o & t' is the temporal extent of o' then either the last instant of o is before the first instant of o' or the last instant of o is the first instant of o' & neither o nor o' are temporal instants"
            ),
        ]
    ] = None
    temporal_part_of: Optional[
        Annotated[
            List[Union[TemporalRegion, URIRef, str]],
            Field(
                description="b temporal part of c =Def b occurrent part of c & (b and c are temporal regions) or (b and c are spatiotemporal regions & b temporally projects onto an occurrent part of the temporal region that c temporally projects onto) or (b and c are processes or process boundaries & b occupies a temporal region that is an occurrent part of the temporal region that c occupies)"
            ),
        ]
    ] = None


class SpatiotemporalRegion(Occurrent, RDFEntity):
    """
    spatiotemporal region
    """

    _class_uri: ClassVar[str] = "http://purl.obolibrary.org/obo/BFO_0000011"
    _name: ClassVar[str] = "spatiotemporal region"
    _property_uris: ClassVar[dict] = {
        "created": "http://purl.org/dc/terms/created",
        "creator": "http://purl.org/dc/terms/creator",
        "exists_at": "http://purl.obolibrary.org/obo/BFO_0000108",
        "has_occurrent_part": "http://purl.obolibrary.org/obo/BFO_0000117",
        "has_temporal_part": "http://purl.obolibrary.org/obo/BFO_0000121",
        "label": "http://www.w3.org/2000/01/rdf-schema#label",
        "occurrent_part_of": "http://purl.obolibrary.org/obo/BFO_0000132",
        "preceded_by": "http://purl.obolibrary.org/obo/BFO_0000062",
        "precedes": "http://purl.obolibrary.org/obo/BFO_0000063",
        "spatially_projects_onto": "http://purl.obolibrary.org/obo/BFO_0000216",
        "temporal_part_of": "http://purl.obolibrary.org/obo/BFO_0000139",
        "temporally_projects_onto": "http://purl.obolibrary.org/obo/BFO_0000153",
    }
    _object_properties: ClassVar[set[str]] = {
        "exists_at",
        "has_occurrent_part",
        "has_temporal_part",
        "occurrent_part_of",
        "preceded_by",
        "precedes",
        "spatially_projects_onto",
        "temporal_part_of",
        "temporally_projects_onto",
    }

    # Data properties
    label: Optional[Annotated[str, Field(description="Label of the resource.")]] = None
    created: Annotated[
        Optional[datetime.datetime],
        Field(description="Date of creation of the resource."),
    ] = datetime.datetime.now()
    creator: Annotated[
        Optional[Any],
        Field(description="An entity responsible for making the resource."),
    ] = os.environ.get("USER")

    # Object properties
    exists_at: Optional[
        Annotated[
            List[Union[TemporalRegion, URIRef, str]],
            Field(
                description="(Elucidation) exists at is a relation between a particular and some temporal region at which the particular exists"
            ),
        ]
    ] = None
    has_occurrent_part: Optional[
        Annotated[
            List[Union[Occurrent, URIRef, str]],
            Field(description="b has occurrent part c =Def c occurrent part of b"),
        ]
    ] = None
    has_temporal_part: Optional[
        Annotated[
            List[Union[Occurrent, URIRef, str]],
            Field(description="b has temporal part c =Def c temporal part of b"),
        ]
    ] = None
    occurrent_part_of: Optional[
        Annotated[
            List[Union[SpatiotemporalRegion, URIRef, str]],
            Field(
                description="(Elucidation) occurrent part of is a relation between occurrents b and c when b is part of c"
            ),
        ]
    ] = None
    preceded_by: Optional[
        Annotated[
            List[Union[Occurrent, URIRef, str]],
            Field(description="b preceded by c =Def b precedes c"),
        ]
    ] = None
    precedes: Optional[
        Annotated[
            List[Union[Occurrent, URIRef, str]],
            Field(
                description="(Elucidation) precedes is a relation between occurrents o, o' such that if t is the temporal extent of o & t' is the temporal extent of o' then either the last instant of o is before the first instant of o' or the last instant of o is the first instant of o' & neither o nor o' are temporal instants"
            ),
        ]
    ] = None
    spatially_projects_onto: Optional[
        Annotated[
            List[Union[SpatialRegion, URIRef, str]],
            Field(
                description="(Elucidation) spatially projects onto is a relation between some spatiotemporal region b and spatial region c such that at some time t, c is the spatial extent of b at t"
            ),
        ]
    ] = None
    temporal_part_of: Optional[
        Annotated[
            List[Union[SpatiotemporalRegion, URIRef, str]],
            Field(
                description="b temporal part of c =Def b occurrent part of c & (b and c are temporal regions) or (b and c are spatiotemporal regions & b temporally projects onto an occurrent part of the temporal region that c temporally projects onto) or (b and c are processes or process boundaries & b occupies a temporal region that is an occurrent part of the temporal region that c occupies)"
            ),
        ]
    ] = None
    temporally_projects_onto: Optional[
        Annotated[
            List[Union[TemporalRegion, URIRef, str]],
            Field(
                description="(Elucidation) temporally projects onto is a relation between a spatiotemporal region s and some temporal region which is the temporal extent of s"
            ),
        ]
    ] = None


class Process(Occurrent, RDFEntity):
    """
    process
    """

    _class_uri: ClassVar[str] = "http://purl.obolibrary.org/obo/BFO_0000015"
    _name: ClassVar[str] = "process"
    _property_uris: ClassVar[dict] = {
        "created": "http://purl.org/dc/terms/created",
        "creator": "http://purl.org/dc/terms/creator",
        "exists_at": "http://purl.obolibrary.org/obo/BFO_0000108",
        "has_occurrent_part": "http://purl.obolibrary.org/obo/BFO_0000117",
        "has_participant": "http://purl.obolibrary.org/obo/BFO_0000057",
        "has_temporal_part": "http://purl.obolibrary.org/obo/BFO_0000121",
        "label": "http://www.w3.org/2000/01/rdf-schema#label",
        "occurrent_part_of": "http://purl.obolibrary.org/obo/BFO_0000132",
        "preceded_by": "http://purl.obolibrary.org/obo/BFO_0000062",
        "precedes": "http://purl.obolibrary.org/obo/BFO_0000063",
        "realizes": "http://purl.obolibrary.org/obo/BFO_0000055",
        "temporal_part_of": "http://purl.obolibrary.org/obo/BFO_0000139",
    }
    _object_properties: ClassVar[set[str]] = {
        "exists_at",
        "has_occurrent_part",
        "has_participant",
        "has_temporal_part",
        "occurrent_part_of",
        "preceded_by",
        "precedes",
        "realizes",
        "temporal_part_of",
    }

    # Data properties
    label: Optional[Annotated[str, Field(description="Label of the resource.")]] = None
    created: Annotated[
        Optional[datetime.datetime],
        Field(description="Date of creation of the resource."),
    ] = datetime.datetime.now()
    creator: Annotated[
        Optional[Any],
        Field(description="An entity responsible for making the resource."),
    ] = os.environ.get("USER")

    # Object properties
    exists_at: Optional[
        Annotated[
            List[Union[TemporalRegion, URIRef, str]],
            Field(
                description="(Elucidation) exists at is a relation between a particular and some temporal region at which the particular exists"
            ),
        ]
    ] = None
    has_occurrent_part: Optional[
        Annotated[
            List[Union[Process, ProcessBoundary, URIRef, str]],
            Field(description="b has occurrent part c =Def c occurrent part of b"),
        ]
    ] = None
    has_participant: Optional[
        Annotated[
            Union[URIRef, str],
            Field(description="p has participant c =Def c participates in p"),
        ]
    ] = None
    has_temporal_part: Optional[
        Annotated[
            List[Union[Occurrent, URIRef, str]],
            Field(description="b has temporal part c =Def c temporal part of b"),
        ]
    ] = None
    occurrent_part_of: Optional[
        Annotated[
            List[Union[Process, URIRef, str]],
            Field(
                description="(Elucidation) occurrent part of is a relation between occurrents b and c when b is part of c"
            ),
        ]
    ] = None
    preceded_by: Optional[
        Annotated[
            List[Union[Occurrent, URIRef, str]],
            Field(description="b preceded by c =Def b precedes c"),
        ]
    ] = None
    precedes: Optional[
        Annotated[
            List[Union[Occurrent, URIRef, str]],
            Field(
                description="(Elucidation) precedes is a relation between occurrents o, o' such that if t is the temporal extent of o & t' is the temporal extent of o' then either the last instant of o is before the first instant of o' or the last instant of o is the first instant of o' & neither o nor o' are temporal instants"
            ),
        ]
    ] = None
    realizes: Optional[
        Annotated[
            List[Union[RealizableEntity, URIRef, str]],
            Field(
                description="(Elucidation) realizes is a relation between a process b and realizable entity c such that c inheres in some d & for all t, if b has participant d then c exists & the type instantiated by b is correlated with the type instantiated by c"
            ),
        ]
    ] = None
    temporal_part_of: Optional[
        Annotated[
            List[Union[Process, URIRef, str]],
            Field(
                description="b temporal part of c =Def b occurrent part of c & (b and c are temporal regions) or (b and c are spatiotemporal regions & b temporally projects onto an occurrent part of the temporal region that c temporally projects onto) or (b and c are processes or process boundaries & b occupies a temporal region that is an occurrent part of the temporal region that c occupies)"
            ),
        ]
    ] = None


class SpecificallyDependentContinuant(Continuant, RDFEntity):
    """
    specifically dependent continuant
    """

    _class_uri: ClassVar[str] = "http://purl.obolibrary.org/obo/BFO_0000020"
    _name: ClassVar[str] = "specifically dependent continuant"
    _property_uris: ClassVar[dict] = {
        "continuant_part_of": "http://purl.obolibrary.org/obo/BFO_0000176",
        "created": "http://purl.org/dc/terms/created",
        "creator": "http://purl.org/dc/terms/creator",
        "exists_at": "http://purl.obolibrary.org/obo/BFO_0000108",
        "has_continuant_part": "http://purl.obolibrary.org/obo/BFO_0000178",
        "inheres_in": "http://purl.obolibrary.org/obo/BFO_0000197",
        "label": "http://www.w3.org/2000/01/rdf-schema#label",
        "specifically_depends_on": "http://purl.obolibrary.org/obo/BFO_0000195",
    }
    _object_properties: ClassVar[set[str]] = {
        "continuant_part_of",
        "exists_at",
        "has_continuant_part",
        "inheres_in",
        "specifically_depends_on",
    }

    # Data properties
    label: Optional[Annotated[str, Field(description="Label of the resource.")]] = None
    created: Annotated[
        Optional[datetime.datetime],
        Field(description="Date of creation of the resource."),
    ] = datetime.datetime.now()
    creator: Annotated[
        Optional[Any],
        Field(description="An entity responsible for making the resource."),
    ] = os.environ.get("USER")

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
    has_continuant_part: Optional[
        Annotated[
            List[Union[Continuant, URIRef, str]],
            Field(description="b has continuant part c =Def c continuant part of b"),
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


class GenericallyDependentContinuant(Continuant, RDFEntity):
    """
    generically dependent continuant
    """

    _class_uri: ClassVar[str] = "http://purl.obolibrary.org/obo/BFO_0000031"
    _name: ClassVar[str] = "generically dependent continuant"
    _property_uris: ClassVar[dict] = {
        "continuant_part_of": "http://purl.obolibrary.org/obo/BFO_0000176",
        "created": "http://purl.org/dc/terms/created",
        "creator": "http://purl.org/dc/terms/creator",
        "exists_at": "http://purl.obolibrary.org/obo/BFO_0000108",
        "generically_depends_on": "http://purl.obolibrary.org/obo/BFO_0000084",
        "has_continuant_part": "http://purl.obolibrary.org/obo/BFO_0000178",
        "is_concretized_by": "http://purl.obolibrary.org/obo/BFO_0000058",
        "label": "http://www.w3.org/2000/01/rdf-schema#label",
    }
    _object_properties: ClassVar[set[str]] = {
        "continuant_part_of",
        "exists_at",
        "generically_depends_on",
        "has_continuant_part",
        "is_concretized_by",
    }

    # Data properties
    label: Optional[Annotated[str, Field(description="Label of the resource.")]] = None
    created: Annotated[
        Optional[datetime.datetime],
        Field(description="Date of creation of the resource."),
    ] = datetime.datetime.now()
    creator: Annotated[
        Optional[Any],
        Field(description="An entity responsible for making the resource."),
    ] = os.environ.get("USER")

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


class ProcessBoundary(Occurrent, RDFEntity):
    """
    process boundary
    """

    _class_uri: ClassVar[str] = "http://purl.obolibrary.org/obo/BFO_0000035"
    _name: ClassVar[str] = "process boundary"
    _property_uris: ClassVar[dict] = {
        "created": "http://purl.org/dc/terms/created",
        "creator": "http://purl.org/dc/terms/creator",
        "exists_at": "http://purl.obolibrary.org/obo/BFO_0000108",
        "has_occurrent_part": "http://purl.obolibrary.org/obo/BFO_0000117",
        "has_temporal_part": "http://purl.obolibrary.org/obo/BFO_0000121",
        "label": "http://www.w3.org/2000/01/rdf-schema#label",
        "occurrent_part_of": "http://purl.obolibrary.org/obo/BFO_0000132",
        "preceded_by": "http://purl.obolibrary.org/obo/BFO_0000062",
        "precedes": "http://purl.obolibrary.org/obo/BFO_0000063",
        "temporal_part_of": "http://purl.obolibrary.org/obo/BFO_0000139",
    }
    _object_properties: ClassVar[set[str]] = {
        "exists_at",
        "has_occurrent_part",
        "has_temporal_part",
        "occurrent_part_of",
        "preceded_by",
        "precedes",
        "temporal_part_of",
    }

    # Data properties
    label: Optional[Annotated[str, Field(description="Label of the resource.")]] = None
    created: Annotated[
        Optional[datetime.datetime],
        Field(description="Date of creation of the resource."),
    ] = datetime.datetime.now()
    creator: Annotated[
        Optional[Any],
        Field(description="An entity responsible for making the resource."),
    ] = os.environ.get("USER")

    # Object properties
    exists_at: Optional[
        Annotated[
            List[Union[TemporalRegion, URIRef, str]],
            Field(
                description="(Elucidation) exists at is a relation between a particular and some temporal region at which the particular exists"
            ),
        ]
    ] = None
    has_occurrent_part: Optional[
        Annotated[
            List[Union[ProcessBoundary, URIRef, str]],
            Field(description="b has occurrent part c =Def c occurrent part of b"),
        ]
    ] = None
    has_temporal_part: Optional[
        Annotated[
            List[Union[ProcessBoundary, URIRef, str]],
            Field(description="b has temporal part c =Def c temporal part of b"),
        ]
    ] = None
    occurrent_part_of: Optional[
        Annotated[
            List[Union[Process, ProcessBoundary, URIRef, str]],
            Field(
                description="(Elucidation) occurrent part of is a relation between occurrents b and c when b is part of c"
            ),
        ]
    ] = None
    preceded_by: Optional[
        Annotated[
            List[Union[Occurrent, URIRef, str]],
            Field(description="b preceded by c =Def b precedes c"),
        ]
    ] = None
    precedes: Optional[
        Annotated[
            List[Union[Occurrent, URIRef, str]],
            Field(
                description="(Elucidation) precedes is a relation between occurrents o, o' such that if t is the temporal extent of o & t' is the temporal extent of o' then either the last instant of o is before the first instant of o' or the last instant of o is the first instant of o' & neither o nor o' are temporal instants"
            ),
        ]
    ] = None
    temporal_part_of: Optional[
        Annotated[
            List[Union[Process, ProcessBoundary, URIRef, str]],
            Field(
                description="b temporal part of c =Def b occurrent part of c & (b and c are temporal regions) or (b and c are spatiotemporal regions & b temporally projects onto an occurrent part of the temporal region that c temporally projects onto) or (b and c are processes or process boundaries & b occupies a temporal region that is an occurrent part of the temporal region that c occupies)"
            ),
        ]
    ] = None


class RealizableEntity(SpecificallyDependentContinuant, RDFEntity):
    """
    realizable entity
    """

    _class_uri: ClassVar[str] = "http://purl.obolibrary.org/obo/BFO_0000017"
    _name: ClassVar[str] = "realizable entity"
    _property_uris: ClassVar[dict] = {
        "continuant_part_of": "http://purl.obolibrary.org/obo/BFO_0000176",
        "created": "http://purl.org/dc/terms/created",
        "creator": "http://purl.org/dc/terms/creator",
        "exists_at": "http://purl.obolibrary.org/obo/BFO_0000108",
        "has_continuant_part": "http://purl.obolibrary.org/obo/BFO_0000178",
        "has_realization": "http://purl.obolibrary.org/obo/BFO_0000054",
        "inheres_in": "http://purl.obolibrary.org/obo/BFO_0000197",
        "label": "http://www.w3.org/2000/01/rdf-schema#label",
        "specifically_depends_on": "http://purl.obolibrary.org/obo/BFO_0000195",
    }
    _object_properties: ClassVar[set[str]] = {
        "continuant_part_of",
        "exists_at",
        "has_continuant_part",
        "has_realization",
        "inheres_in",
        "specifically_depends_on",
    }

    # Data properties
    label: Optional[Annotated[str, Field(description="Label of the resource.")]] = None
    created: Annotated[
        Optional[datetime.datetime],
        Field(description="Date of creation of the resource."),
    ] = datetime.datetime.now()
    creator: Annotated[
        Optional[Any],
        Field(description="An entity responsible for making the resource."),
    ] = os.environ.get("USER")

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
    has_continuant_part: Optional[
        Annotated[
            List[Union[Continuant, URIRef, str]],
            Field(description="b has continuant part c =Def c continuant part of b"),
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


class Quality(SpecificallyDependentContinuant, RDFEntity):
    """
    quality
    """

    _class_uri: ClassVar[str] = "http://purl.obolibrary.org/obo/BFO_0000019"
    _name: ClassVar[str] = "quality"
    _property_uris: ClassVar[dict] = {
        "continuant_part_of": "http://purl.obolibrary.org/obo/BFO_0000176",
        "created": "http://purl.org/dc/terms/created",
        "creator": "http://purl.org/dc/terms/creator",
        "exists_at": "http://purl.obolibrary.org/obo/BFO_0000108",
        "has_continuant_part": "http://purl.obolibrary.org/obo/BFO_0000178",
        "inheres_in": "http://purl.obolibrary.org/obo/BFO_0000197",
        "label": "http://www.w3.org/2000/01/rdf-schema#label",
        "specifically_depends_on": "http://purl.obolibrary.org/obo/BFO_0000195",
    }
    _object_properties: ClassVar[set[str]] = {
        "continuant_part_of",
        "exists_at",
        "has_continuant_part",
        "inheres_in",
        "specifically_depends_on",
    }

    # Data properties
    label: Optional[Annotated[str, Field(description="Label of the resource.")]] = None
    created: Annotated[
        Optional[datetime.datetime],
        Field(description="Date of creation of the resource."),
    ] = datetime.datetime.now()
    creator: Annotated[
        Optional[Any],
        Field(description="An entity responsible for making the resource."),
    ] = os.environ.get("USER")

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
    has_continuant_part: Optional[
        Annotated[
            List[Union[Continuant, URIRef, str]],
            Field(description="b has continuant part c =Def c continuant part of b"),
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


class OnedimensionalTemporalRegion(TemporalRegion, RDFEntity):
    """
    one-dimensional temporal region
    """

    _class_uri: ClassVar[str] = "http://purl.obolibrary.org/obo/BFO_0000038"
    _name: ClassVar[str] = "one-dimensional temporal region"
    _property_uris: ClassVar[dict] = {
        "created": "http://purl.org/dc/terms/created",
        "creator": "http://purl.org/dc/terms/creator",
        "exists_at": "http://purl.obolibrary.org/obo/BFO_0000108",
        "has_first_instant": "http://purl.obolibrary.org/obo/BFO_0000222",
        "has_last_instant": "http://purl.obolibrary.org/obo/BFO_0000224",
        "has_occurrent_part": "http://purl.obolibrary.org/obo/BFO_0000117",
        "has_temporal_part": "http://purl.obolibrary.org/obo/BFO_0000121",
        "label": "http://www.w3.org/2000/01/rdf-schema#label",
        "occurrent_part_of": "http://purl.obolibrary.org/obo/BFO_0000132",
        "preceded_by": "http://purl.obolibrary.org/obo/BFO_0000062",
        "precedes": "http://purl.obolibrary.org/obo/BFO_0000063",
        "temporal_part_of": "http://purl.obolibrary.org/obo/BFO_0000139",
    }
    _object_properties: ClassVar[set[str]] = {
        "exists_at",
        "has_first_instant",
        "has_last_instant",
        "has_occurrent_part",
        "has_temporal_part",
        "occurrent_part_of",
        "preceded_by",
        "precedes",
        "temporal_part_of",
    }

    # Data properties
    label: Optional[Annotated[str, Field(description="Label of the resource.")]] = None
    created: Annotated[
        Optional[datetime.datetime],
        Field(description="Date of creation of the resource."),
    ] = datetime.datetime.now()
    creator: Annotated[
        Optional[Any],
        Field(description="An entity responsible for making the resource."),
    ] = os.environ.get("USER")

    # Object properties
    exists_at: Optional[
        Annotated[
            List[Union[TemporalRegion, URIRef, str]],
            Field(
                description="(Elucidation) exists at is a relation between a particular and some temporal region at which the particular exists"
            ),
        ]
    ] = None
    has_first_instant: Optional[
        Annotated[
            List[Union[TemporalInstant, URIRef, str]],
            Field(description="t has first instant t' =Def t' first instant of t"),
        ]
    ] = None
    has_last_instant: Optional[
        Annotated[
            List[Union[TemporalInstant, URIRef, str]],
            Field(description="t has last instant t' =Def t' last instant of t"),
        ]
    ] = None
    has_occurrent_part: Optional[
        Annotated[
            List[Union[Occurrent, URIRef, str]],
            Field(description="b has occurrent part c =Def c occurrent part of b"),
        ]
    ] = None
    has_temporal_part: Optional[
        Annotated[
            List[
                Union[
                    OnedimensionalTemporalRegion,
                    URIRef,
                    ZerodimensionalTemporalRegion,
                    str,
                ]
            ],
            Field(description="b has temporal part c =Def c temporal part of b"),
        ]
    ] = None
    occurrent_part_of: Optional[
        Annotated[
            List[Union[TemporalRegion, URIRef, str]],
            Field(
                description="(Elucidation) occurrent part of is a relation between occurrents b and c when b is part of c"
            ),
        ]
    ] = None
    preceded_by: Optional[
        Annotated[
            List[Union[Occurrent, URIRef, str]],
            Field(description="b preceded by c =Def b precedes c"),
        ]
    ] = None
    precedes: Optional[
        Annotated[
            List[Union[Occurrent, URIRef, str]],
            Field(
                description="(Elucidation) precedes is a relation between occurrents o, o' such that if t is the temporal extent of o & t' is the temporal extent of o' then either the last instant of o is before the first instant of o' or the last instant of o is the first instant of o' & neither o nor o' are temporal instants"
            ),
        ]
    ] = None
    temporal_part_of: Optional[
        Annotated[
            List[Union[OnedimensionalTemporalRegion, URIRef, str]],
            Field(
                description="b temporal part of c =Def b occurrent part of c & (b and c are temporal regions) or (b and c are spatiotemporal regions & b temporally projects onto an occurrent part of the temporal region that c temporally projects onto) or (b and c are processes or process boundaries & b occupies a temporal region that is an occurrent part of the temporal region that c occupies)"
            ),
        ]
    ] = None


class MaterialEntity(IndependentContinuant, RDFEntity):
    """
    material entity
    """

    _class_uri: ClassVar[str] = "http://purl.obolibrary.org/obo/BFO_0000040"
    _name: ClassVar[str] = "material entity"
    _property_uris: ClassVar[dict] = {
        "continuant_part_of": "http://purl.obolibrary.org/obo/BFO_0000176",
        "created": "http://purl.org/dc/terms/created",
        "creator": "http://purl.org/dc/terms/creator",
        "exists_at": "http://purl.obolibrary.org/obo/BFO_0000108",
        "has_continuant_part": "http://purl.obolibrary.org/obo/BFO_0000178",
        "has_history": "http://purl.obolibrary.org/obo/BFO_0000185",
        "has_member_part": "http://purl.obolibrary.org/obo/BFO_0000115",
        "label": "http://www.w3.org/2000/01/rdf-schema#label",
        "material_basis_of": "http://purl.obolibrary.org/obo/BFO_0000127",
        "member_part_of": "http://purl.obolibrary.org/obo/BFO_0000129",
    }
    _object_properties: ClassVar[set[str]] = {
        "continuant_part_of",
        "exists_at",
        "has_continuant_part",
        "has_history",
        "has_member_part",
        "material_basis_of",
        "member_part_of",
    }

    # Data properties
    label: Optional[Annotated[str, Field(description="Label of the resource.")]] = None
    created: Annotated[
        Optional[datetime.datetime],
        Field(description="Date of creation of the resource."),
    ] = datetime.datetime.now()
    creator: Annotated[
        Optional[Any],
        Field(description="An entity responsible for making the resource."),
    ] = os.environ.get("USER")

    # Object properties
    continuant_part_of: Optional[
        Annotated[
            List[Union[MaterialEntity, URIRef, str]],
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
    has_continuant_part: Optional[
        Annotated[
            List[Union[ContinuantFiatBoundary, MaterialEntity, Site, URIRef, str]],
            Field(description="b has continuant part c =Def c continuant part of b"),
        ]
    ] = None
    has_history: Optional[
        Annotated[
            List[Union[History, URIRef, str]],
            Field(description="b has history c =Def c history of b"),
        ]
    ] = None
    has_member_part: Optional[
        Annotated[
            List[Union[MaterialEntity, URIRef, str]],
            Field(description="b has member part c =Def c member part of b"),
        ]
    ] = None
    material_basis_of: Optional[
        Annotated[
            List[Union[Disposition, URIRef, str]],
            Field(description="b material basis of c =Def c has material basis b"),
        ]
    ] = None
    member_part_of: Optional[
        Annotated[
            List[Union[MaterialEntity, URIRef, str]],
            Field(
                description="b member part of c =Def b is an object & c is a material entity & there is some time t such that b continuant part of c at t & there is a mutually exhaustive and pairwise disjoint partition of c into objects x1, ..., xn (for some n ≠ 1) with b = xi (for some 1 <= i <= n)"
            ),
        ]
    ] = None


class ImmaterialEntity(IndependentContinuant, RDFEntity):
    """
    immaterial entity
    """

    _class_uri: ClassVar[str] = "http://purl.obolibrary.org/obo/BFO_0000141"
    _name: ClassVar[str] = "immaterial entity"
    _property_uris: ClassVar[dict] = {
        "continuant_part_of": "http://purl.obolibrary.org/obo/BFO_0000176",
        "created": "http://purl.org/dc/terms/created",
        "creator": "http://purl.org/dc/terms/creator",
        "exists_at": "http://purl.obolibrary.org/obo/BFO_0000108",
        "has_continuant_part": "http://purl.obolibrary.org/obo/BFO_0000178",
        "label": "http://www.w3.org/2000/01/rdf-schema#label",
    }
    _object_properties: ClassVar[set[str]] = {
        "continuant_part_of",
        "exists_at",
        "has_continuant_part",
    }

    # Data properties
    label: Optional[Annotated[str, Field(description="Label of the resource.")]] = None
    created: Annotated[
        Optional[datetime.datetime],
        Field(description="Date of creation of the resource."),
    ] = datetime.datetime.now()
    creator: Annotated[
        Optional[Any],
        Field(description="An entity responsible for making the resource."),
    ] = os.environ.get("USER")

    # Object properties
    continuant_part_of: Optional[
        Annotated[
            List[Union[IndependentContinuant, URIRef, str]],
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
    has_continuant_part: Optional[
        Annotated[
            List[Union[Continuant, URIRef, str]],
            Field(description="b has continuant part c =Def c continuant part of b"),
        ]
    ] = None


class ZerodimensionalTemporalRegion(TemporalRegion, RDFEntity):
    """
    zero-dimensional temporal region
    """

    _class_uri: ClassVar[str] = "http://purl.obolibrary.org/obo/BFO_0000148"
    _name: ClassVar[str] = "zero-dimensional temporal region"
    _property_uris: ClassVar[dict] = {
        "created": "http://purl.org/dc/terms/created",
        "creator": "http://purl.org/dc/terms/creator",
        "exists_at": "http://purl.obolibrary.org/obo/BFO_0000108",
        "has_first_instant": "http://purl.obolibrary.org/obo/BFO_0000222",
        "has_last_instant": "http://purl.obolibrary.org/obo/BFO_0000224",
        "has_occurrent_part": "http://purl.obolibrary.org/obo/BFO_0000117",
        "has_temporal_part": "http://purl.obolibrary.org/obo/BFO_0000121",
        "label": "http://www.w3.org/2000/01/rdf-schema#label",
        "occurrent_part_of": "http://purl.obolibrary.org/obo/BFO_0000132",
        "preceded_by": "http://purl.obolibrary.org/obo/BFO_0000062",
        "precedes": "http://purl.obolibrary.org/obo/BFO_0000063",
        "temporal_part_of": "http://purl.obolibrary.org/obo/BFO_0000139",
    }
    _object_properties: ClassVar[set[str]] = {
        "exists_at",
        "has_first_instant",
        "has_last_instant",
        "has_occurrent_part",
        "has_temporal_part",
        "occurrent_part_of",
        "preceded_by",
        "precedes",
        "temporal_part_of",
    }

    # Data properties
    label: Optional[Annotated[str, Field(description="Label of the resource.")]] = None
    created: Annotated[
        Optional[datetime.datetime],
        Field(description="Date of creation of the resource."),
    ] = datetime.datetime.now()
    creator: Annotated[
        Optional[Any],
        Field(description="An entity responsible for making the resource."),
    ] = os.environ.get("USER")

    # Object properties
    exists_at: Optional[
        Annotated[
            List[Union[TemporalRegion, URIRef, str]],
            Field(
                description="(Elucidation) exists at is a relation between a particular and some temporal region at which the particular exists"
            ),
        ]
    ] = None
    has_first_instant: Optional[
        Annotated[
            List[Union[TemporalInstant, URIRef, str]],
            Field(description="t has first instant t' =Def t' first instant of t"),
        ]
    ] = None
    has_last_instant: Optional[
        Annotated[
            List[Union[TemporalInstant, URIRef, str]],
            Field(description="t has last instant t' =Def t' last instant of t"),
        ]
    ] = None
    has_occurrent_part: Optional[
        Annotated[
            List[Union[Occurrent, URIRef, str]],
            Field(description="b has occurrent part c =Def c occurrent part of b"),
        ]
    ] = None
    has_temporal_part: Optional[
        Annotated[
            List[Union[URIRef, ZerodimensionalTemporalRegion, str]],
            Field(description="b has temporal part c =Def c temporal part of b"),
        ]
    ] = None
    occurrent_part_of: Optional[
        Annotated[
            List[Union[TemporalRegion, URIRef, str]],
            Field(
                description="(Elucidation) occurrent part of is a relation between occurrents b and c when b is part of c"
            ),
        ]
    ] = None
    preceded_by: Optional[
        Annotated[
            List[Union[Occurrent, URIRef, str]],
            Field(description="b preceded by c =Def b precedes c"),
        ]
    ] = None
    precedes: Optional[
        Annotated[
            List[Union[Occurrent, URIRef, str]],
            Field(
                description="(Elucidation) precedes is a relation between occurrents o, o' such that if t is the temporal extent of o & t' is the temporal extent of o' then either the last instant of o is before the first instant of o' or the last instant of o is the first instant of o' & neither o nor o' are temporal instants"
            ),
        ]
    ] = None
    temporal_part_of: Optional[
        Annotated[
            List[Union[TemporalRegion, URIRef, str]],
            Field(
                description="b temporal part of c =Def b occurrent part of c & (b and c are temporal regions) or (b and c are spatiotemporal regions & b temporally projects onto an occurrent part of the temporal region that c temporally projects onto) or (b and c are processes or process boundaries & b occupies a temporal region that is an occurrent part of the temporal region that c occupies)"
            ),
        ]
    ] = None


class History(Process, RDFEntity):
    """
    history
    """

    _class_uri: ClassVar[str] = "http://purl.obolibrary.org/obo/BFO_0000182"
    _name: ClassVar[str] = "history"
    _property_uris: ClassVar[dict] = {
        "created": "http://purl.org/dc/terms/created",
        "creator": "http://purl.org/dc/terms/creator",
        "exists_at": "http://purl.obolibrary.org/obo/BFO_0000108",
        "has_occurrent_part": "http://purl.obolibrary.org/obo/BFO_0000117",
        "has_participant": "http://purl.obolibrary.org/obo/BFO_0000057",
        "has_temporal_part": "http://purl.obolibrary.org/obo/BFO_0000121",
        "history_of": "http://purl.obolibrary.org/obo/BFO_0000184",
        "label": "http://www.w3.org/2000/01/rdf-schema#label",
        "occurrent_part_of": "http://purl.obolibrary.org/obo/BFO_0000132",
        "preceded_by": "http://purl.obolibrary.org/obo/BFO_0000062",
        "precedes": "http://purl.obolibrary.org/obo/BFO_0000063",
        "realizes": "http://purl.obolibrary.org/obo/BFO_0000055",
        "temporal_part_of": "http://purl.obolibrary.org/obo/BFO_0000139",
    }
    _object_properties: ClassVar[set[str]] = {
        "exists_at",
        "has_occurrent_part",
        "has_participant",
        "has_temporal_part",
        "history_of",
        "occurrent_part_of",
        "preceded_by",
        "precedes",
        "realizes",
        "temporal_part_of",
    }

    # Data properties
    label: Optional[Annotated[str, Field(description="Label of the resource.")]] = None
    created: Annotated[
        Optional[datetime.datetime],
        Field(description="Date of creation of the resource."),
    ] = datetime.datetime.now()
    creator: Annotated[
        Optional[Any],
        Field(description="An entity responsible for making the resource."),
    ] = os.environ.get("USER")

    # Object properties
    exists_at: Optional[
        Annotated[
            List[Union[TemporalRegion, URIRef, str]],
            Field(
                description="(Elucidation) exists at is a relation between a particular and some temporal region at which the particular exists"
            ),
        ]
    ] = None
    has_occurrent_part: Optional[
        Annotated[
            List[Union[Process, ProcessBoundary, URIRef, str]],
            Field(description="b has occurrent part c =Def c occurrent part of b"),
        ]
    ] = None
    has_participant: Optional[
        Annotated[
            Union[URIRef, str],
            Field(description="p has participant c =Def c participates in p"),
        ]
    ] = None
    has_temporal_part: Optional[
        Annotated[
            List[Union[Occurrent, URIRef, str]],
            Field(description="b has temporal part c =Def c temporal part of b"),
        ]
    ] = None
    history_of: Optional[
        Annotated[
            List[Union[MaterialEntity, URIRef, str]],
            Field(
                description="(Elucidation) history of is a relation between history b and material entity c such that b is the unique history of c"
            ),
        ]
    ] = None
    occurrent_part_of: Optional[
        Annotated[
            List[Union[Process, URIRef, str]],
            Field(
                description="(Elucidation) occurrent part of is a relation between occurrents b and c when b is part of c"
            ),
        ]
    ] = None
    preceded_by: Optional[
        Annotated[
            List[Union[Occurrent, URIRef, str]],
            Field(description="b preceded by c =Def b precedes c"),
        ]
    ] = None
    precedes: Optional[
        Annotated[
            List[Union[Occurrent, URIRef, str]],
            Field(
                description="(Elucidation) precedes is a relation between occurrents o, o' such that if t is the temporal extent of o & t' is the temporal extent of o' then either the last instant of o is before the first instant of o' or the last instant of o is the first instant of o' & neither o nor o' are temporal instants"
            ),
        ]
    ] = None
    realizes: Optional[
        Annotated[
            List[Union[RealizableEntity, URIRef, str]],
            Field(
                description="(Elucidation) realizes is a relation between a process b and realizable entity c such that c inheres in some d & for all t, if b has participant d then c exists & the type instantiated by b is correlated with the type instantiated by c"
            ),
        ]
    ] = None
    temporal_part_of: Optional[
        Annotated[
            List[Union[Process, URIRef, str]],
            Field(
                description="b temporal part of c =Def b occurrent part of c & (b and c are temporal regions) or (b and c are spatiotemporal regions & b temporally projects onto an occurrent part of the temporal region that c temporally projects onto) or (b and c are processes or process boundaries & b occupies a temporal region that is an occurrent part of the temporal region that c occupies)"
            ),
        ]
    ] = None


class SpatialRegion(ImmaterialEntity, RDFEntity):
    """
    spatial region
    """

    _class_uri: ClassVar[str] = "http://purl.obolibrary.org/obo/BFO_0000006"
    _name: ClassVar[str] = "spatial region"
    _property_uris: ClassVar[dict] = {
        "continuant_part_of": "http://purl.obolibrary.org/obo/BFO_0000176",
        "created": "http://purl.org/dc/terms/created",
        "creator": "http://purl.org/dc/terms/creator",
        "exists_at": "http://purl.obolibrary.org/obo/BFO_0000108",
        "has_continuant_part": "http://purl.obolibrary.org/obo/BFO_0000178",
        "label": "http://www.w3.org/2000/01/rdf-schema#label",
    }
    _object_properties: ClassVar[set[str]] = {
        "continuant_part_of",
        "exists_at",
        "has_continuant_part",
    }

    # Data properties
    label: Optional[Annotated[str, Field(description="Label of the resource.")]] = None
    created: Annotated[
        Optional[datetime.datetime],
        Field(description="Date of creation of the resource."),
    ] = datetime.datetime.now()
    creator: Annotated[
        Optional[Any],
        Field(description="An entity responsible for making the resource."),
    ] = os.environ.get("USER")

    # Object properties
    continuant_part_of: Optional[
        Annotated[
            List[Union[SpatialRegion, URIRef, str]],
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
    has_continuant_part: Optional[
        Annotated[
            List[Union[Continuant, URIRef, str]],
            Field(description="b has continuant part c =Def c continuant part of b"),
        ]
    ] = None


class Disposition(RealizableEntity, RDFEntity):
    """
    disposition
    """

    _class_uri: ClassVar[str] = "http://purl.obolibrary.org/obo/BFO_0000016"
    _name: ClassVar[str] = "disposition"
    _property_uris: ClassVar[dict] = {
        "continuant_part_of": "http://purl.obolibrary.org/obo/BFO_0000176",
        "created": "http://purl.org/dc/terms/created",
        "creator": "http://purl.org/dc/terms/creator",
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
        "exists_at",
        "has_continuant_part",
        "has_material_basis",
        "has_realization",
        "inheres_in",
        "specifically_depends_on",
    }

    # Data properties
    label: Optional[Annotated[str, Field(description="Label of the resource.")]] = None
    created: Annotated[
        Optional[datetime.datetime],
        Field(description="Date of creation of the resource."),
    ] = datetime.datetime.now()
    creator: Annotated[
        Optional[Any],
        Field(description="An entity responsible for making the resource."),
    ] = os.environ.get("USER")

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


class Role(RealizableEntity, RDFEntity):
    """
    role
    """

    _class_uri: ClassVar[str] = "http://purl.obolibrary.org/obo/BFO_0000023"
    _name: ClassVar[str] = "role"
    _property_uris: ClassVar[dict] = {
        "continuant_part_of": "http://purl.obolibrary.org/obo/BFO_0000176",
        "created": "http://purl.org/dc/terms/created",
        "creator": "http://purl.org/dc/terms/creator",
        "exists_at": "http://purl.obolibrary.org/obo/BFO_0000108",
        "has_continuant_part": "http://purl.obolibrary.org/obo/BFO_0000178",
        "has_realization": "http://purl.obolibrary.org/obo/BFO_0000054",
        "inheres_in": "http://purl.obolibrary.org/obo/BFO_0000197",
        "label": "http://www.w3.org/2000/01/rdf-schema#label",
        "specifically_depends_on": "http://purl.obolibrary.org/obo/BFO_0000195",
    }
    _object_properties: ClassVar[set[str]] = {
        "continuant_part_of",
        "exists_at",
        "has_continuant_part",
        "has_realization",
        "inheres_in",
        "specifically_depends_on",
    }

    # Data properties
    label: Optional[Annotated[str, Field(description="Label of the resource.")]] = None
    created: Annotated[
        Optional[datetime.datetime],
        Field(description="Date of creation of the resource."),
    ] = datetime.datetime.now()
    creator: Annotated[
        Optional[Any],
        Field(description="An entity responsible for making the resource."),
    ] = os.environ.get("USER")

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
    has_continuant_part: Optional[
        Annotated[
            List[Union[Continuant, URIRef, str]],
            Field(description="b has continuant part c =Def c continuant part of b"),
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


class FiatObjectPart(MaterialEntity, RDFEntity):
    """
    fiat object part
    """

    _class_uri: ClassVar[str] = "http://purl.obolibrary.org/obo/BFO_0000024"
    _name: ClassVar[str] = "fiat object part"
    _property_uris: ClassVar[dict] = {
        "continuant_part_of": "http://purl.obolibrary.org/obo/BFO_0000176",
        "created": "http://purl.org/dc/terms/created",
        "creator": "http://purl.org/dc/terms/creator",
        "exists_at": "http://purl.obolibrary.org/obo/BFO_0000108",
        "has_continuant_part": "http://purl.obolibrary.org/obo/BFO_0000178",
        "has_history": "http://purl.obolibrary.org/obo/BFO_0000185",
        "has_member_part": "http://purl.obolibrary.org/obo/BFO_0000115",
        "label": "http://www.w3.org/2000/01/rdf-schema#label",
        "material_basis_of": "http://purl.obolibrary.org/obo/BFO_0000127",
        "member_part_of": "http://purl.obolibrary.org/obo/BFO_0000129",
    }
    _object_properties: ClassVar[set[str]] = {
        "continuant_part_of",
        "exists_at",
        "has_continuant_part",
        "has_history",
        "has_member_part",
        "material_basis_of",
        "member_part_of",
    }

    # Data properties
    label: Optional[Annotated[str, Field(description="Label of the resource.")]] = None
    created: Annotated[
        Optional[datetime.datetime],
        Field(description="Date of creation of the resource."),
    ] = datetime.datetime.now()
    creator: Annotated[
        Optional[Any],
        Field(description="An entity responsible for making the resource."),
    ] = os.environ.get("USER")

    # Object properties
    continuant_part_of: Optional[
        Annotated[
            List[Union[MaterialEntity, URIRef, str]],
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
    has_continuant_part: Optional[
        Annotated[
            List[Union[ContinuantFiatBoundary, MaterialEntity, Site, URIRef, str]],
            Field(description="b has continuant part c =Def c continuant part of b"),
        ]
    ] = None
    has_history: Optional[
        Annotated[
            List[Union[History, URIRef, str]],
            Field(description="b has history c =Def c history of b"),
        ]
    ] = None
    has_member_part: Optional[
        Annotated[
            List[Union[MaterialEntity, URIRef, str]],
            Field(description="b has member part c =Def c member part of b"),
        ]
    ] = None
    material_basis_of: Optional[
        Annotated[
            List[Union[Disposition, URIRef, str]],
            Field(description="b material basis of c =Def c has material basis b"),
        ]
    ] = None
    member_part_of: Optional[
        Annotated[
            List[Union[MaterialEntity, URIRef, str]],
            Field(
                description="b member part of c =Def b is an object & c is a material entity & there is some time t such that b continuant part of c at t & there is a mutually exhaustive and pairwise disjoint partition of c into objects x1, ..., xn (for some n ≠ 1) with b = xi (for some 1 <= i <= n)"
            ),
        ]
    ] = None


class ObjectAggregate(MaterialEntity, RDFEntity):
    """
    object aggregate
    """

    _class_uri: ClassVar[str] = "http://purl.obolibrary.org/obo/BFO_0000027"
    _name: ClassVar[str] = "object aggregate"
    _property_uris: ClassVar[dict] = {
        "continuant_part_of": "http://purl.obolibrary.org/obo/BFO_0000176",
        "created": "http://purl.org/dc/terms/created",
        "creator": "http://purl.org/dc/terms/creator",
        "exists_at": "http://purl.obolibrary.org/obo/BFO_0000108",
        "has_continuant_part": "http://purl.obolibrary.org/obo/BFO_0000178",
        "has_history": "http://purl.obolibrary.org/obo/BFO_0000185",
        "has_member_part": "http://purl.obolibrary.org/obo/BFO_0000115",
        "label": "http://www.w3.org/2000/01/rdf-schema#label",
        "material_basis_of": "http://purl.obolibrary.org/obo/BFO_0000127",
        "member_part_of": "http://purl.obolibrary.org/obo/BFO_0000129",
    }
    _object_properties: ClassVar[set[str]] = {
        "continuant_part_of",
        "exists_at",
        "has_continuant_part",
        "has_history",
        "has_member_part",
        "material_basis_of",
        "member_part_of",
    }

    # Data properties
    label: Optional[Annotated[str, Field(description="Label of the resource.")]] = None
    created: Annotated[
        Optional[datetime.datetime],
        Field(description="Date of creation of the resource."),
    ] = datetime.datetime.now()
    creator: Annotated[
        Optional[Any],
        Field(description="An entity responsible for making the resource."),
    ] = os.environ.get("USER")

    # Object properties
    continuant_part_of: Optional[
        Annotated[
            List[Union[MaterialEntity, URIRef, str]],
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
    has_continuant_part: Optional[
        Annotated[
            List[Union[ContinuantFiatBoundary, MaterialEntity, Site, URIRef, str]],
            Field(description="b has continuant part c =Def c continuant part of b"),
        ]
    ] = None
    has_history: Optional[
        Annotated[
            List[Union[History, URIRef, str]],
            Field(description="b has history c =Def c history of b"),
        ]
    ] = None
    has_member_part: Optional[
        Annotated[
            List[Union[MaterialEntity, URIRef, str]],
            Field(description="b has member part c =Def c member part of b"),
        ]
    ] = None
    material_basis_of: Optional[
        Annotated[
            List[Union[Disposition, URIRef, str]],
            Field(description="b material basis of c =Def c has material basis b"),
        ]
    ] = None
    member_part_of: Optional[
        Annotated[
            List[Union[MaterialEntity, URIRef, str]],
            Field(
                description="b member part of c =Def b is an object & c is a material entity & there is some time t such that b continuant part of c at t & there is a mutually exhaustive and pairwise disjoint partition of c into objects x1, ..., xn (for some n ≠ 1) with b = xi (for some 1 <= i <= n)"
            ),
        ]
    ] = None


class Site(ImmaterialEntity, RDFEntity):
    """
    site
    """

    _class_uri: ClassVar[str] = "http://purl.obolibrary.org/obo/BFO_0000029"
    _name: ClassVar[str] = "site"
    _property_uris: ClassVar[dict] = {
        "continuant_part_of": "http://purl.obolibrary.org/obo/BFO_0000176",
        "created": "http://purl.org/dc/terms/created",
        "creator": "http://purl.org/dc/terms/creator",
        "exists_at": "http://purl.obolibrary.org/obo/BFO_0000108",
        "has_continuant_part": "http://purl.obolibrary.org/obo/BFO_0000178",
        "label": "http://www.w3.org/2000/01/rdf-schema#label",
        "occupies_spatial_region": "http://purl.obolibrary.org/obo/BFO_0000210",
    }
    _object_properties: ClassVar[set[str]] = {
        "continuant_part_of",
        "exists_at",
        "has_continuant_part",
        "occupies_spatial_region",
    }

    # Data properties
    label: Optional[Annotated[str, Field(description="Label of the resource.")]] = None
    created: Annotated[
        Optional[datetime.datetime],
        Field(description="Date of creation of the resource."),
    ] = datetime.datetime.now()
    creator: Annotated[
        Optional[Any],
        Field(description="An entity responsible for making the resource."),
    ] = os.environ.get("USER")

    # Object properties
    continuant_part_of: Optional[
        Annotated[
            List[Union[MaterialEntity, Site, URIRef, str]],
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
    has_continuant_part: Optional[
        Annotated[
            List[Union[ContinuantFiatBoundary, Site, URIRef, str]],
            Field(description="b has continuant part c =Def c continuant part of b"),
        ]
    ] = None
    occupies_spatial_region: Optional[
        Annotated[
            List[Union[ThreedimensionalSpatialRegion, URIRef, str]],
            Field(
                description="b occupies spatial region r =Def b is an independent continuant that is not a spatial region & r is a spatial region & there is some time t such that every continuant part of b occupies some continuant part of r at t and no continuant part of b occupies any spatial region that is not a continuant part of r at t"
            ),
        ]
    ] = None


class Object(MaterialEntity, RDFEntity):
    """
    object
    """

    _class_uri: ClassVar[str] = "http://purl.obolibrary.org/obo/BFO_0000030"
    _name: ClassVar[str] = "object"
    _property_uris: ClassVar[dict] = {
        "continuant_part_of": "http://purl.obolibrary.org/obo/BFO_0000176",
        "created": "http://purl.org/dc/terms/created",
        "creator": "http://purl.org/dc/terms/creator",
        "exists_at": "http://purl.obolibrary.org/obo/BFO_0000108",
        "has_continuant_part": "http://purl.obolibrary.org/obo/BFO_0000178",
        "has_history": "http://purl.obolibrary.org/obo/BFO_0000185",
        "has_member_part": "http://purl.obolibrary.org/obo/BFO_0000115",
        "label": "http://www.w3.org/2000/01/rdf-schema#label",
        "material_basis_of": "http://purl.obolibrary.org/obo/BFO_0000127",
        "member_part_of": "http://purl.obolibrary.org/obo/BFO_0000129",
    }
    _object_properties: ClassVar[set[str]] = {
        "continuant_part_of",
        "exists_at",
        "has_continuant_part",
        "has_history",
        "has_member_part",
        "material_basis_of",
        "member_part_of",
    }

    # Data properties
    label: Optional[Annotated[str, Field(description="Label of the resource.")]] = None
    created: Annotated[
        Optional[datetime.datetime],
        Field(description="Date of creation of the resource."),
    ] = datetime.datetime.now()
    creator: Annotated[
        Optional[Any],
        Field(description="An entity responsible for making the resource."),
    ] = os.environ.get("USER")

    # Object properties
    continuant_part_of: Optional[
        Annotated[
            List[Union[MaterialEntity, URIRef, str]],
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
    has_continuant_part: Optional[
        Annotated[
            List[Union[ContinuantFiatBoundary, MaterialEntity, Site, URIRef, str]],
            Field(description="b has continuant part c =Def c continuant part of b"),
        ]
    ] = None
    has_history: Optional[
        Annotated[
            List[Union[History, URIRef, str]],
            Field(description="b has history c =Def c history of b"),
        ]
    ] = None
    has_member_part: Optional[
        Annotated[
            List[Union[MaterialEntity, URIRef, str]],
            Field(description="b has member part c =Def c member part of b"),
        ]
    ] = None
    material_basis_of: Optional[
        Annotated[
            List[Union[Disposition, URIRef, str]],
            Field(description="b material basis of c =Def c has material basis b"),
        ]
    ] = None
    member_part_of: Optional[
        Annotated[
            List[Union[MaterialEntity, URIRef, str]],
            Field(
                description="b member part of c =Def b is an object & c is a material entity & there is some time t such that b continuant part of c at t & there is a mutually exhaustive and pairwise disjoint partition of c into objects x1, ..., xn (for some n ≠ 1) with b = xi (for some 1 <= i <= n)"
            ),
        ]
    ] = None


class ContinuantFiatBoundary(ImmaterialEntity, RDFEntity):
    """
    continuant fiat boundary
    """

    _class_uri: ClassVar[str] = "http://purl.obolibrary.org/obo/BFO_0000140"
    _name: ClassVar[str] = "continuant fiat boundary"
    _property_uris: ClassVar[dict] = {
        "continuant_part_of": "http://purl.obolibrary.org/obo/BFO_0000176",
        "created": "http://purl.org/dc/terms/created",
        "creator": "http://purl.org/dc/terms/creator",
        "exists_at": "http://purl.obolibrary.org/obo/BFO_0000108",
        "has_continuant_part": "http://purl.obolibrary.org/obo/BFO_0000178",
        "label": "http://www.w3.org/2000/01/rdf-schema#label",
        "location_of": "http://purl.obolibrary.org/obo/BFO_0000124",
    }
    _object_properties: ClassVar[set[str]] = {
        "continuant_part_of",
        "exists_at",
        "has_continuant_part",
        "location_of",
    }

    # Data properties
    label: Optional[Annotated[str, Field(description="Label of the resource.")]] = None
    created: Annotated[
        Optional[datetime.datetime],
        Field(description="Date of creation of the resource."),
    ] = datetime.datetime.now()
    creator: Annotated[
        Optional[Any],
        Field(description="An entity responsible for making the resource."),
    ] = os.environ.get("USER")

    # Object properties
    continuant_part_of: Optional[
        Annotated[
            List[Union[IndependentContinuant, URIRef, str]],
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
    has_continuant_part: Optional[
        Annotated[
            List[Union[ContinuantFiatBoundary, URIRef, str]],
            Field(description="b has continuant part c =Def c continuant part of b"),
        ]
    ] = None
    location_of: Optional[
        Annotated[
            List[Union[ContinuantFiatBoundary, URIRef, str]],
            Field(description="b location of c =Def c located in b"),
        ]
    ] = None


class RelationalQuality(Quality, RDFEntity):
    """
    relational quality
    """

    _class_uri: ClassVar[str] = "http://purl.obolibrary.org/obo/BFO_0000145"
    _name: ClassVar[str] = "relational quality"
    _property_uris: ClassVar[dict] = {
        "continuant_part_of": "http://purl.obolibrary.org/obo/BFO_0000176",
        "created": "http://purl.org/dc/terms/created",
        "creator": "http://purl.org/dc/terms/creator",
        "exists_at": "http://purl.obolibrary.org/obo/BFO_0000108",
        "has_continuant_part": "http://purl.obolibrary.org/obo/BFO_0000178",
        "inheres_in": "http://purl.obolibrary.org/obo/BFO_0000197",
        "label": "http://www.w3.org/2000/01/rdf-schema#label",
        "specifically_depends_on": "http://purl.obolibrary.org/obo/BFO_0000195",
    }
    _object_properties: ClassVar[set[str]] = {
        "continuant_part_of",
        "exists_at",
        "has_continuant_part",
        "inheres_in",
        "specifically_depends_on",
    }

    # Data properties
    label: Optional[Annotated[str, Field(description="Label of the resource.")]] = None
    created: Annotated[
        Optional[datetime.datetime],
        Field(description="Date of creation of the resource."),
    ] = datetime.datetime.now()
    creator: Annotated[
        Optional[Any],
        Field(description="An entity responsible for making the resource."),
    ] = os.environ.get("USER")

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
    has_continuant_part: Optional[
        Annotated[
            List[Union[Continuant, URIRef, str]],
            Field(description="b has continuant part c =Def c continuant part of b"),
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


class TemporalInterval(OnedimensionalTemporalRegion, RDFEntity):
    """
    temporal interval
    """

    _class_uri: ClassVar[str] = "http://purl.obolibrary.org/obo/BFO_0000202"
    _name: ClassVar[str] = "temporal interval"
    _property_uris: ClassVar[dict] = {
        "created": "http://purl.org/dc/terms/created",
        "creator": "http://purl.org/dc/terms/creator",
        "exists_at": "http://purl.obolibrary.org/obo/BFO_0000108",
        "has_first_instant": "http://purl.obolibrary.org/obo/BFO_0000222",
        "has_last_instant": "http://purl.obolibrary.org/obo/BFO_0000224",
        "has_occurrent_part": "http://purl.obolibrary.org/obo/BFO_0000117",
        "has_temporal_part": "http://purl.obolibrary.org/obo/BFO_0000121",
        "label": "http://www.w3.org/2000/01/rdf-schema#label",
        "occurrent_part_of": "http://purl.obolibrary.org/obo/BFO_0000132",
        "preceded_by": "http://purl.obolibrary.org/obo/BFO_0000062",
        "precedes": "http://purl.obolibrary.org/obo/BFO_0000063",
        "temporal_part_of": "http://purl.obolibrary.org/obo/BFO_0000139",
    }
    _object_properties: ClassVar[set[str]] = {
        "exists_at",
        "has_first_instant",
        "has_last_instant",
        "has_occurrent_part",
        "has_temporal_part",
        "occurrent_part_of",
        "preceded_by",
        "precedes",
        "temporal_part_of",
    }

    # Data properties
    label: Optional[Annotated[str, Field(description="Label of the resource.")]] = None
    created: Annotated[
        Optional[datetime.datetime],
        Field(description="Date of creation of the resource."),
    ] = datetime.datetime.now()
    creator: Annotated[
        Optional[Any],
        Field(description="An entity responsible for making the resource."),
    ] = os.environ.get("USER")

    # Object properties
    exists_at: Optional[
        Annotated[
            List[Union[TemporalRegion, URIRef, str]],
            Field(
                description="(Elucidation) exists at is a relation between a particular and some temporal region at which the particular exists"
            ),
        ]
    ] = None
    has_first_instant: Optional[
        Annotated[
            List[Union[TemporalInstant, URIRef, str]],
            Field(description="t has first instant t' =Def t' first instant of t"),
        ]
    ] = None
    has_last_instant: Optional[
        Annotated[
            List[Union[TemporalInstant, URIRef, str]],
            Field(description="t has last instant t' =Def t' last instant of t"),
        ]
    ] = None
    has_occurrent_part: Optional[
        Annotated[
            List[Union[Occurrent, URIRef, str]],
            Field(description="b has occurrent part c =Def c occurrent part of b"),
        ]
    ] = None
    has_temporal_part: Optional[
        Annotated[
            List[
                Union[
                    OnedimensionalTemporalRegion,
                    URIRef,
                    ZerodimensionalTemporalRegion,
                    str,
                ]
            ],
            Field(description="b has temporal part c =Def c temporal part of b"),
        ]
    ] = None
    occurrent_part_of: Optional[
        Annotated[
            List[Union[TemporalRegion, URIRef, str]],
            Field(
                description="(Elucidation) occurrent part of is a relation between occurrents b and c when b is part of c"
            ),
        ]
    ] = None
    preceded_by: Optional[
        Annotated[
            List[Union[Occurrent, URIRef, str]],
            Field(description="b preceded by c =Def b precedes c"),
        ]
    ] = None
    precedes: Optional[
        Annotated[
            List[Union[Occurrent, URIRef, str]],
            Field(
                description="(Elucidation) precedes is a relation between occurrents o, o' such that if t is the temporal extent of o & t' is the temporal extent of o' then either the last instant of o is before the first instant of o' or the last instant of o is the first instant of o' & neither o nor o' are temporal instants"
            ),
        ]
    ] = None
    temporal_part_of: Optional[
        Annotated[
            List[Union[OnedimensionalTemporalRegion, URIRef, str]],
            Field(
                description="b temporal part of c =Def b occurrent part of c & (b and c are temporal regions) or (b and c are spatiotemporal regions & b temporally projects onto an occurrent part of the temporal region that c temporally projects onto) or (b and c are processes or process boundaries & b occupies a temporal region that is an occurrent part of the temporal region that c occupies)"
            ),
        ]
    ] = None


class TemporalInstant(ZerodimensionalTemporalRegion, RDFEntity):
    """
    temporal instant
    """

    _class_uri: ClassVar[str] = "http://purl.obolibrary.org/obo/BFO_0000203"
    _name: ClassVar[str] = "temporal instant"
    _property_uris: ClassVar[dict] = {
        "created": "http://purl.org/dc/terms/created",
        "creator": "http://purl.org/dc/terms/creator",
        "exists_at": "http://purl.obolibrary.org/obo/BFO_0000108",
        "first_instant_of": "http://purl.obolibrary.org/obo/BFO_0000221",
        "has_first_instant": "http://purl.obolibrary.org/obo/BFO_0000222",
        "has_last_instant": "http://purl.obolibrary.org/obo/BFO_0000224",
        "has_occurrent_part": "http://purl.obolibrary.org/obo/BFO_0000117",
        "has_temporal_part": "http://purl.obolibrary.org/obo/BFO_0000121",
        "label": "http://www.w3.org/2000/01/rdf-schema#label",
        "last_instant_of": "http://purl.obolibrary.org/obo/BFO_0000223",
        "occurrent_part_of": "http://purl.obolibrary.org/obo/BFO_0000132",
        "preceded_by": "http://purl.obolibrary.org/obo/BFO_0000062",
        "precedes": "http://purl.obolibrary.org/obo/BFO_0000063",
        "temporal_part_of": "http://purl.obolibrary.org/obo/BFO_0000139",
    }
    _object_properties: ClassVar[set[str]] = {
        "exists_at",
        "first_instant_of",
        "has_first_instant",
        "has_last_instant",
        "has_occurrent_part",
        "has_temporal_part",
        "last_instant_of",
        "occurrent_part_of",
        "preceded_by",
        "precedes",
        "temporal_part_of",
    }

    # Data properties
    label: Optional[Annotated[str, Field(description="Label of the resource.")]] = None
    created: Annotated[
        Optional[datetime.datetime],
        Field(description="Date of creation of the resource."),
    ] = datetime.datetime.now()
    creator: Annotated[
        Optional[Any],
        Field(description="An entity responsible for making the resource."),
    ] = os.environ.get("USER")

    # Object properties
    exists_at: Optional[
        Annotated[
            List[Union[TemporalRegion, URIRef, str]],
            Field(
                description="(Elucidation) exists at is a relation between a particular and some temporal region at which the particular exists"
            ),
        ]
    ] = None
    first_instant_of: Optional[
        Annotated[
            List[Union[TemporalRegion, URIRef, str]],
            Field(
                description="t first instant of t' =Def t is a temporal instant & t' is a temporal region t' & t precedes all temporal parts of t' other than t"
            ),
        ]
    ] = None
    has_first_instant: Optional[
        Annotated[
            List[Union[TemporalInstant, URIRef, str]],
            Field(description="t has first instant t' =Def t' first instant of t"),
        ]
    ] = None
    has_last_instant: Optional[
        Annotated[
            List[Union[TemporalInstant, URIRef, str]],
            Field(description="t has last instant t' =Def t' last instant of t"),
        ]
    ] = None
    has_occurrent_part: Optional[
        Annotated[
            List[Union[Occurrent, URIRef, str]],
            Field(description="b has occurrent part c =Def c occurrent part of b"),
        ]
    ] = None
    has_temporal_part: Optional[
        Annotated[
            List[Union[URIRef, ZerodimensionalTemporalRegion, str]],
            Field(description="b has temporal part c =Def c temporal part of b"),
        ]
    ] = None
    last_instant_of: Optional[
        Annotated[
            List[Union[TemporalRegion, URIRef, str]],
            Field(
                description="t last instant of t' =Def t is a temporal instant & t' is a temporal region & all temporal parts of t' other than t precede t"
            ),
        ]
    ] = None
    occurrent_part_of: Optional[
        Annotated[
            List[Union[TemporalRegion, URIRef, str]],
            Field(
                description="(Elucidation) occurrent part of is a relation between occurrents b and c when b is part of c"
            ),
        ]
    ] = None
    preceded_by: Optional[
        Annotated[
            List[Union[Occurrent, URIRef, str]],
            Field(description="b preceded by c =Def b precedes c"),
        ]
    ] = None
    precedes: Optional[
        Annotated[
            List[Union[Occurrent, URIRef, str]],
            Field(
                description="(Elucidation) precedes is a relation between occurrents o, o' such that if t is the temporal extent of o & t' is the temporal extent of o' then either the last instant of o is before the first instant of o' or the last instant of o is the first instant of o' & neither o nor o' are temporal instants"
            ),
        ]
    ] = None
    temporal_part_of: Optional[
        Annotated[
            List[Union[TemporalRegion, URIRef, str]],
            Field(
                description="b temporal part of c =Def b occurrent part of c & (b and c are temporal regions) or (b and c are spatiotemporal regions & b temporally projects onto an occurrent part of the temporal region that c temporally projects onto) or (b and c are processes or process boundaries & b occupies a temporal region that is an occurrent part of the temporal region that c occupies)"
            ),
        ]
    ] = None


class TwodimensionalSpatialRegion(SpatialRegion, RDFEntity):
    """
    two-dimensional spatial region
    """

    _class_uri: ClassVar[str] = "http://purl.obolibrary.org/obo/BFO_0000009"
    _name: ClassVar[str] = "two-dimensional spatial region"
    _property_uris: ClassVar[dict] = {
        "continuant_part_of": "http://purl.obolibrary.org/obo/BFO_0000176",
        "created": "http://purl.org/dc/terms/created",
        "creator": "http://purl.org/dc/terms/creator",
        "exists_at": "http://purl.obolibrary.org/obo/BFO_0000108",
        "has_continuant_part": "http://purl.obolibrary.org/obo/BFO_0000178",
        "label": "http://www.w3.org/2000/01/rdf-schema#label",
    }
    _object_properties: ClassVar[set[str]] = {
        "continuant_part_of",
        "exists_at",
        "has_continuant_part",
    }

    # Data properties
    label: Optional[Annotated[str, Field(description="Label of the resource.")]] = None
    created: Annotated[
        Optional[datetime.datetime],
        Field(description="Date of creation of the resource."),
    ] = datetime.datetime.now()
    creator: Annotated[
        Optional[Any],
        Field(description="An entity responsible for making the resource."),
    ] = os.environ.get("USER")

    # Object properties
    continuant_part_of: Optional[
        Annotated[
            List[Union[SpatialRegion, URIRef, str]],
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
    has_continuant_part: Optional[
        Annotated[
            List[
                Union[
                    OnedimensionalSpatialRegion,
                    TwodimensionalSpatialRegion,
                    URIRef,
                    ZerodimensionalSpatialRegion,
                    str,
                ]
            ],
            Field(description="b has continuant part c =Def c continuant part of b"),
        ]
    ] = None


class ZerodimensionalSpatialRegion(SpatialRegion, RDFEntity):
    """
    zero-dimensional spatial region
    """

    _class_uri: ClassVar[str] = "http://purl.obolibrary.org/obo/BFO_0000018"
    _name: ClassVar[str] = "zero-dimensional spatial region"
    _property_uris: ClassVar[dict] = {
        "continuant_part_of": "http://purl.obolibrary.org/obo/BFO_0000176",
        "created": "http://purl.org/dc/terms/created",
        "creator": "http://purl.org/dc/terms/creator",
        "exists_at": "http://purl.obolibrary.org/obo/BFO_0000108",
        "has_continuant_part": "http://purl.obolibrary.org/obo/BFO_0000178",
        "label": "http://www.w3.org/2000/01/rdf-schema#label",
    }
    _object_properties: ClassVar[set[str]] = {
        "continuant_part_of",
        "exists_at",
        "has_continuant_part",
    }

    # Data properties
    label: Optional[Annotated[str, Field(description="Label of the resource.")]] = None
    created: Annotated[
        Optional[datetime.datetime],
        Field(description="Date of creation of the resource."),
    ] = datetime.datetime.now()
    creator: Annotated[
        Optional[Any],
        Field(description="An entity responsible for making the resource."),
    ] = os.environ.get("USER")

    # Object properties
    continuant_part_of: Optional[
        Annotated[
            List[Union[SpatialRegion, URIRef, str]],
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
    has_continuant_part: Optional[
        Annotated[
            List[Union[URIRef, ZerodimensionalSpatialRegion, str]],
            Field(description="b has continuant part c =Def c continuant part of b"),
        ]
    ] = None


class OnedimensionalSpatialRegion(SpatialRegion, RDFEntity):
    """
    one-dimensional spatial region
    """

    _class_uri: ClassVar[str] = "http://purl.obolibrary.org/obo/BFO_0000026"
    _name: ClassVar[str] = "one-dimensional spatial region"
    _property_uris: ClassVar[dict] = {
        "continuant_part_of": "http://purl.obolibrary.org/obo/BFO_0000176",
        "created": "http://purl.org/dc/terms/created",
        "creator": "http://purl.org/dc/terms/creator",
        "exists_at": "http://purl.obolibrary.org/obo/BFO_0000108",
        "has_continuant_part": "http://purl.obolibrary.org/obo/BFO_0000178",
        "label": "http://www.w3.org/2000/01/rdf-schema#label",
    }
    _object_properties: ClassVar[set[str]] = {
        "continuant_part_of",
        "exists_at",
        "has_continuant_part",
    }

    # Data properties
    label: Optional[Annotated[str, Field(description="Label of the resource.")]] = None
    created: Annotated[
        Optional[datetime.datetime],
        Field(description="Date of creation of the resource."),
    ] = datetime.datetime.now()
    creator: Annotated[
        Optional[Any],
        Field(description="An entity responsible for making the resource."),
    ] = os.environ.get("USER")

    # Object properties
    continuant_part_of: Optional[
        Annotated[
            List[Union[SpatialRegion, URIRef, str]],
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
    has_continuant_part: Optional[
        Annotated[
            List[
                Union[
                    OnedimensionalSpatialRegion,
                    URIRef,
                    ZerodimensionalSpatialRegion,
                    str,
                ]
            ],
            Field(description="b has continuant part c =Def c continuant part of b"),
        ]
    ] = None


class ThreedimensionalSpatialRegion(SpatialRegion, RDFEntity):
    """
    three-dimensional spatial region
    """

    _class_uri: ClassVar[str] = "http://purl.obolibrary.org/obo/BFO_0000028"
    _name: ClassVar[str] = "three-dimensional spatial region"
    _property_uris: ClassVar[dict] = {
        "continuant_part_of": "http://purl.obolibrary.org/obo/BFO_0000176",
        "created": "http://purl.org/dc/terms/created",
        "creator": "http://purl.org/dc/terms/creator",
        "exists_at": "http://purl.obolibrary.org/obo/BFO_0000108",
        "has_continuant_part": "http://purl.obolibrary.org/obo/BFO_0000178",
        "label": "http://www.w3.org/2000/01/rdf-schema#label",
    }
    _object_properties: ClassVar[set[str]] = {
        "continuant_part_of",
        "exists_at",
        "has_continuant_part",
    }

    # Data properties
    label: Optional[Annotated[str, Field(description="Label of the resource.")]] = None
    created: Annotated[
        Optional[datetime.datetime],
        Field(description="Date of creation of the resource."),
    ] = datetime.datetime.now()
    creator: Annotated[
        Optional[Any],
        Field(description="An entity responsible for making the resource."),
    ] = os.environ.get("USER")

    # Object properties
    continuant_part_of: Optional[
        Annotated[
            List[Union[SpatialRegion, URIRef, str]],
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
    has_continuant_part: Optional[
        Annotated[
            List[Union[SpatialRegion, URIRef, str]],
            Field(description="b has continuant part c =Def c continuant part of b"),
        ]
    ] = None


class Function(Disposition, RDFEntity):
    """
    function
    """

    _class_uri: ClassVar[str] = "http://purl.obolibrary.org/obo/BFO_0000034"
    _name: ClassVar[str] = "function"
    _property_uris: ClassVar[dict] = {
        "continuant_part_of": "http://purl.obolibrary.org/obo/BFO_0000176",
        "created": "http://purl.org/dc/terms/created",
        "creator": "http://purl.org/dc/terms/creator",
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
        "exists_at",
        "has_continuant_part",
        "has_material_basis",
        "has_realization",
        "inheres_in",
        "specifically_depends_on",
    }

    # Data properties
    label: Optional[Annotated[str, Field(description="Label of the resource.")]] = None
    created: Annotated[
        Optional[datetime.datetime],
        Field(description="Date of creation of the resource."),
    ] = datetime.datetime.now()
    creator: Annotated[
        Optional[Any],
        Field(description="An entity responsible for making the resource."),
    ] = os.environ.get("USER")

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


class FiatLine(ContinuantFiatBoundary, RDFEntity):
    """
    fiat line
    """

    _class_uri: ClassVar[str] = "http://purl.obolibrary.org/obo/BFO_0000142"
    _name: ClassVar[str] = "fiat line"
    _property_uris: ClassVar[dict] = {
        "continuant_part_of": "http://purl.obolibrary.org/obo/BFO_0000176",
        "created": "http://purl.org/dc/terms/created",
        "creator": "http://purl.org/dc/terms/creator",
        "exists_at": "http://purl.obolibrary.org/obo/BFO_0000108",
        "has_continuant_part": "http://purl.obolibrary.org/obo/BFO_0000178",
        "label": "http://www.w3.org/2000/01/rdf-schema#label",
        "location_of": "http://purl.obolibrary.org/obo/BFO_0000124",
    }
    _object_properties: ClassVar[set[str]] = {
        "continuant_part_of",
        "exists_at",
        "has_continuant_part",
        "location_of",
    }

    # Data properties
    label: Optional[Annotated[str, Field(description="Label of the resource.")]] = None
    created: Annotated[
        Optional[datetime.datetime],
        Field(description="Date of creation of the resource."),
    ] = datetime.datetime.now()
    creator: Annotated[
        Optional[Any],
        Field(description="An entity responsible for making the resource."),
    ] = os.environ.get("USER")

    # Object properties
    continuant_part_of: Optional[
        Annotated[
            List[Union[IndependentContinuant, URIRef, str]],
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
    has_continuant_part: Optional[
        Annotated[
            List[Union[FiatLine, FiatPoint, URIRef, str]],
            Field(description="b has continuant part c =Def c continuant part of b"),
        ]
    ] = None
    location_of: Optional[
        Annotated[
            List[Union[ContinuantFiatBoundary, URIRef, str]],
            Field(description="b location of c =Def c located in b"),
        ]
    ] = None


class FiatSurface(ContinuantFiatBoundary, RDFEntity):
    """
    fiat surface
    """

    _class_uri: ClassVar[str] = "http://purl.obolibrary.org/obo/BFO_0000146"
    _name: ClassVar[str] = "fiat surface"
    _property_uris: ClassVar[dict] = {
        "continuant_part_of": "http://purl.obolibrary.org/obo/BFO_0000176",
        "created": "http://purl.org/dc/terms/created",
        "creator": "http://purl.org/dc/terms/creator",
        "exists_at": "http://purl.obolibrary.org/obo/BFO_0000108",
        "has_continuant_part": "http://purl.obolibrary.org/obo/BFO_0000178",
        "label": "http://www.w3.org/2000/01/rdf-schema#label",
        "location_of": "http://purl.obolibrary.org/obo/BFO_0000124",
    }
    _object_properties: ClassVar[set[str]] = {
        "continuant_part_of",
        "exists_at",
        "has_continuant_part",
        "location_of",
    }

    # Data properties
    label: Optional[Annotated[str, Field(description="Label of the resource.")]] = None
    created: Annotated[
        Optional[datetime.datetime],
        Field(description="Date of creation of the resource."),
    ] = datetime.datetime.now()
    creator: Annotated[
        Optional[Any],
        Field(description="An entity responsible for making the resource."),
    ] = os.environ.get("USER")

    # Object properties
    continuant_part_of: Optional[
        Annotated[
            List[Union[IndependentContinuant, URIRef, str]],
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
    has_continuant_part: Optional[
        Annotated[
            List[Union[ContinuantFiatBoundary, URIRef, str]],
            Field(description="b has continuant part c =Def c continuant part of b"),
        ]
    ] = None
    location_of: Optional[
        Annotated[
            List[Union[ContinuantFiatBoundary, URIRef, str]],
            Field(description="b location of c =Def c located in b"),
        ]
    ] = None


class FiatPoint(ContinuantFiatBoundary, RDFEntity):
    """
    fiat point
    """

    _class_uri: ClassVar[str] = "http://purl.obolibrary.org/obo/BFO_0000147"
    _name: ClassVar[str] = "fiat point"
    _property_uris: ClassVar[dict] = {
        "continuant_part_of": "http://purl.obolibrary.org/obo/BFO_0000176",
        "created": "http://purl.org/dc/terms/created",
        "creator": "http://purl.org/dc/terms/creator",
        "exists_at": "http://purl.obolibrary.org/obo/BFO_0000108",
        "has_continuant_part": "http://purl.obolibrary.org/obo/BFO_0000178",
        "label": "http://www.w3.org/2000/01/rdf-schema#label",
        "location_of": "http://purl.obolibrary.org/obo/BFO_0000124",
    }
    _object_properties: ClassVar[set[str]] = {
        "continuant_part_of",
        "exists_at",
        "has_continuant_part",
        "location_of",
    }

    # Data properties
    label: Optional[Annotated[str, Field(description="Label of the resource.")]] = None
    created: Annotated[
        Optional[datetime.datetime],
        Field(description="Date of creation of the resource."),
    ] = datetime.datetime.now()
    creator: Annotated[
        Optional[Any],
        Field(description="An entity responsible for making the resource."),
    ] = os.environ.get("USER")

    # Object properties
    continuant_part_of: Optional[
        Annotated[
            List[Union[IndependentContinuant, URIRef, str]],
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
    has_continuant_part: Optional[
        Annotated[
            List[Union[FiatPoint, URIRef, str]],
            Field(description="b has continuant part c =Def c continuant part of b"),
        ]
    ] = None
    location_of: Optional[
        Annotated[
            List[Union[ContinuantFiatBoundary, URIRef, str]],
            Field(description="b location of c =Def c located in b"),
        ]
    ] = None


# Rebuild models to resolve forward references
Entity.model_rebuild()
Continuant.model_rebuild()
Occurrent.model_rebuild()
IndependentContinuant.model_rebuild()
TemporalRegion.model_rebuild()
SpatiotemporalRegion.model_rebuild()
Process.model_rebuild()
SpecificallyDependentContinuant.model_rebuild()
GenericallyDependentContinuant.model_rebuild()
ProcessBoundary.model_rebuild()
RealizableEntity.model_rebuild()
Quality.model_rebuild()
OnedimensionalTemporalRegion.model_rebuild()
MaterialEntity.model_rebuild()
ImmaterialEntity.model_rebuild()
ZerodimensionalTemporalRegion.model_rebuild()
History.model_rebuild()
SpatialRegion.model_rebuild()
Disposition.model_rebuild()
Role.model_rebuild()
FiatObjectPart.model_rebuild()
ObjectAggregate.model_rebuild()
Site.model_rebuild()
Object.model_rebuild()
ContinuantFiatBoundary.model_rebuild()
RelationalQuality.model_rebuild()
TemporalInterval.model_rebuild()
TemporalInstant.model_rebuild()
TwodimensionalSpatialRegion.model_rebuild()
ZerodimensionalSpatialRegion.model_rebuild()
OnedimensionalSpatialRegion.model_rebuild()
ThreedimensionalSpatialRegion.model_rebuild()
Function.model_rebuild()
FiatLine.model_rebuild()
FiatSurface.model_rebuild()
FiatPoint.model_rebuild()
