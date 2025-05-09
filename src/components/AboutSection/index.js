import React from 'react';
import clsx from 'clsx';
import Link from '@docusaurus/Link';
import styles from './styles.module.css';

export default function AboutSection() {
  return (
    <div className="container padding-vert--xl">
      <div className="row">
        <div className="col col--5">
          <div style={{ paddingRight: '2rem' }}>
            <h2 className={styles.sectionTitle}>
              About HealthyPhases
            </h2>
            <p className={styles.sectionText}>
              The HealthyPhases Project promotes healthy aging through the semantic enrichment of solitude research (PHASES), creating standardized frameworks for understanding the relationship between solitude and gerotranscendence.
            </p>
            <p className={styles.sectionText}>
              Our multidisciplinary team brings together expertise in ontology development, psychology, 
              computer science, and gerontology to address challenges of terminological ambiguity and 
              data interoperability in solitude and aging research.
            </p>
            <Link
              className={clsx('button', styles.learnMoreButton)}
              style={{ color: '#0066cc' }}
              to="/docs/about/overview">
              Learn More
              <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={styles.arrowIcon}>
                <line x1="5" y1="12" x2="19" y2="12"></line>
                <polyline points="12 5 19 12 12 19"></polyline>
              </svg>
            </Link>
          </div>
        </div>
        <div className="col col--7">
          <div className="row">
            <div className="col col--12" style={{ marginBottom: '2rem' }}>
              <div className={styles.featureCard}>
                <div className={styles.featureIconContainer} style={{ backgroundColor: 'rgba(0, 102, 204, 0.1)' }}>
                  <svg xmlns="http://www.w3.org/2000/svg" width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#0066cc" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path>
                    <circle cx="9" cy="7" r="4"></circle>
                    <path d="M23 21v-2a4 4 0 0 0-3-3.87"></path>
                    <path d="M16 3.13a4 4 0 0 1 0 7.75"></path>
                  </svg>
                </div>
                <div className={styles.featureContent}>
                  <h3 className={styles.featureTitle} style={{ color: '#0066cc' }}>
                    Solitude Research
                  </h3>
                  <p className={styles.featureText}>
                    Clarifying the distinctions between solitude, loneliness, and social isolation
                    to better understand their effects on aging and well-being.
                  </p>
                </div>
              </div>
            </div>
            <div className="col col--12" style={{ marginBottom: '2rem' }}>
              <div className={styles.featureCard}>
                <div className={styles.featureIconContainer} style={{ backgroundColor: 'rgba(0, 102, 204, 0.1)' }}>
                  <svg xmlns="http://www.w3.org/2000/svg" width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#0066cc" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"></path>
                    <polyline points="9 22 9 12 15 12 15 22"></polyline>
                  </svg>
                </div>
                <div className={styles.featureContent}>
                  <h3 className={styles.featureTitle} style={{ color: '#0066cc' }}>
                    Gerotranscendence
                  </h3>
                  <p className={styles.featureText}>
                    Exploring the developmental shift in perspective that can occur in later life,
                    characterized by changes in relationship to self, others, and the universe.
                  </p>
                </div>
              </div>
            </div>
            <div className="col col--12">
              <div className={styles.featureCard}>
                <div className={styles.featureIconContainer} style={{ backgroundColor: 'rgba(0, 102, 204, 0.1)' }}>
                  <svg xmlns="http://www.w3.org/2000/svg" width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#0066cc" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <polygon points="12 2 2 7 12 12 22 7 12 2"></polygon>
                    <polyline points="2 17 12 22 22 17"></polyline>
                    <polyline points="2 12 12 17 22 12"></polyline>
                  </svg>
                </div>
                <div className={styles.featureContent}>
                  <h3 className={styles.featureTitle} style={{ color: '#0066cc' }}>
                    Semantic Enrichment
                  </h3>
                  <p className={styles.featureText}>
                    Developing standardized ontologies and knowledge graphs to enhance research data
                    and facilitate cross-domain integration and analysis.
                  </p>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
} 