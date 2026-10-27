# HealthyPhases Project Deployment Instructions

## Changes Made

We've successfully transformed the website to represent the HealthyPhases Project with the following changes:

1. **Core Configuration**
   - Updated site title, description, and metadata in `docusaurus.config.js`
   - Updated repository and organization information
   - Changed color scheme from gold to blue

2. **Content**
   - Created new pages for the project overview, team, and research background
   - Created pages for Research Areas, ontology development, and web resources
   - Updated the join page to reflect participation options for the HealthyPhases Project
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

## Platform release (ABI API and Nexus web)

The HealthyPhases platform under `abi-phases/` runs one ABI release, currently
`naas-abi-v2.93.1`, in two places that must move together:

- **ABI API:** the `abi-phases/.abi` submodule, pinned to the release tag. The
  `abi` and `dagster` containers run from it, and `abi-phases/pyproject.toml`
  installs its `libs/*` as path dependencies.
- **Nexus web:** the prebuilt image `ghcr.io/jupyter-naas/nexus-web:naas-abi-vX.Y.Z`,
  pinned on the `nexus-web` service in `abi-phases/docker-compose.yml`. The
  server `.env` no longer chooses it: `NEXUS_WEB_IMAGE` and `NEXUS_WEB_TAG` there
  are ignored.

To move to another release, in one commit:

1. `git -C abi-phases/.abi fetch --tags && git -C abi-phases/.abi checkout naas-abi-vX.Y.Z`
2. Change the `nexus-web` image tag in `abi-phases/docker-compose.yml` to the same tag.
3. Raise the `naas-abi*` floors in `abi-phases/pyproject.toml` to the versions in
   `abi-phases/.abi/libs/*/pyproject.toml`, then run `uv lock` in `abi-phases/`.
4. `make test` in `abi-phases/`. `tests/release_pin_test.py` fails if the image
   tag and the submodule release differ.

A merge to `main` deploys it: `.github/workflows/deploy.yaml` recreates `abi`,
`dagster` and `nexus-web` (pulling the pinned image), then checks that the API
and the web app answer.

## Contact

If you need any assistance with the deployment or have questions about the changes, please contact the development team. 