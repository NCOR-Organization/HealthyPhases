import React, { useState } from 'react';
import Link from '@docusaurus/Link';
import styles from './styles.module.css';
import clsx from 'clsx';

export default function EventsSection() {
  const [activeTab, setActiveTab] = useState('upcoming');
  
  // Sample event data for HealthPhases
  const upcomingEvents = [
    {
      id: 1,
      title: 'Consensus-Building Workshop on Solitude Terminology',
      description: 'A two-day workshop bringing together experts in psychology, gerontology, and ontology to develop consensus definitions for key terms in solitude research.',
      date: 'September 15-16, 2023',
      location: 'University at Buffalo, NY',
      url: '/docs/events/workshops'
    },
    {
      id: 2,
      title: 'Ontology Tutorial at GSA Annual Scientific Meeting',
      description: 'A hands-on tutorial introducing gerontology researchers to ontological approaches for standardizing research data.',
      date: 'November 8, 2023',
      location: 'Tampa, FL',
      url: '/docs/events/workshops'
    },
    {
      id: 3,
      title: 'Knowledge Graph Workshop for Aging Research',
      description: 'Learn how to use knowledge graphs to enhance research on aging, solitude, and well-being with semantic technologies.',
      date: 'January 20, 2024',
      location: 'Virtual',
      url: '/docs/events/workshops'
    }
  ];
  
  const pastEvents = [
    {
      id: 4,
      title: 'Project Launch Symposium',
      description: 'The official launch of the HealthPhases Project, featuring presentations from the principal investigators and demonstrations of initial ontology prototypes.',
      date: 'March 10, 2023',
      location: 'Virtual',
      url: '/docs/events/workshops'
    },
    {
      id: 5,
      title: 'Solitude & Gerotranscendence Research Forum',
      description: 'A collaborative forum exploring the connections and distinctions between solitude and gerotranscendence in aging research.',
      date: 'April 15, 2023',
      location: 'University of Florida, Gainesville',
      url: '/docs/events/workshops'
    },
    {
      id: 6,
      title: 'Ontology Framework Development Workshop',
      description: 'A hands-on workshop for developing the initial framework for the solitude and gerotranscendence ontologies.',
      date: 'May 22, 2023',
      location: 'University of Michigan, Ann Arbor',
      url: '/docs/events/workshops'
    }
  ];
  
  // Display events based on active tab
  const displayedEvents = activeTab === 'upcoming' ? upcomingEvents : pastEvents;

  return (
    <div className={styles.eventsContainer}>
      <div className="container">
        <div className={styles.headerRow}>
          <div className={styles.headerContent}>
            <h2 className={styles.sectionTitle}>
              Workshops & <span className={styles.highlight}>Events</span>
            </h2>
            <p className={styles.sectionDescription}>
              Engage with our research community through workshops, conferences, and collaborative events
              focused on solitude, aging, and semantic technologies.
            </p>
          </div>
          <div className={styles.allEventsLink}>
            <Link to="/docs/events/workshops" className={styles.viewAllLink}>
              All Events
              <svg
                width="20"
                height="20"
                viewBox="0 0 24 24"
                fill="none"
                xmlns="http://www.w3.org/2000/svg"
                className={styles.arrowIcon}
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
        
        <div className={styles.tabContainer}>
          <button 
            className={clsx(styles.tabButton, activeTab === 'upcoming' && styles.activeTab)}
            onClick={() => setActiveTab('upcoming')}
          >
            Upcoming Events
          </button>
          <button 
            className={clsx(styles.tabButton, activeTab === 'past' && styles.activeTab)}
            onClick={() => setActiveTab('past')}
          >
            Past Events
          </button>
        </div>
        
        <div className={styles.eventsGrid}>
          {displayedEvents.map((event) => (
            <div key={event.id} className={styles.eventCard}>
              <div className={styles.eventContent}>
                <div className={styles.eventHeader}>
                  <h3 className={styles.eventTitle}>{event.title}</h3>
                  <span className={styles.eventType}>Workshop</span>
                </div>
                <p className={styles.eventDescription}>{event.description}</p>
                <div className={styles.eventMeta}>
                  <div className={styles.eventDate}>
                    <svg 
                      xmlns="http://www.w3.org/2000/svg" 
                      width="16" 
                      height="16" 
                      viewBox="0 0 24 24" 
                      fill="none" 
                      stroke="currentColor" 
                      strokeWidth="2" 
                      strokeLinecap="round" 
                      strokeLinejoin="round"
                      className={styles.metaIcon}
                    >
                      <rect x="3" y="4" width="18" height="18" rx="2" ry="2"></rect>
                      <line x1="16" y1="2" x2="16" y2="6"></line>
                      <line x1="8" y1="2" x2="8" y2="6"></line>
                      <line x1="3" y1="10" x2="21" y2="10"></line>
                    </svg>
                    {event.date}
                  </div>
                  <div className={styles.eventLocation}>
                    <svg 
                      xmlns="http://www.w3.org/2000/svg" 
                      width="16" 
                      height="16" 
                      viewBox="0 0 24 24" 
                      fill="none" 
                      stroke="currentColor" 
                      strokeWidth="2" 
                      strokeLinecap="round" 
                      strokeLinejoin="round"
                      className={styles.metaIcon}
                    >
                      <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"></path>
                      <circle cx="12" cy="10" r="3"></circle>
                    </svg>
                    {event.location}
                  </div>
                </div>
              </div>
              <div className={styles.eventFooter}>
                <Link to={event.url} className={styles.viewDetailsLink}>
                  View Details
                  <svg
                    width="16"
                    height="16"
                    viewBox="0 0 24 24"
                    fill="none"
                    xmlns="http://www.w3.org/2000/svg"
                    className={styles.detailsArrow}
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
          ))}
        </div>
      </div>
    </div>
  );
} 