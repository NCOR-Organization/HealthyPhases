import React, { useState, useRef } from 'react';
import Layout from '@theme/Layout';
import Link from '@docusaurus/Link';
import clsx from 'clsx';
import styles from './join.module.css';

function JoinPage() {
  const [formData, setFormData] = useState({
    firstName: '',
    lastName: '',
    email: '',
    organization: '',
    role: '',
    participationType: 'researcher',
    interests: [],
    message: '',
  });
  
  const [formStatus, setFormStatus] = useState({
    submitted: false,
    success: false,
    error: null,
  });
  
  const [isSubmitting, setIsSubmitting] = useState(false);
  const formRef = useRef(null);
  
  // Available interests checkboxes
  const interestOptions = [
    'Solitude Research',
    'Gerotranscendence',
    'Ontology Development',
    'Aging Studies',
    'Semantic Technologies',
    'Data Integration',
    'Psychology',
    'Gerontology',
  ];
  
  // Role options for the dropdown
  const roleOptions = [
    'Professor/Academic Researcher',
    'Graduate Student',
    'Postdoctoral Researcher',
    'Psychologist',
    'Gerontologist',
    'Data Scientist',
    'Ontology Engineer',
    'Software Developer',
    'Healthcare Professional',
    'Social Worker',
    'Government Researcher',
    'Industry Researcher',
    'Other'
  ];
  
  const handleChange = (e) => {
    const { name, value } = e.target;
    setFormData({
      ...formData,
      [name]: value,
    });
  };
  
  const handleCheckbox = (e) => {
    const { value, checked } = e.target;
    if (checked) {
      setFormData({
        ...formData,
        interests: [...formData.interests, value],
      });
    } else {
      setFormData({
        ...formData,
        interests: formData.interests.filter(interest => interest !== value),
      });
    }
  };
  
  const handleSubmit = async (e) => {
    e.preventDefault();
    setIsSubmitting(true);
    
    try {
      // Format the email body with all form data
      const emailBody = `
        New HealthPhases Project Participation Request
        
        Name: ${formData.firstName} ${formData.lastName}
        Email: ${formData.email}
        Organization: ${formData.organization || 'Not provided'}
        Role: ${formData.role || 'Not provided'}
        Participation Type: ${formData.participationType === 'researcher' ? 'Researcher' : formData.participationType === 'volunteer' ? 'Volunteer' : 'Student'}
        
        Interests:
        ${formData.interests.length > 0 ? formData.interests.join(', ') : 'None selected'}
        
        Additional Information:
        ${formData.message || 'None provided'}
      `;
      
      // Using EmailJS to send the form (you'll need to set this up)
      // Replace with your own EmailJS credentials
      const response = await emailjs.send(
        'YOUR_SERVICE_ID', // Create an EmailJS account and get these values
        'YOUR_TEMPLATE_ID',
        {
          to_email: 'jcb26@buffalo.edu',
          from_name: `${formData.firstName} ${formData.lastName}`,
          from_email: formData.email,
          message: emailBody,
          subject: `HealthPhases Project Interest: ${formData.firstName} ${formData.lastName}`,
        },
        'YOUR_USER_ID'
      );
      
      if (response.status === 200) {
        setFormStatus({
          submitted: true,
          success: true,
          error: null,
        });
        formRef.current.reset();
        setFormData({
          firstName: '',
          lastName: '',
          email: '',
          organization: '',
          role: '',
          participationType: 'researcher',
          interests: [],
          message: '',
        });
      } else {
        throw new Error('Failed to send email');
      }
    } catch (error) {
      console.error('Error submitting form:', error);
      setFormStatus({
        submitted: true,
        success: false,
        error: 'There was a problem submitting your application. Please try again or contact us directly at jcb26@buffalo.edu.',
      });
    } finally {
      setIsSubmitting(false);
    }
  };
  
  return (
    <Layout
      title="Join the HealthPhases Project"
      description="Join the HealthPhases Project to collaborate on research promoting healthy aging through semantic enrichment of solitude research"
    >
      <div className={styles.joinHero}>
        <div className="container">
          <div className="row">
            <div className="col col--8 col--offset-2">
              <h1 className={styles.heroTitle}>Join Our Research</h1>
              <div className={styles.heroLine}></div>
              <p className={styles.heroSubtitle}>
                Participate in the HealthPhases Project to advance research on solitude and healthy aging
              </p>
            </div>
          </div>
        </div>
      </div>
      
      <div className="container margin-top--xl margin-bottom--xl">
        <div className="row">
          <div className="col col--10 col--offset-1">
            <div className={styles.benefitsCard}>
              <div className={styles.benefitsHeader}>
                <div className={styles.benefitsIcon}>
                  <svg width="28" height="28" viewBox="0 0 24 24" fill="currentColor">
                    <path d="M16 11c1.66 0 2.99-1.34 2.99-3S17.66 5 16 5s-3 1.34-3 3 1.34 3 3 3zm-8 0c1.66 0 2.99-1.34 2.99-3S9.66 5 8 5 5 6.34 5 8s1.34 3 3 3zm0 2c-2.33 0-7 1.17-7 3.5V19h14v-2.5c0-2.33-4.67-3.5-7-3.5zm8 0c-.29 0-.62.02-.97.05 1.16.84 1.97 1.97 1.97 3.45V19h6v-2.5c0-2.33-4.67-3.5-7-3.5z" />
                  </svg>
                </div>
                <h2>Ways to Participate</h2>
              </div>
              <div className={styles.benefitsGrid}>
                <div className={styles.benefitItem}>
                  <div className={styles.benefitIcon}>
                    <svg width="24" height="24" viewBox="0 0 24 24" fill="currentColor">
                      <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 17.93c-3.95-.49-7-3.85-7-7.93 0-.62.08-1.21.21-1.79L9 15v1c0 1.1.9 2 2 2v1.93zm6.9-2.54c-.26-.81-1-1.39-1.9-1.39h-1v-3c0-.55-.45-1-1-1H8v-2h2c.55 0 1-.45 1-1V7h2c1.1 0 2-.9 2-2v-.41c2.93 1.19 5 4.06 5 7.41 0 2.08-.8 3.97-2.1 5.39z" />
                    </svg>
                  </div>
                  <h3>Research Collaboration</h3>
                  <p>Partner with our team on research projects related to solitude, gerotranscendence, and semantic technologies</p>
                </div>
                <div className={styles.benefitItem}>
                  <div className={styles.benefitIcon}>
                    <svg width="24" height="24" viewBox="0 0 24 24" fill="currentColor">
                      <path d="M21 5c-1.11-.35-2.33-.5-3.5-.5-1.95 0-4.05.4-5.5 1.5-1.45-1.1-3.55-1.5-5.5-1.5S2.45 4.9 1 6v14.65c0 .25.25.5.5.5.1 0 .15-.05.25-.05C3.1 20.45 5.05 20 6.5 20c1.95 0 4.05.4 5.5 1.5 1.35-.85 3.8-1.5 5.5-1.5 1.65 0 3.35.3 4.75 1.05.1.05.15.05.25.05.25 0 .5-.25.5-.5V6c-.6-.45-1.25-.75-2-1zm0 13.5c-1.1-.35-2.3-.5-3.5-.5-1.7 0-4.15.65-5.5 1.5V8c1.35-.85 3.8-1.5 5.5-1.5 1.2 0 2.4.15 3.5.5v11.5z" />
                    </svg>
                  </div>
                  <h3>Data Sharing</h3>
                  <p>Contribute to our data repository by sharing datasets or participating in standardization efforts</p>
                </div>
                <div className={styles.benefitItem}>
                  <div className={styles.benefitIcon}>
                    <svg width="24" height="24" viewBox="0 0 24 24" fill="currentColor">
                      <path d="M16 11c1.66 0 2.99-1.34 2.99-3S17.66 5 16 5c-1.66 0-3 1.34-3 3s1.34 3 3 3zm-8 0c1.66 0 2.99-1.34 2.99-3S9.66 5 8 5C6.34 5 5 6.34 5 8s1.34 3 3 3zm0 2c-2.33 0-7 1.17-7 3.5V19h14v-2.5c0-2.33-4.67-3.5-7-3.5zm8 0c-.29 0-.62.02-.97.05 1.16.84 1.97 1.97 1.97 3.45V19h6v-2.5c0-2.33-4.67-3.5-7-3.5z" />
                    </svg>
                  </div>
                  <h3>Workshop Participation</h3>
                  <p>Attend or help facilitate workshops on consensus-building, ontology development, and research methods</p>
                </div>
                <div className={styles.benefitItem}>
                  <div className={styles.benefitIcon}>
                    <svg width="24" height="24" viewBox="0 0 24 24" fill="currentColor">
                      <path d="M12 1L3 5v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V5l-9-4zm0 10.99h7c-.53 4.12-3.28 7.79-7 8.94V12H5V6.3l7-3.11v8.8z" />
                    </svg>
                  </div>
                  <h3>Student Involvement</h3>
                  <p>Opportunities for graduate and undergraduate students to engage in research projects and gain experience</p>
                </div>
                <div className={styles.benefitItem}>
                  <div className={styles.benefitIcon}>
                    <svg width="24" height="24" viewBox="0 0 24 24" fill="currentColor">
                      <path d="M11.8 10.9c-2.27-.59-3-1.2-3-2.15 0-1.09 1.01-1.85 2.7-1.85 1.78 0 2.44.85 2.5 2.1h2.21c-.07-1.72-1.12-3.3-3.21-3.81V3h-3v2.16c-1.94.42-3.5 1.68-3.5 3.61 0 2.31 1.91 3.46 4.7 4.13 2.5.6 3 1.48 3 2.41 0 .69-.49 1.79-2.7 1.79-2.06 0-2.87-.92-2.98-2.1h-2.2c.12 2.19 1.76 3.42 3.68 3.83V21h3v-2.15c1.95-.37 3.5-1.5 3.5-3.55 0-2.84-2.43-3.81-4.7-4.4z"/>
                    </svg>
                  </div>
                  <h3>Resource Access</h3>
                  <p>Access to ontologies, data models, and semantic tools developed through the project</p>
                </div>
                <div className={styles.benefitItem}>
                  <div className={styles.benefitIcon}>
                    <svg width="24" height="24" viewBox="0 0 24 24" fill="currentColor">
                      <path d="M19 3H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm-5 14h-2V9h-2V7h4v10z"/>
                    </svg>
                  </div>
                  <h3>Volunteer Opportunities</h3>
                  <p>Help with data annotation, literature review, or community outreach activities</p>
                </div>
              </div>
            </div>
          
            {formStatus.submitted && formStatus.success ? (
              <div className={styles.successCard}>
                <div className={styles.successIcon}>
                  <svg width="64" height="64" viewBox="0 0 24 24" fill="currentColor">
                    <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z" />
                  </svg>
                </div>
                <h2>Thank You For Your Interest!</h2>
                <p>
                  We've received your application to participate in the HealthPhases Project and will be in touch soon. 
                  In the meantime, feel free to explore our resources or learn more about our research aims.
                </p>
                <div className={styles.successButtons}>
                  <Link 
                    to="/docs/get-started" 
                    className={styles.primaryButton}
                  >
                    Explore Resources
                  </Link>
                  <Link 
                    to="/docs/research/aims" 
                    className={styles.secondaryButton}
                  >
                    Research Aims
                  </Link>
                </div>
              </div>
            ) : (
              <div className={styles.formCard}>
                <div className={styles.formHeader}>
                  <h2>Participation Request</h2>
                  <p>Complete the form below to express interest in participating in the HealthPhases Project</p>
                </div>
                
                <div className={styles.formBody}>
                  {formStatus.error && (
                    <div className={styles.errorMessage}>
                      <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
                        <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z" />
                      </svg>
                      {formStatus.error}
                    </div>
                  )}
                  
                  <form ref={formRef} onSubmit={handleSubmit}>
                    <div className={styles.formGrid}>
                      <div className={styles.formField}>
                        <label htmlFor="firstName">
                          <strong>First Name</strong> <span className={styles.required}>*</span>
                        </label>
                        <input
                          id="firstName"
                          name="firstName"
                          type="text"
                          className={styles.formInput}
                          value={formData.firstName}
                          onChange={handleChange}
                          required
                        />
                      </div>
                      
                      <div className={styles.formField}>
                        <label htmlFor="lastName">
                          <strong>Last Name</strong> <span className={styles.required}>*</span>
                        </label>
                        <input
                          id="lastName"
                          name="lastName"
                          type="text"
                          className={styles.formInput}
                          value={formData.lastName}
                          onChange={handleChange}
                          required
                        />
                      </div>
                    </div>
                    
                    <div className={styles.formField}>
                      <label htmlFor="email">
                        <strong>Email Address</strong> <span className={styles.required}>*</span>
                      </label>
                      <input
                        id="email"
                        name="email"
                        type="email"
                        className={styles.formInput}
                        value={formData.email}
                        onChange={handleChange}
                        required
                      />
                    </div>
                    
                    <div className={styles.formField}>
                      <label htmlFor="organization">
                        <strong>Organization</strong>
                      </label>
                      <input
                        id="organization"
                        name="organization"
                        type="text"
                        className={styles.formInput}
                        value={formData.organization}
                        onChange={handleChange}
                        placeholder="University, Company, or Institution"
                      />
                    </div>
                    
                    <div className={styles.formField}>
                      <label htmlFor="role">
                        <strong>Role</strong> <span className={styles.required}>*</span>
                      </label>
                      <select
                        id="role"
                        name="role"
                        className={styles.formSelect}
                        value={formData.role}
                        onChange={handleChange}
                        required
                      >
                        <option value="" disabled>Select your role</option>
                        {roleOptions.map(option => (
                          <option key={option} value={option}>{option}</option>
                        ))}
                      </select>
                    </div>
                    
                    <div className={styles.formField}>
                      <p><strong>How Would You Like to Participate?</strong> <span className={styles.required}>*</span></p>
                      <div className={styles.radioGroup}>
                        <div className={styles.radioOption}>
                          <input
                            type="radio"
                            id="participation-researcher"
                            name="participationType"
                            value="researcher"
                            checked={formData.participationType === 'researcher'}
                            onChange={handleChange}
                            required
                          />
                          <label htmlFor="participation-researcher">
                            <span className={styles.radioButton}></span>
                            Research Collaborator
                          </label>
                        </div>
                        <div className={styles.radioOption}>
                          <input
                            type="radio"
                            id="participation-volunteer"
                            name="participationType"
                            value="volunteer"
                            checked={formData.participationType === 'volunteer'}
                            onChange={handleChange}
                          />
                          <label htmlFor="participation-volunteer">
                            <span className={styles.radioButton}></span>
                            Volunteer
                          </label>
                        </div>
                        <div className={styles.radioOption}>
                          <input
                            type="radio"
                            id="participation-student"
                            name="participationType"
                            value="student"
                            checked={formData.participationType === 'student'}
                            onChange={handleChange}
                          />
                          <label htmlFor="participation-student">
                            <span className={styles.radioButton}></span>
                            Student Researcher
                          </label>
                        </div>
                      </div>
                    </div>
                    
                    <div className={styles.formField}>
                      <p><strong>Areas of Interest</strong> (select all that apply)</p>
                      <div className={styles.checkboxGrid}>
                        {interestOptions.map(option => (
                          <div key={option} className={styles.checkboxOption}>
                            <input
                              type="checkbox"
                              id={option.replace(/\s+/g, '-').toLowerCase()}
                              name="interests"
                              value={option}
                              onChange={handleCheckbox}
                              checked={formData.interests.includes(option)}
                            />
                            <label htmlFor={option.replace(/\s+/g, '-').toLowerCase()}>
                              <span className={styles.checkbox}></span>
                              {option}
                            </label>
                          </div>
                        ))}
                      </div>
                    </div>
                    
                    <div className={styles.formField}>
                      <label htmlFor="message">
                        <strong>Additional Information</strong>
                      </label>
                      <textarea
                        id="message"
                        name="message"
                        rows="4"
                        className={styles.formTextarea}
                        value={formData.message}
                        onChange={handleChange}
                        placeholder="Tell us about your background, specific interests, or how you'd like to contribute to the HealthPhases Project."
                      />
                    </div>
                    
                    <div className={styles.formActions}>
                      <button
                        type="submit"
                        className={styles.submitButton}
                        disabled={isSubmitting}
                      >
                        {isSubmitting ? (
                          <>
                            <span className={styles.spinner}></span>
                            Submitting...
                          </>
                        ) : (
                          'Submit Request'
                        )}
                      </button>
                    </div>
                  </form>
                </div>
              </div>
            )}
            
            <div className={styles.contactSection}>
              <h2>Contact Us</h2>
              <p>For questions about participation or to discuss potential collaboration:</p>
              
              <div className={styles.contactGrid}>
                <div className={styles.contactItem}>
                  <div className={styles.contactIcon}>
                    <svg width="24" height="24" viewBox="0 0 24 24" fill="currentColor">
                      <path d="M20 4H4C2.9 4 2.01 4.9 2.01 6L2 18C2 19.1 2.9 20 4 20H20C21.1 20 22 19.1 22 18V6C22 4.9 21.1 4 20 4ZM20 8L12 13L4 8V6L12 11L20 6V8Z" />
                    </svg>
                  </div>
                  <div>
                    <h3>Email Us</h3>
                    <a href="mailto:jcb26@buffalo.edu">jcb26@buffalo.edu</a>
                  </div>
                </div>
                
                <div className={styles.contactItem}>
                  <div className={styles.contactIcon}>
                    <svg width="24" height="24" viewBox="0 0 24 24" fill="currentColor">
                      <path d="M12 2C8.13 2 5 5.13 5 9C5 14.25 12 22 12 22C12 22 19 14.25 19 9C19 5.13 15.87 2 12 2ZM12 11.5C10.62 11.5 9.5 10.38 9.5 9C9.5 7.62 10.62 6.5 12 6.5C13.38 6.5 14.5 7.62 14.5 9C14.5 10.38 13.38 11.5 12 11.5Z" />
                    </svg>
                  </div>
                  <div>
                    <h3>Visit Us</h3>
                    <address>
                      University at Buffalo<br/>
                      Buffalo, NY 14260<br/>
                      United States
                    </address>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </Layout>
  );
}

export default JoinPage; 