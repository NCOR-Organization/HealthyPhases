import { themes as prismThemes } from 'prism-react-renderer';

// @ts-check

// This runs in Node.js - Don't use client-side code here (browser APIs, JSX...)

/** @type {import('@docusaurus/types').Config} */
const config = {
  title: 'HealthyPhases Project',
  tagline: 'Promoting Healthy Aging through Semantic Enrichment of Solitude Research',
  favicon: 'img/favicon.ico',

  // Set the production url of your site here
  url: 'https://healthyphases.org',
  // Set the /<baseUrl>/ pathname under which your site is served
  // For GitHub pages deployment, it is often '/<projectName>/'
  baseUrl: '/',

  // GitHub pages deployment config.
  // If you aren't using GitHub pages, you don't need these.
  organizationName: 'HealthyPhases', // Updated from NCOR-Organization
  projectName: 'HealthyPhases', // Updated from NCOR-Network
  trailingSlash: false,

  onBrokenLinks: 'ignore',
  onBrokenMarkdownLinks: 'warn',

  // Even if you don't use internationalization, you can use this field to set
  // useful metadata like html lang. For example, if your site is Chinese, you
  // may want to replace "en" with "zh-Hans".
  i18n: {
    defaultLocale: 'en',
    locales: ['en'],
  },

  presets: [
    [
      'classic',
      /** @type {import('@docusaurus/preset-classic').Options} */
      ({
        docs: {
          sidebarPath: require.resolve('./sidebars.js'),
          // Remove or update this if needed
          editUrl: 'https://github.com/NCOR-Organization/NCOR-Network/tree/main/',
        },
        blog: false,
        theme: {
          customCss: './src/css/custom.css',
        },
      }),
    ],
  ],
  
  // Wiki plugin has been removed
  plugins: [],

  themeConfig:
    /** @type {import('@docusaurus/preset-classic').ThemeConfig} */
    ({
      // Replace with your project's social card
      image: 'img/healthyphases-social-card.png',
      navbar: {
        title: 'HealthyPhases',
        logo: {
          alt: 'HealthyPhases Logo',
          src: 'img/healthyphases-logo.png',
          srcDark: 'img/healthyphases-logo.png',
        },
        items: [
          {
            to: '/docs/about/overview',
            label: 'Documentation',
            position: 'right',
          },
          {
            href: 'https://github.com/NCOR-Organization/HealthyPhases',
            label: 'GitHub',
            position: 'right',
          },
          {
            to: '/join',
            label: 'Join Us',
            position: 'right',
            className: 'button button--primary navbar-join-button',
          },
        ],
      },
      footer: {
        style: 'dark',
        links: [
          {
            title: 'HealthyPhases',
            items: [
              {
                html: `
                  <p style="text-align: left; max-width: 300px; margin-top: -5px;">
                    The HealthyPhases Project promotes healthy aging through semantic enrichment of solitude research, creating standardized ontologies for better understanding gerotranscendence and solitude.
                  </p>
                `,
              },
            ],
          },
          {
            title: 'Quick Links',
            items: [
              {
                label: 'Home',
                to: '/',
              },
              {
                label: 'About',
                to: '/docs/about/overview',
              },
              {
                label: 'Research',
                to: '/docs/research/areas',
              },
              {
                label: 'Team',
                to: '/docs/about/team',
              },
            ],
          },
          {
            title: 'Resources',
            items: [
              {
                label: 'Publications',
                to: '/docs/resources/publications',
              },
              {
                label: 'Ontologies',
                to: '/docs/resources/ontology-development',
              },
              {
                label: 'Terms & References',
                to: '/docs/resources/terms-references',
              },
              {
                label: 'GitHub',
                href: 'https://github.com/NCOR-Organization/HealthyPhases',
              },
            ],
          },
          {
            title: 'Contact',
            items: [
              {
                html: `
                  <div style="display: flex; align-items: flex-start; margin-bottom: 8px;">
                    <svg style="min-width: 20px; margin-right: 8px; margin-top: 4px;" width="20" height="20" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                      <path d="M12 2C8.13 2 5 5.13 5 9C5 14.25 12 22 12 22C12 22 19 14.25 19 9C19 5.13 15.87 2 12 2ZM12 11.5C10.62 11.5 9.5 10.38 9.5 9C9.5 7.62 10.62 6.5 12 6.5C13.38 6.5 14.5 7.62 14.5 9C14.5 10.38 13.38 11.5 12 11.5Z" fill="#adbac7"/>
                    </svg>
                    <span>
                      University at Buffalo<br/>
                      Buffalo, NY 14260<br/>
                      United States
                    </span>
                  </div>
                  <div style="display: flex; align-items: center;">
                    <svg style="min-width: 20px; margin-right: 8px;" width="20" height="20" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                      <path d="M20 4H4C2.9 4 2.01 4.9 2.01 6L2 18C2 19.1 2.9 20 4 20H20C21.1 20 22 19.1 22 18V6C22 4.9 21.1 4 20 4ZM20 8L12 13L4 8V6L12 11L20 6V8Z" fill="#adbac7"/>
                    </svg>
                    <a href="mailto:johnbeve@buffalo.edu">johnbeve@buffalo.edu</a>
                  </div>
                `,
              },
            ],
          },
        ],
        copyright: `© ${new Date().getFullYear()} HealthyPhases Project. All rights reserved. | <a href="#">Privacy Policy</a> | <a href="#">Terms of Use</a>`,
      },
      prism: {
        theme: prismThemes.github,
        darkTheme: prismThemes.dracula,
      },
      colorMode: {
        defaultMode: 'light',
        disableSwitch: true,
        respectPrefersColorScheme: false,
      },
      docs: {
        sidebar: {
          hideable: false,
          autoCollapseCategories: false
        }
      },
      announcementBar: {
        id: 'project_announcement',
        content: 
          '🚧 <strong>Work in Progress:</strong> This site is currently under development. Check back soon for updates! 🚧',
        backgroundColor: '#fff3cd', // Light yellow background
        textColor: '#0066cc',        // Blue text
        isCloseable: false,          // Make it persistent
      },
    }),
  stylesheets: [
    {
      href: 'https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=Merriweather:wght@300;400;700;900&display=swap',
      type: 'text/css',
    },
  ],
  headTags: [
    {
      tagName: 'script',
      attributes: {
        type: 'text/javascript',
        src: 'https://cdn.jsdelivr.net/npm/@emailjs/browser@3/dist/email.min.js',
      },
    },
    {
      tagName: 'script',
      attributes: {
        type: 'text/javascript',
      },
      innerHTML: `
        (function(){
          emailjs.init("YOUR_USER_ID"); // Replace with your actual EmailJS user ID
        })();
      `,
    },
  ],
};

export default config; 