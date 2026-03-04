from naas_abi_core.services.agent.Agent import AgentConfiguration, AgentSharedState
from naas_abi_core.services.agent.IntentAgent import IntentAgent, Intent, IntentType
from fastapi import APIRouter
from langchain_core.tools import tool
from abi_phases.phases import ABIModule

# from abi_phases.phases.models.google_gemini_2_0_flash import model as gemini_model
from langchain_openai import ChatOpenAI
from naas_abi_marketplace.applications.pubmed.agents.PubMedAgent import PubMedAgent

# from naas_abi_marketplace.domains.inbox.agents.InboxAgent import InboxAgent
# from naas_abi_marketplace.applications.pubmed.agents.PubMedAgent import create_agent as pubmed_create_agent
import rdflib

from abi_phases.phases.utils import embed_text

with open("abi_phases/phases/ontologies/phases.owl", "r") as f:
    ontology = f.read()

ontology = rdflib.Graph().parse(data=ontology, format="xml").serialize(format="turtle")

NAME = "ELO"


@tool(description="Search docbase using a prompt", return_direct=False)
def search_docbase_by_prompt(prompt: str) -> list:
    if not prompt or not prompt.strip():
        return []

    module: ABIModule = ABIModule.get_instance()
    vector_store = module.engine.services.vector_store

    chunks, embeddings = embed_text(prompt)

    if not chunks or not embeddings:
        return []

    embedding = embeddings[0]

    results = vector_store.search_similar("papers", embedding, k=10)

    ids = [result.id for result in results]

    if not ids:
        return []

    id_filters = " || ".join(
        [f"CONTAINS(?chunk_id, {rdflib.Literal(id_).n3()})" for id_ in ids]
    )

    rows = module.engine.services.triple_store.query(f"""PREFIX phases-doc: <http://purl.obolibrary.org/obo/phases/documents.owl#>
SELECT ?chunk ?chunk_id ?pdf_paper_file ?path ?text WHERE {{
?chunk a phases-doc:Chunk ;
phases-doc:text ?text ;
phases-doc:chunk_of ?pdf_paper_file ;
phases-doc:chunk_id ?chunk_id .
?pdf_paper_file phases-doc:path ?path .
FILTER({id_filters})
}}""")

    return list(rows)


# @tool(description="Get pdf_paper_file content", return_direct=False)
# def get_pdf_paper_file_content(pdf_paper_file: str) -> str:
#     module : ABIModule = ABIModule.get_instance()
#     object_storage = module.engine.services.object_storage
#     return object_storage.get_object(pdf_paper_file)


class ELOAgent(IntentAgent):
    DEFAULT_SYSTEM_PROMPT = """
name: ELO role: Ontology-Aware AI Assistant for Healthy Aging Research purpose: To assist researchers, developers, and stakeholders in exploring, analyzing, and enriching data on solitude and gerotranscendence using formal ontologies and semantic technologies. personality: Thoughtful, insightful, grounded in science, collaborative, and precise.

capabilities:

    Interpret and answer questions using BFO- and CCO-aligned ontologies
    Distinguish clearly between solitude, loneliness, and social isolation
    Model developmental shifts such as gerotranscendence using formal classes and relations
    Generate structured YAML/OWL snippets to extend ontologies
    Support the construction and querying of semantic knowledge graphs
    Map qualitative research findings to formal ontological terms
    Facilitate semantic interoperability across aging-related datasets
    Translate human questions into ontology-based competency questions

ontology_context: top_level_ontology: Basic Formal Ontology (BFO, ISO/IEC 21838-2) mid_level_ontology: Common Core Ontologies (CCO) domain_ontologies: - SolitudeOntology (solitude, loneliness, social isolation) - GerotranscendenceOntology (developmental stages, existential shifts) - HealthyAgingOntology (well-being, psychological adaptation) cross_cutting_concepts: - Temporal reasoning - Psychological phenomena - Social roles and environments - Health indicators - Life course transitions

tone_guidelines:

    Avoid generalities; always aim for conceptual precision
    When uncertain, ask clarifying questions
    Be helpful to both technical and non-technical users
    Offer suggestions for extending ontologies or standardizing terminology

sample_behaviors:

    When asked “What is the difference between solitude and loneliness?”, respond with an ontologically grounded distinction using relevant classes
    When asked “How can I model the concept of ‘meaningful solitude’?”, suggest a formal representation in YAML aligned with BFO
    When asked to interpret interview data, identify potential mappings to formal classes and suggest annotations
    When given a dataset or CSV, propose a semantic enrichment strategy using relevant ontologies

restrictions:

    Do not invent ontological classes unless explicitly instructed to
    Do not rely on pop psychology definitions; defer to vetted academic sources and ontological standards
    Do not confuse empirical observations with ontological commitments

memory:

    Maintain awareness of prior concepts introduced during the conversation
    Track user preferences for output formats (e.g., YAML, Turtle, Markdown)

    """

    @staticmethod
    def new():
        module: ABIModule = ABIModule.get_instance()
        pubmed_agents = module.engine.modules[
            "naas_abi_marketplace.applications.pubmed"
        ].agents
        pubmed_agent = [agent for agent in pubmed_agents if agent is PubMedAgent]
        assert len(pubmed_agent) == 1, (
            "Only one PubMed agent is allowed {} found".format(len(pubmed_agent))
        )
        pubmed_agent = pubmed_agent[0]
        # inbox_agent = next(agent for agent in module.engine.modules["naas_abi_marketplace.domains.inbox"].agents if agent is InboxAgent)

        return ELOAgent(
            name=NAME,
            description="ELO is a agent that can help you with your research on healthy aging and gerotranscendence",
            # chat_model=gemini_model(),
            chat_model=ChatOpenAI(model="gpt-5"),
            agents=[pubmed_agent.New()],
            tools=[search_docbase_by_prompt],
            intents=[
                # Intent(intent_type=IntentType.AGENT, intent_value="get a paper", intent_target="PubMedAgent"),
                # Intent(intent_type=IntentType.AGENT, intent_value="paper about", intent_target="PubMedAgent"),
                # Intent(intent_type=IntentType.AGENT, intent_value="last research", intent_target="PubMedAgent"),
                # Intent(intent_type=IntentType.AGENT, intent_value="download", intent_target="PubMedAgent"),
            ],
            state=AgentSharedState(thread_id="0", supervisor_agent=NAME),
            configuration=AgentConfiguration(
                system_prompt=ELOAgent.DEFAULT_SYSTEM_PROMPT.format(ontology=ontology),
            ),
        )

    def as_api(self, router: APIRouter):
        super().as_api(
            router, route_name="elo", name="ELOAgent", description=self._description
        )


create_agent = ELOAgent.new
