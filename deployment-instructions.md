# HealthPhases Project Deployment Instructions

## Changes Made

We've successfully transformed the website to represent the HealthPhases Project with the following changes:

1. **Core Configuration**
   - Updated site title, description, and metadata in `docusaurus.config.js`
   - Updated repository and organization information
   - Changed color scheme from gold to blue

2. **Content**
   - Created new pages for the project overview, team, and research background
   - Created pages for research aims, ontology development, and web resources
   - Updated the join page to reflect participation options for the HealthPhases Project
   - Created wiki resources on common data models, semantic enrichment, and knowledge graphs
   - Updated the glossary with terminology relevant to solitude and gerotranscendence research

3. **Visual Design**
   - Updated the homepage with a new hero section and graphics
   - Changed the color scheme to blue throughout the site
   - Updated navigation structure

## Next Steps

To complete the deployment, you should:

### 1. Create/Update Images

Create or update the following image files:

- `/static/img/healthyphases-logo.png` - Main logo for the site
- `/static/img/healthyphases-banner.png` - Banner image for README
- `/static/img/healthyphases-social-card.png` - Social media sharing card

### 2. Add Team Photos

Add team member photos to:
- `/static/img/team/`

### 3. Update Other Components

The following components may need additional updates:
- `src/components/AboutSection`
- `src/components/ResearchAreasSection`
- `src/components/PeopleSection`
- `src/components/EventsSection`
- `src/components/HomepageFeatures`

### 4. Email Configuration

Set up email handling for the contact form:
1. Create an EmailJS account at https://www.emailjs.com/
2. Replace the placeholders in the join.js file:
   - `YOUR_SERVICE_ID`
   - `YOUR_TEMPLATE_ID`
   - `YOUR_USER_ID`

### 5. Additional Content

Create more detailed content for:
- Additional research publications
- Specific workshop materials
- Case studies and examples
- Implementation guides for the common data model

### 6. Deploy the Site

1. **Testing**
   ```bash
   npm run build
   npm run serve
   ```

2. **Setup Hosting**
   - Set up a hosting platform (GitHub Pages, Netlify, Vercel, etc.)
   - Configure your domain (healthyphases.org)

3. **Deploy**
   ```bash
   npm run deploy
   ```

## Contact

If you need any assistance with the deployment or have questions about the changes, please contact the development team. 