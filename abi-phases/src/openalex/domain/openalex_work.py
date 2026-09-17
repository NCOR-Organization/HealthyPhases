"""Normalize source metadata into the enrichment publication contract."""

from datetime import UTC, datetime

from openalex.domain.openalex_matching import normalize_doi, normalize_pmid, work_id


def normalize_work(raw, fetched_at=None):
    ids = raw.get("ids") or {}
    oa = raw.get("open_access") or {}
    return {
        "work_id": work_id(raw["id"]),
        "doi": normalize_doi(raw.get("doi") or ids.get("doi", "")),
        "pmid": normalize_pmid(ids.get("pmid", "")),
        "title": raw.get("display_name") or "",
        "publication_year": raw.get("publication_year") or 0,
        "citation_count": raw.get("cited_by_count") or 0,
        "referenced_work_ids": [work_id(v) for v in raw.get("referenced_works") or []],
        "related_work_ids": [work_id(v) for v in raw.get("related_works") or []],
        "topics": [
            {
                "id": t.get("id") or "",
                "name": t.get("display_name") or "",
                "score": t.get("score") or 0,
            }
            for t in raw.get("topics") or []
        ],
        "authorships": [
            {
                "author_id": (a.get("author") or {}).get("id") or "",
                "name": (a.get("author") or {}).get("display_name") or "",
                "orcid": (a.get("author") or {}).get("orcid") or "",
                "institutions": [
                    {
                        "id": i.get("id") or "",
                        "name": i.get("display_name") or "",
                        "country_code": i.get("country_code") or "",
                    }
                    for i in a.get("institutions") or []
                ],
            }
            for a in raw.get("authorships") or []
        ],
        "locations": [
            {
                "landing_page_url": loc.get("landing_page_url") or "",
                "pdf_url": loc.get("pdf_url") or "",
                "source_name": (loc.get("source") or {}).get("display_name") or "",
                "license": loc.get("license") or "",
                "is_oa": bool(loc.get("is_oa")),
            }
            for loc in raw.get("locations") or []
        ],
        "is_oa": bool(oa.get("is_oa")),
        "oa_status": oa.get("oa_status") or "",
        "oa_url": oa.get("oa_url") or "",
        "source_updated_at": raw.get("updated_date") or "",
        "fetched_at": fetched_at or datetime.now(UTC).isoformat(),
        "contract_version": 1,
    }
