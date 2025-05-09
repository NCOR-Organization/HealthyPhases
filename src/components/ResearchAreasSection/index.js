import React from 'react';
import Link from '@docusaurus/Link';
import styles from './styles.module.css';

export default function ResearchAreasSection() {
  const researchAreas = [
    {
      title: 'Solitude & Loneliness',
      description: 'Investigating the distinct experiences of solitude, loneliness, and social isolation and their impacts on health and well-being.',
      link: '/docs/research/aims#aim-1-ontology-development'
    },
    {
      title: 'Gerotranscendence',
      description: 'Exploring the developmental shift in perspective that can occur in later life, characterized by changes in values and cosmic awareness.',
      link: '/docs/about/background#understanding-gerotranscendence'
    },
    {
      title: 'Ontology Development',
      description: 'Creating formal representations of knowledge to standardize terminology and relationships in solitude and aging research.',
      link: '/docs/research/ontology-development'
    },
    {
      title: 'Common Data Model',
      description: 'Designing standardized frameworks for collecting, representing, and sharing data on solitude and gerotranscendence.',
      link: '/wiki/common-data-model'
    },
    {
      title: 'Semantic Enrichment',
      description: 'Enhancing research data with structured, machine-interpretable annotations to enable integration and discovery.',
      link: '/wiki/semantic-enrichment'
    },
    {
      title: 'Knowledge Graphs',
      description: 'Building semantic networks that represent entities and relationships to support querying, inference, and discovery.',
      link: '/wiki/knowledge-graph'
    }
  ];

  return (
    <div className={styles.researchAreasContainer}>
      <div className="container">
        <div className={styles.sectionHeader}>
          <h2 className={styles.sectionTitle}>
            Research <span className={styles.highlight}>Areas</span>
          </h2>
          <p className={styles.sectionDescription}>
            The HealthyPhases Project bridges isolated research areas through semantic enrichment and standardization,
            transforming our understanding of solitude's role in healthy aging.
          </p>
        </div>

        <div className={styles.cardsContainer}>
          {researchAreas.map((area, index) => (
            <div key={index} className={styles.researchCard}>
              <h3 className={styles.cardTitle}>{area.title}</h3>
              <p className={styles.cardDescription}>{area.description}</p>
              <Link to={area.link} className={styles.learnMoreLink}>
                Learn more{' '}
                <svg
                  className={styles.arrowIcon}
                  width="16"
                  height="16"
                  viewBox="0 0 24 24"
                  fill="none"
                  xmlns="http://www.w3.org/2000/svg"
                >
                  <path
                    d="M5 12H19"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                  <path
                    d="M12 5L19 12L12 19"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              </Link>
            </div>
          ))}
        </div>

        <div className={styles.viewAllContainer}>
          <Link
            to="/docs/research/areas"
            className={styles.viewAllButton}
          >
            View Research Areas{' '}
            <svg
              width="20"
              height="20"
              viewBox="0 0 24 24"
              fill="none"
              xmlns="http://www.w3.org/2000/svg"
              className={styles.buttonArrow}
            >
              <path
                d="M5 12H19"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
              <path
                d="M12 5L19 12L12 19"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </Link>
        </div>
      </div>
    </div>
  );
} 