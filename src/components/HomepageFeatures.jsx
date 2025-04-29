import React from 'react';
import styles from './HomepageFeatures.module.css';

// Using color backgrounds instead of images since the image files don't exist yet
const FeatureList = [
  {
    title: 'Ontology Development',
    bgColor: '#e6f7ff',
    iconColor: '#0066cc',
    description: 'Creating standardized vocabulary and semantic frameworks to precisely define terms and relationships in solitude and gerotranscendence research.',
    url: '/docs/research/ontology-development'
  },
  {
    title: 'Common Data Model',
    bgColor: '#e6f7ff',
    iconColor: '#0066cc',
    description: 'Developing a standardized structure for collecting, representing, and sharing data related to solitude and gerotranscendence.',
    url: '/wiki/common-data-model'
  },
  {
    title: 'Semantic Enrichment',
    bgColor: '#e6f7ff',
    iconColor: '#0066cc',
    description: 'Enhancing research data with structured, machine-interpretable annotations to enable more sophisticated analysis and integration.',
    url: '/wiki/semantic-enrichment'
  },
  {
    title: 'Knowledge Graphs',
    bgColor: '#e6f7ff',
    iconColor: '#0066cc',
    description: 'Building semantic networks to represent the complex relationships between concepts in solitude and aging research.',
    url: '/wiki/knowledge-graph'
  },
  {
    title: 'Solitude Research',
    bgColor: '#e6f7ff',
    iconColor: '#0066cc',
    description: 'Investigating the distinct experiences of solitude, loneliness, and social isolation and their impacts on aging and well-being.',
    url: '/docs/about/background#understanding-solitude'
  },
  {
    title: 'Gerotranscendence',
    bgColor: '#e6f7ff',
    iconColor: '#0066cc',
    description: 'Exploring the developmental shift in perspective that can occur in later life, characterized by changes in values and cosmic awareness.',
    url: '/docs/about/background#understanding-gerotranscendence'
  }
];

function FeatureCard({title, bgColor, iconColor, description, url}) {
  const cardClassName = title.toLowerCase().replace(/\s+/g, '-') + '-card';
  
  // Use a color background instead of an image
  const headerStyle = {
    height: '160px',
    backgroundColor: bgColor,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: '8px 8px 0 0',
    position: 'relative',
    overflow: 'hidden'
  };
  
  // Icon placeholder
  const iconStyle = {
    fontSize: '60px',
    color: iconColor,
    opacity: 0.2
  };
  
  // Blue button styles
  const buttonStyle = {
    backgroundColor: '#0066cc',
    borderColor: '#0066cc',
    color: 'white'
  };
  
  return (
    <div className="card margin-bottom--lg" style={{height: '100%', display: 'flex', flexDirection: 'column'}}>
      <div style={headerStyle}>
        <div style={iconStyle}>
          {title === 'Ontology Development' && '💡'}
          {title === 'Common Data Model' && '📊'}
          {title === 'Semantic Enrichment' && '🔍'}
          {title === 'Knowledge Graphs' && '🕸️'}
          {title === 'Solitude Research' && '🧠'}
          {title === 'Gerotranscendence' && '⏳'}
        </div>
      </div>
      <div className="card-content padding--lg" style={{flex: 1, display: 'flex', flexDirection: 'column'}}>
        <h3>{title}</h3>
        <p style={{flex: 1}}>{description}</p>
        
        <div className="card-actions" style={{marginTop: '1rem'}}>
          <a 
            href={url} 
            className="button button--primary button--sm" 
            style={buttonStyle}
            target="_blank" 
            rel="noopener noreferrer"
          >
            Learn More
          </a>
        </div>
      </div>
    </div>
  );
}

export default function HomepageFeatures() {
  return (
    <section className={styles.features}>
      <div className="container">
        <div className={styles.sectionHeader}>
          <h2 className={styles.sectionTitle}>
            Project <span className={styles.highlight}>Components</span>
          </h2>
          <p className={styles.sectionDescription}>
            The HealthPhases Project bridges isolated research areas by creating semantic frameworks, data models, and knowledge resources
          </p>
        </div>
        
        <div className="row">
          {FeatureList.map((props, idx) => (
            <div key={idx} className="col col--4 margin-bottom--xl">
              <FeatureCard {...props} />
            </div>
          ))}
        </div>
      </div>
    </section>
  );
} 