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
  const { siteConfig } = useDocusaurusContext();

  // Video background logic
  const videoRef = React.useRef(null);

  React.useEffect(() => {
    if (videoRef.current) {
      console.log("Video element exists:", videoRef.current);
      videoRef.current.addEventListener('error', (e) => {
        console.error("Video load error:", e);
      });

      videoRef.current.addEventListener('loadeddata', () => {
        console.log("Video loaded successfully");
      });

      videoRef.current.style.pointerEvents = 'none';
    }

    // Ensure overlays don't block clicks
    const overlays = document.querySelectorAll('.videoOverlay, [class*="overlay"]');
    overlays.forEach(overlay => {
      if (overlay) overlay.style.pointerEvents = 'none';
    });

    // Make content elements clickable
    const contentElements = document.querySelectorAll('a, button, .button');
    contentElements.forEach(el => {
      if (el) el.style.pointerEvents = 'auto';
    });
  }, []);

  return (
    <header className={styles.heroBanner} style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', position: 'relative', overflow: 'hidden' }}>
      {/* Video Background */}
      <div style={{
        position: 'absolute',
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        width: '100%',
        height: '100%',
        overflow: 'hidden',
        zIndex: 0
      }}>
        <video
          ref={videoRef}
          autoPlay
          loop
          muted
          playsInline
          style={{
            position: 'absolute',
            top: '50%',
            left: '50%',
            minWidth: '100%',
            minHeight: '100%',
            width: 'auto',
            height: 'auto',
            transform: 'translate(-50%, -50%)',
            objectFit: 'cover'
          }}
        >
          <source src="/videos/HealthPhases-Video.mp4" type="video/mp4" />
        </video>

        {/* Video Overlay */}
        <div style={{
          position: 'absolute',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          width: '100%',
          height: '100%',
          backgroundColor: 'rgba(0, 0, 0, 0.4)',
          zIndex: 1
        }}></div>
      </div>

      <div className="container" style={{ width: '100%', position: 'relative', zIndex: 2 }}>
        <div style={{
          textAlign: 'center',
          padding: '4rem 0',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'center',
          minHeight: '80vh',
          pointerEvents: 'auto'
        }}>
          <h1 style={{
            fontSize: '3rem',
            fontWeight: '700',
            color: '#ffffff',
            margin: '0 0 1rem 0'
          }}>
            The HealthyPhases Project
          </h1>
          <p style={{
            fontSize: '1.25rem',
            maxWidth: '800px',
            margin: '0 auto 2rem auto',
            color: '#ffffff',
            lineHeight: '1.6'
          }}>
            Promoting Healthy Aging through Semantic Enrichment of Solitude Research
          </p>
          <div style={{
            display: 'flex',
            flexDirection: 'row',
            justifyContent: 'center',
            flexWrap: 'wrap',
            gap: '1rem',
            margin: '0 auto'
          }}>
            <a
              className="button button--lg"
              style={{
                backgroundColor: '#0066cc',
                borderColor: '#0066cc',
                color: 'white',
                padding: '0.75rem 1.5rem',
                fontWeight: '500',
                borderRadius: '4px',
                textDecoration: 'none',
                pointerEvents: 'auto',
                minWidth: '180px',
                textAlign: 'center',
                display: 'inline-block'
              }}
              href="/join">
              Join Our Research
            </a>
            <a
              className="button button--lg"
              style={{
                backgroundColor: 'rgba(255, 255, 255, 0.2)',
                borderColor: '#ffffff',
                color: '#ffffff',
                padding: '0.75rem 1.5rem',
                fontWeight: '500',
                borderRadius: '4px',
                textDecoration: 'none',
                pointerEvents: 'auto',
                minWidth: '180px',
                textAlign: 'center',
                display: 'inline-block'
              }}
              href="/docs/about/overview">
              Learn More
            </a>
          </div>
        </div>
      </div>
    </header>
  );
}

export default function Home() {
  const { siteConfig } = useDocusaurusContext();
  return (
    <Layout
      title={`Home`}
      description="HealthyPhases - Promoting Healthy Aging through Semantic Enrichment of Solitude Research"
      className="homepage">
      <HomepageHeader />

      {/* University Collaboration Banner */}
      <section style={{
        background: '#fff',
        padding: '2rem 0',
        borderBottom: '1px solid #eee',
        position: 'relative'
      }}>
        <div className="container">
          <div style={{ textAlign: 'center', marginBottom: '0.75rem' }}>
            <h3 style={{
              fontSize: '1.5rem',
              color: '#333',
              marginBottom: '0.5rem'
            }}>
              A Collaborative Research Initiative
            </h3>
            <p style={{
              fontSize: '1.1rem',
              color: '#555',
              maxWidth: '800px',
              margin: '0 auto 1rem auto'
            }}>
              To standardize and enrich data on solitude and gerotranscendence
            </p>
          </div>
          <div style={{
            display: 'flex',
            flexDirection: 'row',
            justifyContent: 'center',
            alignItems: 'center',
            flexWrap: 'wrap',
            gap: '2rem',
            margin: '0 auto'
          }}>
            <div style={{
              maxWidth: '250px',
              padding: '0.5rem',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center'
            }}>
              <img
                src="/img/university-at-buffalo-logo-horizontal.png"
                alt="University at Buffalo"
                style={{ width: '100%', height: 'auto' }}
              />
            </div>
            <div style={{
              maxWidth: '250px',
              padding: '0.5rem',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center'
            }}>
              <img
                src="/img/university-of-florida-logo-horizontal.png"
                alt="University of Florida"
                style={{ width: '100%', height: 'auto' }}
              />
            </div>
            <div style={{
              maxWidth: '250px',
              padding: '0.5rem',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center'
            }}>
              <img
                src="/img/university-of-michigan-logo-horizontal.png"
                alt="University of Michigan"
                style={{ width: '100%', height: 'auto' }}
              />
            </div>
            <div style={{
              maxWidth: '300px',
              padding: '0.5rem',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center'
            }}>
              <img
                src="/img/NIH-Logo.jpg"
                alt="National Institutes of Health"
                style={{ 
                  width: '100%', 
                  height: 'auto',
                  filter: 'brightness(1.1) contrast(1.05)'
                }}
              />
            </div>
          </div>
        </div>
      </section>

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
