"""The workspace actions as the assistant's tools.

Each tool is a :class:`~phases_v2.assistant.workspace.WorkspaceActions` method
with a description of when to use it. Tools that queue costly work come in
pairs (``prepare_*`` then ``queue_*`` or ``create_*``); the second refuses to
act without the first's token and the user's yes in between.
"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import BaseTool, tool

from phases_v2.assistant.workspace import WorkspaceActions

COSTLY_PAIRS = {
    "prepare_run": "queue_run",
    "prepare_pubmed_ingestion": "queue_pubmed_ingestion",
    "prepare_pubmed_schedule": "create_pubmed_schedule",
    "prepare_openalex_enrichment": "queue_openalex_enrichment",
}


def build_tools(actions: WorkspaceActions) -> list[BaseTool]:
    # -- reading ----------------------------------------------------------

    @tool
    def list_collections() -> dict[str, Any]:
        """Every collection with how many papers and members it has."""
        return actions.list_collections()

    @tool
    def get_collection(collection_id: str) -> dict[str, Any]:
        """One collection: its members (PubMed searches, folders, single papers)
        and its papers with their status (not_ingested, ingested, results)."""
        return actions.get_collection(collection_id)

    @tool
    def list_pubmed_searches() -> dict[str, Any]:
        """Saved PubMed searches, newest first, with how many papers each
        matched and how many are downloaded. A search_id is what collections,
        downloads, schedules and enrichment take."""
        return actions.list_pubmed_searches()

    @tool
    def get_pubmed_search(search_id: str) -> dict[str, Any]:
        """One saved PubMed search with the papers it previewed and which of
        them are downloaded."""
        return actions.get_pubmed_search(search_id)

    @tool
    def browse_library(
        search: str = "", search_id: str = "", page: int = 1
    ) -> dict[str, Any]:
        """Downloaded PubMed papers in the library, filtered by words in their
        title, authors or journal, or by saved search. 25 per page."""
        return actions.browse_library(search, search_id, page)

    @tool
    def list_prompts() -> dict[str, Any]:
        """Every prompt version: prompt_id, name, output format and the start of
        its text. Versions of one prompt share its name."""
        return actions.list_prompts()

    @tool
    def get_prompt_versions(name: str) -> dict[str, Any]:
        """Every version of one prompt, newest first, with its full text and
        how often it ran."""
        return actions.get_prompt_versions(name)

    @tool
    def list_models_and_chunkers() -> dict[str, Any]:
        """The models a run or a try can use (only available ones work) and the
        chunkers that cut papers into chunks."""
        return actions.list_models_and_chunkers()

    @tool
    def list_runs() -> dict[str, Any]:
        """The 25 most recent pipeline runs with their status."""
        return actions.list_runs()

    @tool
    def get_run(run_id: str) -> dict[str, Any]:
        """One pipeline run: status, choices, timings and how many chunks
        succeeded, failed or were skipped."""
        return actions.get_run(run_id)

    @tool
    def list_downloads_and_enrichments() -> dict[str, Any]:
        """Recent PubMed downloads and full ingestions, scheduled searches, and
        OpenAlex enrichments, with their status."""
        return actions.list_downloads_and_enrichments()

    @tool
    def list_run_configurations() -> dict[str, Any]:
        """Saved run configurations: a collection or folders, prompts, model and
        chunker kept to run again."""
        return actions.list_run_configurations()

    @tool
    def list_papers(
        q: str = "",
        collection_id: str = "",
        run_id: str = "",
        has_results: bool | None = None,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Ingested papers (ready for prompts and runs) with their result
        counts. Filter by words in the title, file name or PMID, by collection,
        by the run that covered them, or by whether they have results. 25 per
        page; use offset for more. A paper_id from here is what trying a prompt
        and reading results take."""
        return actions.list_papers(q, collection_id, run_id, has_results, offset)

    @tool
    def get_paper_results(
        paper_id: str, prompt_id: str = "", model_id: str = ""
    ) -> dict[str, Any]:
        """One paper: its record, what ran on it, the runs that covered it, and
        its results grouped by prompt version and model (the first 15 items of
        each). Narrow to one prompt_id or model_id when the user asks about one."""
        return actions.get_paper_results(paper_id, prompt_id, model_id)

    @tool
    def get_paper_chunks(
        paper_id: str, chunker_id: str, page: int = 1
    ) -> dict[str, Any]:
        """A paper's chunks for one chunker, in order, each with a short
        preview, to pick which ones to try a prompt on. 25 chunks a page out
        of "total"; ask for the next page for more."""
        return actions.get_paper_chunks(paper_id, chunker_id, page)

    @tool
    def search_findings(
        query: str,
        by: str = "meaning",
        collection_id: str = "",
        prompt_names: list[str] | None = None,
        model_ids: list[str] | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        """Search extracted findings by "meaning" or by exact words
        ("keyword"), optionally within one collection or for some prompts or
        models. Each hit names its paper."""
        return actions.search_findings(
            query, by, collection_id, prompt_names or [], model_ids or [], limit
        )

    # -- acting freely ------------------------------------------------------

    @tool
    def search_pubmed(
        query: str,
        max_results: int = 100,
        start_date: str = "",
        end_date: str = "",
        sort: str = "relevance",
    ) -> dict[str, Any]:
        """Search PubMed and save the search with up to max_results (1-1000)
        papers previewed. Downloads nothing. Dates are YYYY-MM-DD; sort is
        "relevance" or "pub_date". Returns the search_id."""
        return actions.search_pubmed(query, max_results, start_date, end_date, sort)

    @tool
    def create_collection(
        name: str,
        description: str = "",
        pubmed_search_ids: list[str] | None = None,
        pmids: list[str] | None = None,
        paper_ids: list[str] | None = None,
        folders: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a collection, optionally with members: saved PubMed searches
        (live: papers they download later join), single PubMed papers by PMID,
        ingested papers by paper_id, or storage folders."""
        return actions.create_collection(
            name,
            description,
            pubmed_search_ids or [],
            pmids or [],
            paper_ids or [],
            folders or [],
        )

    @tool
    def update_collection(
        collection_id: str, name: str | None = None, description: str | None = None
    ) -> dict[str, Any]:
        """Rename a collection or change its description. What is not given
        stays as it is."""
        return actions.update_collection(collection_id, name, description)

    @tool
    def add_to_collection(
        collection_id: str,
        pubmed_search_ids: list[str] | None = None,
        pmids: list[str] | None = None,
        paper_ids: list[str] | None = None,
        folders: list[str] | None = None,
    ) -> dict[str, Any]:
        """Add members to a collection: saved PubMed searches, PMIDs, paper_ids
        or storage folders. Adding one already there changes nothing. Make one
        call per collection change rather than several at once."""
        return actions.add_to_collection(
            collection_id,
            pubmed_search_ids or [],
            pmids or [],
            paper_ids or [],
            folders or [],
        )

    @tool
    def save_prompt_version(
        name: str, template: str, output_format: str = "results"
    ) -> dict[str, Any]:
        """Save prompt text as a version of the prompt with this name (a new
        name starts a new prompt). The text must contain {chunk_text}.
        output_format is one of results, what, causes, how, when, where,
        effects, conditional_statement, relations; keep the one the prompt
        already uses. Saving the same text again changes nothing."""
        return actions.save_prompt_version(name, template, output_format)

    @tool
    def try_prompt(
        paper_id: str,
        model_id: str,
        chunker_id: str,
        prompt_id: str = "",
        name: str = "",
        template: str = "",
        output_format: str = "",
        chunk_seqs: list[int] | None = None,
        first: int = 3,
        compare_with_prompt_id: str = "",
    ) -> dict[str, Any]:
        """Try a saved version (prompt_id) or a draft (template, with name and
        output_format) on at most 10 chunks of one ingested paper and return
        what it extracts from each, right away. Saves nothing. Pick chunks by
        chunk_seqs, or take the first ones (first, 1 to 10). The paper must be
        chunked with chunker_id. compare_with_prompt_id shows an earlier
        version's stored results for the same chunks."""
        return actions.try_prompt(
            paper_id,
            model_id,
            chunker_id,
            prompt_id,
            name,
            template,
            output_format,
            chunk_seqs or [],
            first,
            compare_with_prompt_id,
        )

    @tool
    def save_run_configuration(
        name: str,
        collection_id: str,
        chunker_id: str,
        prompt_ids: list[str],
        model_id: str,
    ) -> dict[str, Any]:
        """Save a run's choices (collection, prompt versions, model, chunker)
        under a name to run later. Queues nothing."""
        return actions.save_run_configuration(
            name, collection_id, chunker_id, prompt_ids, model_id
        )

    # -- costly: prepare, ask, then act -----------------------------------

    @tool
    def prepare_run(
        collection_id: str, chunker_id: str, prompt_ids: list[str], model_id: str
    ) -> dict[str, Any]:
        """Step 1 of queuing a pipeline run on a collection. Checks the choices
        and returns a summary (papers, prompts, model) and a confirmation token.
        Queues nothing."""
        return actions.prepare_run(collection_id, chunker_id, prompt_ids, model_id)

    @tool
    def queue_run(
        confirmation_token: str,
        collection_id: str,
        chunker_id: str,
        prompt_ids: list[str],
        model_id: str,
    ) -> dict[str, Any]:
        """Step 2: queue the run prepared with prepare_run, with its token and
        the same parameters. Only after the user said yes to its summary."""
        return actions.queue_run(
            confirmation_token, collection_id, chunker_id, prompt_ids, model_id
        )

    @tool
    def prepare_pubmed_ingestion(
        search_id: str, which: str = "previewed", pmids: list[str] | None = None
    ) -> dict[str, Any]:
        """Step 1 of downloading papers of a saved PubMed search. which
        "previewed" downloads the papers the search previewed (or only the
        given pmids among them); which "all" finds and downloads every paper
        PubMed matches. Returns a summary and a confirmation token. Queues
        nothing."""
        return actions.prepare_pubmed_ingestion(search_id, which, pmids or [])

    @tool
    def queue_pubmed_ingestion(
        confirmation_token: str,
        search_id: str,
        which: str = "previewed",
        pmids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Step 2: queue the download prepared with prepare_pubmed_ingestion,
        with its token and the same parameters. Only after the user said yes."""
        return actions.queue_pubmed_ingestion(
            confirmation_token, search_id, which, pmids or []
        )

    @tool
    def prepare_pubmed_schedule(
        search_id: str,
        name: str,
        interval_hours: int = 24,
        download_new_papers: bool = True,
    ) -> dict[str, Any]:
        """Step 1 of scheduling a saved PubMed search to run again every 1, 24
        or 168 hours, downloading the new papers it finds unless told not to.
        Returns a summary and a confirmation token. Creates nothing."""
        return actions.prepare_pubmed_schedule(
            search_id, name, interval_hours, download_new_papers
        )

    @tool
    def create_pubmed_schedule(
        confirmation_token: str,
        search_id: str,
        name: str,
        interval_hours: int = 24,
        download_new_papers: bool = True,
    ) -> dict[str, Any]:
        """Step 2: create the schedule prepared with prepare_pubmed_schedule,
        with its token and the same parameters. Only after the user said yes."""
        return actions.create_pubmed_schedule(
            confirmation_token, search_id, name, interval_hours, download_new_papers
        )

    @tool
    def prepare_openalex_enrichment(
        search_id: str, refresh: bool = False
    ) -> dict[str, Any]:
        """Step 1 of enriching a saved PubMed search's papers with OpenAlex
        (citations, topics, institutions). refresh fetches again papers
        enriched recently. Returns a summary and a confirmation token. Queues
        nothing."""
        return actions.prepare_openalex_enrichment(search_id, refresh)

    @tool
    def queue_openalex_enrichment(
        confirmation_token: str, search_id: str, refresh: bool = False
    ) -> dict[str, Any]:
        """Step 2: queue the enrichment prepared with prepare_openalex_enrichment,
        with its token and the same parameters. Only after the user said yes."""
        return actions.queue_openalex_enrichment(confirmation_token, search_id, refresh)

    return [
        list_collections,
        get_collection,
        list_pubmed_searches,
        get_pubmed_search,
        browse_library,
        list_prompts,
        get_prompt_versions,
        list_models_and_chunkers,
        list_runs,
        get_run,
        list_downloads_and_enrichments,
        list_run_configurations,
        list_papers,
        get_paper_results,
        get_paper_chunks,
        search_findings,
        search_pubmed,
        create_collection,
        update_collection,
        add_to_collection,
        save_prompt_version,
        try_prompt,
        save_run_configuration,
        prepare_run,
        queue_run,
        prepare_pubmed_ingestion,
        queue_pubmed_ingestion,
        prepare_pubmed_schedule,
        create_pubmed_schedule,
        prepare_openalex_enrichment,
        queue_openalex_enrichment,
    ]
