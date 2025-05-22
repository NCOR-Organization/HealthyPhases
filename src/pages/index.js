import React from 'react';
import clsx from 'clsx';
import Link from '@docusaurus/Link';
import useDocusaurusContext from '@docusaurus/useDocusaurusContext';
import Layout from '@theme/Layout';
import Heading from '@theme/Heading';

// Import the new component
import AboutSection from '@site/src/components/AboutSection';
import PeopleSection from '@site/src/components/PeopleSection';
import ResearchAreasSection from '@site/src/components/ResearchAreasSection';
import EventsSection from '@site/src/components/EventsSection';
import FeaturedVideosSection from '@site/src/components/FeaturedVideosSection';

import styles from './styles.module.css';

function HomepageHeader() {
  const {siteConfig} = useDocusaurusContext();
  return (
    <header className={styles.heroBanner} style={{ minHeight: '100vh', display: 'flex', alignItems: 'center' }}>
      {/* Background */}
      <div style={{ 
        position: 'absolute', 
        top: 0, 
        left: 0, 
        right: 0, 
        bottom: 0,
        background: 'linear-gradient(135deg, #e6f7ff 0%, #ffffff 100%)',
        zIndex: 0
      }}>
        {/* Light grid texture overlay */}
        <div style={{
          position: 'absolute',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          backgroundImage: 'linear-gradient(rgba(220, 220, 220, 0.5) 1px, transparent 1px), linear-gradient(90deg, rgba(220, 220, 220, 0.5) 1px, transparent 1px)',
          backgroundSize: '20px 20px',
          opacity: 0.6
        }} />
        
        {/* SVG with research and aging-related graphics */}
        <svg width="100%" height="100%" viewBox="0 0 1200 800" xmlns="http://www.w3.org/2000/svg">
          {/* Frame border */}
          <rect x="40" y="40" width="1120" height="720" fill="none" stroke="#0066cc" strokeWidth="3" strokeDasharray="2,2" opacity="0.3" />
          <rect x="50" y="50" width="1100" height="700" fill="none" stroke="#0066cc" strokeWidth="1" opacity="0.3" />
          
          {/* Research nodes and connections */}
          <g transform="translate(600, 400)">
            <circle cx="-250" cy="-150" r="40" fill="none" stroke="#0066cc" strokeWidth="1.5" opacity="0.5" />
            <text x="-250" y="-145" textAnchor="middle" fill="#0066cc" opacity="0.7" fontSize="12">Solitude</text>
            
            <circle cx="250" cy="-150" r="40" fill="none" stroke="#0066cc" strokeWidth="1.5" opacity="0.5" />
            <text x="250" y="-145" textAnchor="middle" fill="#0066cc" opacity="0.7" fontSize="12">Gerotranscendence</text>
            
            <circle cx="0" cy="50" r="60" fill="none" stroke="#0066cc" strokeWidth="1.5" opacity="0.5" />
            <text x="0" y="55" textAnchor="middle" fill="#0066cc" opacity="0.7" fontSize="12">Semantic Enrichment</text>
            
            <circle cx="-180" cy="150" r="40" fill="none" stroke="#0066cc" strokeWidth="1.5" opacity="0.5" />
            <text x="-180" y="155" textAnchor="middle" fill="#0066cc" opacity="0.7" fontSize="12">Ontology</text>
            
            <circle cx="180" cy="150" r="40" fill="none" stroke="#0066cc" strokeWidth="1.5" opacity="0.5" />
            <text x="180" y="155" textAnchor="middle" fill="#0066cc" opacity="0.7" fontSize="12">Knowledge Graph</text>
            
            {/* Connection lines */}
            <line x1="-250" y1="-150" x2="0" y2="50" stroke="#0066cc" strokeWidth="1" opacity="0.3" />
            <line x1="250" y1="-150" x2="0" y2="50" stroke="#0066cc" strokeWidth="1" opacity="0.3" />
            <line x1="0" y1="50" x2="-180" y2="150" stroke="#0066cc" strokeWidth="1" opacity="0.3" />
            <line x1="0" y1="50" x2="180" y2="150" stroke="#0066cc" strokeWidth="1" opacity="0.3" />
            <line x1="-250" y1="-150" x2="250" y2="-150" stroke="#0066cc" strokeWidth="1" opacity="0.3" />
            <line x1="-180" y1="150" x2="180" y2="150" stroke="#0066cc" strokeWidth="1" opacity="0.3" />
            
            {/* Animation */}
            <circle cx="0" cy="0" r="120" fill="none" stroke="#0066cc" strokeWidth="1" opacity="0.3">
              <animate 
                attributeName="r" 
                values="120;150;120" 
                dur="10s" 
                repeatCount="indefinite" 
              />
              <animate 
                attributeName="opacity" 
                values="0.3;0.5;0.3" 
                dur="10s" 
                repeatCount="indefinite" 
              />
            </circle>
          </g>
          
          {/* Corner decorations */}
          <path d="M80,80 C100,60 120,60 140,80 C120,100 120,120 140,140 C100,120 80,120 60,140 C80,100 60,80 80,80" fill="none" stroke="#0066cc" strokeWidth="1" opacity="0.4" />
          <path d="M1120,80 C1100,60 1080,60 1060,80 C1080,100 1080,120 1060,140 C1100,120 1120,120 1140,140 C1120,100 1140,80 1120,80" fill="none" stroke="#0066cc" strokeWidth="1" opacity="0.4" />
          <path d="M80,720 C100,740 120,740 140,720 C120,700 120,680 140,660 C100,680 80,680 60,660 C80,700 60,720 80,720" fill="none" stroke="#0066cc" strokeWidth="1" opacity="0.4" />
          <path d="M1120,720 C1100,740 1080,740 1060,720 C1080,700 1080,680 1060,660 C1100,680 1120,680 1140,660 C1120,700 1140,720 1120,720" fill="none" stroke="#0066cc" strokeWidth="1" opacity="0.4" />
        </svg>

        {/* Gradient overlay */}
        <div style={{
          position: 'absolute',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          background: 'linear-gradient(135deg, rgba(255,255,255,0.7) 0%, rgba(255,255,255,0.2) 100%)',
          zIndex: 1
        }} />
      </div>

      <div className="container" style={{ width: '100%' }}>
        <div style={{ 
          position: 'relative', 
          zIndex: 2, 
          textAlign: 'center', 
          padding: '4rem 0',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'center',
          minHeight: '80vh'
        }}>
          <h1 style={{ 
            fontSize: '3rem', 
            fontWeight: '700', 
            color: '#0066cc', 
            margin: '0 0 1rem 0' 
          }}>
            The HealthyPhases Project
          </h1>
          <p style={{ 
            fontSize: '1.25rem', 
            maxWidth: '800px', 
            margin: '0 auto 1rem auto', 
            color: '#333333', 
            lineHeight: '1.6' 
          }}>
            Promoting Healthy Aging through Semantic Enrichment of Solitude Research
          </p>
          <p style={{ 
            fontSize: '1.25rem', 
            maxWidth: '800px', 
            margin: '0 auto 2rem auto', 
            color: '#333333', 
            lineHeight: '1.6' 
          }}>
            A collaborative research initiative to standardize and enrich data on solitude and gerotranscendence
          </p>
          <div>
            <a
              className="button button--lg"
              style={{ 
                backgroundColor: '#0066cc', 
                borderColor: '#0066cc',
                color: 'white',
                margin: '0 0.75rem',
                padding: '0.75rem 1.5rem',
                fontWeight: '500',
                borderRadius: '4px',
                textDecoration: 'none'
              }}
              href="/join">
              Join Our Research
            </a>
            <a
              className="button button--lg"
              style={{ 
                backgroundColor: 'transparent',
                borderColor: '#0066cc',
                color: '#0066cc',
                margin: '0 0.75rem',
                padding: '0.75rem 1.5rem',
                fontWeight: '500',
                borderRadius: '4px',
                textDecoration: 'none'
              }}
              href="/docs/get-started">
              Learn More
            </a>
          </div>
        </div>
      </div>
    </header>
  );
}

export default function Home() {
  const {siteConfig} = useDocusaurusContext();
  return (
    <Layout
      title={`${siteConfig.title}`}
      description="HealthyPhases - Promoting Healthy Aging through Semantic Enrichment of Solitude Research"
      className="homepage">
      <HomepageHeader />
      
      {/* About Section */}
      <section style={{ 
        background: '#fff',
        padding: '60px 0', 
        borderBottom: '1px solid #eee',
        position: 'relative'
      }}>
        <AboutSection />
      </section>
      
      {/* Research Areas Section */}
      <ResearchAreasSection />
      
      {/* The rest of your page content */}
      <main>
      </main>
    </Layout>
  );
}
