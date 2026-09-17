"""Exact identifier matching; uncertain identity never becomes an automatic link."""

import re


def normalize_doi(value: str | None) -> str:
    value = (value or "").strip().lower()
    value = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", value)
    return value if re.fullmatch(r"10\.\d{4,9}/\S{1,2000}", value) else ""


def normalize_pmid(value: str | None) -> str:
    value = (value or "").strip().rstrip("/")
    value = re.sub(
        r"^(?:https?://pubmed\.ncbi\.nlm\.nih\.gov/|https?://www\.ncbi\.nlm\.nih\.gov/pubmed/|pmid:)",
        "",
        value,
    )
    return value if re.fullmatch(r"[1-9][0-9]*", value) else ""


def work_id(value: str) -> str:
    value = re.sub(r"^https?://openalex\.org/", "", value or "", flags=re.I).upper()
    if not re.fullmatch(r"W[0-9]+", value):
        raise ValueError("OpenAlex returned an invalid work identifier")
    return value


def match(paper: dict, candidates: list[dict]) -> tuple[str, dict | None, str]:
    pmid, doi = paper["pmid"], normalize_doi(paper.get("doi"))
    unique = {work_id(c["id"]): c for c in candidates}
    if not unique:
        return "no_match", None, "No exact DOI or PMID match was found"
    if len(unique) != 1:
        return "ambiguous", None, "DOI and PMID resolve to different OpenAlex works"
    matched = set()
    for candidate in candidates:
        ids = candidate.get("ids") or {}
        raw_pmid = ids.get("pmid")
        raw_doi = candidate.get("doi") or ids.get("doi")
        candidate_pmid = normalize_pmid(raw_pmid)
        candidate_doi = normalize_doi(raw_doi)
        if (raw_pmid and not candidate_pmid) or (raw_doi and not candidate_doi):
            return (
                "ambiguous",
                None,
                "OpenAlex returned identifiers that could not be verified",
            )
        if (candidate_pmid and candidate_pmid != pmid) or (
            doi and candidate_doi and candidate_doi != doi
        ):
            return (
                "ambiguous",
                None,
                "OpenAlex identifiers conflict with the PubMed record",
            )
        if candidate_pmid == pmid:
            matched.add("pmid")
        if doi and candidate_doi == doi:
            matched.add("doi")
    if not matched:
        return (
            "ambiguous",
            None,
            "The returned work does not confirm the requested identifiers",
        )
    return (
        "enriched",
        candidates[-1],
        "+".join(key for key in ("pmid", "doi") if key in matched),
    )
