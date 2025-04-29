import React from 'react';
import clsx from 'clsx';
import Link from '@docusaurus/Link';
import styles from './styles.module.css';

const PeopleList = [
  {
    name: 'Dr. John Beverley',
    title: 'Principal Investigator',
    initials: 'JB',
    image: '/img/team/john_beverley.jpeg',
    affiliation: 'University at Buffalo',
    profileLink: '#',
  },
  {
    name: 'Dr. Bill Duncan',
    title: 'Principal Investigator',
    initials: 'BD',
    image: '/img/team/bill_duncan.jpeg',
    affiliation: 'University of Florida',
    profileLink: '#',
  },
  {
    name: 'Dr. Hollen Reischer',
    title: 'Subject Matter Expert',
    initials: 'HR',
    image: '/img/team/hollen_reischer.jpeg',
    affiliation: 'University at Buffalo',
    profileLink: '#',
  },
  {
    name: 'Dr. Julie Bowker',
    title: 'Subject Matter Expert',
    initials: 'JB',
    image: '/img/team/julie_bowker.jpeg',
    affiliation: 'University at Buffalo',
    profileLink: '#',
  },
  {
    name: 'Dr. Oliver He',
    title: 'UM Lead',
    initials: 'OH',
    image: '/img/team/oliver_he.jpeg',
    affiliation: 'University of Michigan',
    profileLink: '#',
  },
  {
    name: 'Dr. Damayanthi Jesudas',
    title: 'Post-Doctoral Researcher',
    initials: 'DJ',
    image: '/img/team/damayanthi_jesudas.jpeg',
    affiliation: 'University at Buffalo',
    profileLink: '#',
  },
];

function PersonCard({name, title, initials, image, affiliation, profileLink}) {
  return (
    <div className={styles.personCard}>
      {image ? (
        <div className={styles.avatarImage}>
          <img src={image} alt={`${name} profile`} />
        </div>
      ) : (
        <div className={styles.avatarCircle}>
          {initials}
        </div>
      )}
      <h3 className={styles.personName}>{name}</h3>
      <div className={styles.personTitle}>{title}</div>
      <div className={styles.personAffiliation}>{affiliation}</div>
      <Link to={profileLink} className={styles.viewProfileLink}>
        View Profile <span style={{ marginLeft: '4px' }}>→</span>
      </Link>
    </div>
  );
}

export default function PeopleSection() {
  return (
    <section className={styles.peopleSection}>
      <div className="container">
        <div className={styles.sectionHeader}>
          <h2 className={styles.sectionTitle}>
            Research <span className={styles.highlight}>Team</span>
          </h2>
          <p className={styles.sectionDescription}>
            Our multidisciplinary team brings together expertise in ontology, psychology, computer science, and gerontology
          </p>
        </div>
        
        <div className={styles.peopleGrid}>
          {PeopleList.map((props, idx) => (
            <PersonCard key={idx} {...props} />
          ))}
        </div>
        
        <div className={styles.joinSection}>
          <div className={styles.joinContent}>
            <h3 className={styles.joinTitle}>Join Our Research</h3>
            <p className={styles.joinDescription}>
              Interested in participating in the HealthPhases Project? We welcome 
              collaborators, students, and volunteers to help advance our 
              understanding of solitude and healthy aging.
            </p>
          </div>
          <div className={styles.joinButtons}>
            <Link className={styles.button} to="/join">
              Get Involved
            </Link>
          </div>
        </div>
      </div>
    </section>
  );
} 