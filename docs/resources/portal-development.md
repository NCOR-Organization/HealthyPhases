---
sidebar_position: 2
title: Portal Development
description: Web portal for exploring solitude and gerotranscendence constructs with AI-powered tools
---

# Portal Development

The HealthyPhases website serves as our comprehensive research portal - a web-based platform designed to facilitate exploration, discovery, and analysis of solitude and gerotranscendence research through semantic enrichment and AI-powered tools.

## Portal Overview

In the context of the solitude and gerotranscendence literatures, the growth and complexity of research necessitates the development of efficient systems for organizing, accessing, and extracting insights from these research areas. We have created a new web portal through which researchers, clinicians, educators, and students may interact with semantically enriched solitude and gerotranscendence data.

## Core Services

The portal will provide three major services to stakeholders through the PHASES Ingestion Pipeline:

### 1. Recommender System

A recommender system for solitude and gerotranscendence research provides automated recommendations for research themes, articles, and authors based on stakeholder profiles and preferences.

**Technical Approach:**
- Ontologies and knowledge graphs enrich the recommender system
- Reduces the need for large amounts of training data through formal specification of entities and relationships
- Provides robust explanations for recommendations through clear logical reasoning
- Hosted recommender system enriched by the PHASES ontologies
- Allows researchers to remain up-to-date on cutting-edge work in these respective fields

**Current Status:** In Development

### 2. Question-Answer System

A question-answer system for solitude and gerotranscendence research allows stakeholders to pose natural language questions about constructs, methods, and findings across solitude and gerotranscendence literatures.

**Current Technical Implementation:**
- **LLM Integration**: Gemini free API with basic system prompt
- **ABI Framework**: Open source Agentic Brain Infrastructure for API orchestration
- **PubMed Integration**: Direct API calls to retrieve and analyze research papers
- **Ontology-Driven Search**: Leverages solitude and gerotranscendence ontologies for enhanced paper discovery
- **Downloadable Links**: Provides direct access to research papers and resources

**Current Capabilities:**
- Natural language queries about solitude and gerotranscendence research
- PubMed paper discovery and retrieval
- Ontology-based search result enhancement
- Direct links to downloadable research papers

**Current Status:** Phase 3 Active - Access the Q&A system at [/chat](/chat)

### 3. Inference Extraction System

An inference extraction system that leverages the PHASES Knowledge Graphs to discover new relationships and insights across solitude and gerotranscendence research domains.

**Planned Technical Implementation:**
- **SHACL Validation**: Shapes Constraint Language for data quality and validation
- **SPARQL Querying**: Advanced semantic queries across the knowledge graphs
- **Multi-source Integration**: PsyArXiv, OSFPREPRINTS, NIH NLM data sources
- **Metadata Enrichment**: UMLS and W3C standards integration
- **Semantic Interoperability**: FHIR-aligned datasets across domains

**Current Status:** Planned for Phase 4

## Technical Architecture

### Data Integration
- **Data Sources**: PubMed (National Library of Medicine), Open Science Foundation
- **Data Model**: Fast Healthcare Interoperability Resources (FHIR) as common data model
- **Semantic Mapping**: Data mapped to Solitude Ontology and Gerotranscendence Ontology

### AI Components
- **ABI Framework**: Agentic Brain Infrastructure orchestrates all AI operations and data processing workflows
- **LLM Integration**: Gemini API with ABI framework orchestration
- **PubMed API**: Direct integration for research paper discovery
- **Ontology Integration**: Solitude and gerotranscendence ontologies for enhanced search
- **Semantic Enrichment**: Ontological annotations and relationship mapping (in development)

### ABI Framework Role
The ABI (Agentic Brain Infrastructure) framework serves as the central orchestration layer that:
- **API Orchestration**: Manages calls to multiple data sources (PubMed, PsyArXiv, OSFPREPRINTS, NIH NLM)
- **Workflow Management**: Coordinates data ingestion, processing, and transformation pipelines
- **LLM Integration**: Handles interactions with Large Language Models for natural language processing
- **HL7 FHIR Module**: Integrated data standardization and interoperability module within ABI
- **PHASES Ontologies Module**: Integrated semantic processing and ontology management within ABI
- **Data Processing**: Manages the flow from raw data sources through integrated modules to knowledge graphs
- **Portal Services**: Powers the Recommender, Q/A, and Inference systems in the final portal

### User Interface
- **Web Portal**: Accessible interface for researchers, clinicians, educators, and students
- **Natural Language Queries**: Support for complex questions about research constructs
- **Personalized Recommendations**: Profile-based article and author suggestions

## Development Progress

### Phase 1: Project Website (Completed)
- [x] Portal architecture design
- [x] Web portal development (this website)
- [x] Project documentation and research area descriptions
- [x] Basic website infrastructure and navigation

```mermaid
flowchart LR
    A[Project Planning] --> B[Website Design]
    B --> C[Docusaurus Setup]
    C --> D[Documentation]
    D --> E[Basic Navigation]
    E --> F[Live Website]
    
    classDef completed fill:#e8f5e8,stroke:#1b5e20,stroke-width:2px
    class A,B,C,D,E,F completed
```

**Color Legend:**
- 🟢 **Green (Completed)**: Successfully implemented and deployed components

### Phase 2: Basic LLM Integration (Completed)
- [x] LLM integration with Gemini free API
- [x] Basic system prompt implementation
- [x] Open source ABI (Agentic Brain Infrastructure) framework integration
- [x] Initial chat interface at [/chat](/chat)

```mermaid
flowchart LR
    A[Gemini API Setup] --> B[System Prompt Design]
    B --> C[ABI Framework Integration]
    C --> D[Chat Interface Development]
    D --> E[Basic Q&A Functionality]
    E --> F[Live Chat System]
    
    classDef completed fill:#e8f5e8,stroke:#1b5e20,stroke-width:2px
    class A,B,C,D,E,F completed
```

**Color Legend:**
- 🟢 **Green (Completed)**: Successfully implemented and deployed components

### Phase 3: PubMed API Integration (In Progress)
- [x] ABI framework enhancement for PubMed API calls
- [x] Ontology-based paper discovery and analysis
- [x] Natural language query processing for research questions
- [x] Paper retrieval and downloadable link generation
- [ ] Advanced semantic enrichment of search results
- [ ] Enhanced ontology-driven recommendations

```mermaid
flowchart LR
    A[PubMed API Integration] --> B[ABI Framework Enhancement]
    B --> C[Ontology-Based Search]
    C --> D[Paper Discovery]
    D --> E[Downloadable Links]
    E --> F[Enhanced Q&A System]
    
    G[Advanced Semantic Enrichment] -.-> C
    H[Enhanced Recommendations] -.-> F
    
    classDef completed fill:#e8f5e8,stroke:#1b5e20,stroke-width:2px
    classDef inprogress fill:#fff3e0,stroke:#e65100,stroke-width:2px
    
    class A,B,C,D,E,F completed
    class G,H inprogress
```

**Color Legend:**
- 🟢 **Green (Completed)**: Successfully implemented and deployed components
- 🟠 **Orange (In Progress)**: Currently being developed or enhanced

### Phase 4: PHASES Ingestion Pipeline (Planned)
- [ ] Multi-source data integration (PsyArXiv, OSFPREPRINTS, NIH NLM)
- [ ] ABI Framework orchestration with integrated modules:
  - [ ] HL7 FHIR Module for data standardization
  - [ ] PHASES Ontologies Module for semantic processing
- [ ] PHASES Knowledge Graphs construction
- [ ] UMLS and W3C metadata enrichment
- [ ] SHACL validation and SPARQL querying
- [ ] Complete portal with Recommender, Q/A, and Inference systems

```mermaid
flowchart LR
    A[Data Sources] --> B[ABI Framework]
    B --> C[PHASES Knowledge Graphs]
    C --> D[Portal]
    
    E[Metadata] --> C
    
    A1[PsyArXiv] --> A
    A2[OSFPREPRINTS] --> A
    A3[NIH NLM] --> A
    
    B1[API Orchestration] --> B
    B2[LLM Integration] --> B
    B3[Workflow Management] --> B
    B4[HL7 FHIR Module] --> B
    B5[PHASES Ontologies Module] --> B
    
    E1[UMLS] --> E
    E2[W3C] --> E
    
    D1[Recommender System] --> D
    D2[Q/A System] --> D
    D3[Inference Extraction] --> D
    
    classDef planned fill:#f3e5f5,stroke:#4a148c,stroke-width:2px
    classDef data fill:#e8f5e8,stroke:#1b5e20,stroke-width:2px
    classDef metadata fill:#fff3e0,stroke:#e65100,stroke-width:2px
    classDef abi fill:#e1f5fe,stroke:#01579b,stroke-width:2px
    
    class A,C,D,D1,D2,D3 planned
    class A1,A2,A3 data
    class E,E1,E2 metadata
    class B,B1,B2,B3,B4,B5 abi
```

**Color Legend:**
- 🔵 **Blue (ABI Framework)**: Central orchestration layer managing all AI operations and workflows
- 🟣 **Purple (Planned Components)**: Future system components and services
- 🟢 **Green (Data Sources)**: External data repositories and standards
- 🟠 **Orange (Metadata)**: Enrichment and validation standards

## Access and Usage

The HealthyPhases portal is live and available for use by the research community:

- **Free Access**: Open-access platform available at [healthyphases.org](https://healthyphases.org)
- **Q&A System**: Interactive chat interface at [/chat](/chat) with PubMed integration
- **Research Documentation**: Comprehensive resources and ontology information
- **Community Resources**: Publications, training materials, and research areas
- **Current Capabilities**: 
  - Natural language queries about solitude and gerotranscendence research
  - PubMed paper discovery and retrieval
  - Direct links to downloadable research papers
  - Ontology-enhanced search results

## Future Enhancements

- **Open Source Release**: Complete opening of the current private repository with ABI framework implementation
- **Multi-language Support**: International research collaboration
- **Collaboration Tools**: Research team features and sharing capabilities
- **Analytics Dashboard**: Usage statistics and research trend analysis

## Contributing

We welcome contributions from the research community to improve the portal's functionality and content. Please see our [Contributing Guidelines](../CONTRIBUTING.md) for more information.
