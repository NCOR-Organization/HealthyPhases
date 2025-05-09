# HealthyPhases Project

![HealthyPhases Banner](./static/img/healthyphases-banner.png)

[![Website Status](https://img.shields.io/website?url=https%3A%2F%2Fhealthyphases.org&label=website&style=flat-square&logo=docusaurus)](https://healthyphases.org)

This repository contains the website for the HealthyPhases Project: Promoting Healthy Aging through Semantic Enrichment of Solitude Research (PHASES).

## What is the HealthyPhases Project?

The HealthyPhases Project is a multidisciplinary research initiative focused on promoting healthy aging through the semantic enrichment of solitude research. Our team brings together expertise in ontology development, psychology, computer science, and gerontology to address the challenges of terminological ambiguity and data interoperability in research on solitude and gerotranscendence.

Through the development of standardized ontologies and data models, we aim to bridge isolated research areas, foster interoperability of research data, and advance our understanding of how solitude impacts healthy aging processes.

## Project Aims

1. **Ontology Development**: Create standardized vocabularies and semantic frameworks that precisely define terms and relationships in solitude and gerotranscendence research
2. **Ontology-Based Web Resources**: Develop practical web-based tools implementing our ontological framework
3. **Promotion and Dissemination**: Engage with the research community through workshops, conferences, and educational resources

## Research Team

**Principal Investigators**
- John Beverley (University at Buffalo)
- Bill Duncan (University of Florida)

**Co-Investigators**
- Hollen Reischer (University at Buffalo)
- Julie Bowker (University at Buffalo)
- Oliver He (University of Michigan)

## Website Setup

### Prerequisites

- [Node.js](https://nodejs.org/) ≥ 18.0.0
- npm (comes with Node.js)

### Step-by-Step Setup

### 1. Clone the Repository

```bash
git clone https://github.com/HealthyPhases/HealthyPhases.git
cd HealthyPhases
```

### 2. Install Dependencies

```bash
# Install from the root directory
npm install
```

### 3. Start the Development Server

```bash
# From the project root
npm run start
```

This will start the server at http://localhost:3000/

### 4. Development Workflow

1. Edit files in the following directories:
   - `docs/` - Documentation content (Markdown)
   - `src/` - React components and styling
   - `static/` - Images and other static assets

2. The browser will automatically refresh to show your changes

3. To test a production build locally:
   ```bash
   npm run build
   npm run serve
   ```

## Project Structure

```
HealthyPhases/
├── docs/              # Documentation markdown files
├── src/               # React components and custom CSS
│   ├── components/    # Reusable components
│   ├── css/           # Custom CSS styles
│   └── pages/         # Custom React pages
├── static/            # Static assets (images, etc.)
├── wiki/              # Wiki content and resources
├── docusaurus.config.js  # Main configuration
├── sidebars.js        # Main sidebar configuration
└── package.json       # Project configuration
```

## Contact

For inquiries about the HealthyPhases Project, please contact:

**John Beverley, PhD**  
Department of Philosophy  
University at Buffalo  
Email: johnbeve@buffalo.edu 

## License

This project is licensed under the BSD-3 License.
