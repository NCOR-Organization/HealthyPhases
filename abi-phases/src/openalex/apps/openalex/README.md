# OpenAlex enrichment app

Nexus catalog ID: `openalex:openalex`. Choose a saved PubMed query and queue enrichment. The app shows request progress and allows resuming interrupted requests. The request covers every paper saved for the query at submission, with or without a PDF.

Use PubMed Library's Papers page for paper details and citation/topic/institution filters. HTTP mutation authentication follows Nexus bearer credentials. API keys remain server-side in SecretService.
