"""NCBI E-utilities search and the public PMC Cloud article distribution."""

import hashlib
import re
import threading
import time
from typing import Any
from urllib.parse import parse_qs, quote, urlparse
from xml.etree import ElementTree

import requests

from pubmed.domain.pubmed_errors import AcquisitionError, FullTextUnavailable

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
CLOUD = "https://pmc-oa-opendata.s3.amazonaws.com"


class NcbiSource:
    def __init__(
        self,
        api_key="",
        email="",
        session=None,
        sleep=time.sleep,
        timeout=30,
        max_pdf_bytes=100 * 1024 * 1024,
    ):
        self.api_key, self.email = api_key, email
        self.http = session or requests.Session()
        self.sleep, self.timeout, self.max_pdf_bytes = sleep, timeout, max_pdf_bytes
        self._lock = threading.Lock()

    def _get(self, url, params=None, stream=False):
        for attempt in range(3):
            # Serialize calls made through this client, including search and download.
            with self._lock:
                self.sleep(0.34)
                try:
                    response = self.http.get(
                        url,
                        params=params,
                        timeout=self.timeout,
                        stream=stream,
                        allow_redirects=False,
                    )
                    if response.status_code == 429 or response.status_code >= 500:
                        response.close()
                        if attempt < 2:
                            self.sleep(2**attempt)
                            continue
                    response.raise_for_status()
                    if 300 <= response.status_code < 400:
                        response.close()
                        raise AcquisitionError("Unexpected redirect from NCBI")
                    return response
                except requests.RequestException as exc:
                    if attempt == 2 or (
                        getattr(exc, "response", None) is not None
                        and 400 <= exc.response.status_code < 500
                        and exc.response.status_code != 429
                    ):
                        raise AcquisitionError(
                            "NCBI request failed; retry later or check the identifier"
                        ) from exc
                    self.sleep(2**attempt)
        raise AcquisitionError("NCBI request failed after three attempts")

    def _json(self, url, params=None):
        response = self._get(url, params)
        try:
            return response.json()
        except ValueError as exc:
            raise AcquisitionError("NCBI returned invalid JSON") from exc
        finally:
            response.close()

    def _entrez(self, endpoint, **params):
        params.update(db="pubmed", retmode="json", tool="healthyphases_pubmed")
        if self.api_key:
            params["api_key"] = self.api_key
        if self.email:
            params["email"] = self.email
        result = self._json(f"{EUTILS}/{endpoint}.fcgi", params)
        if result.get("error"):
            raise AcquisitionError(str(result["error"]))
        return result

    def search(self, parameters: dict[str, Any]) -> tuple[int, list[dict[str, Any]]]:
        options = {
            "term": parameters["query"],
            "sort": parameters["sort"],
            "datetype": "pdat",
        }
        start_date = parameters.get("start_date")
        end_date = parameters.get("end_date")
        if start_date or end_date:
            # ESearch silently ignores date restrictions unless both bounds exist.
            options["mindate"] = (start_date or "0001-01-01").replace("-", "/")
            options["maxdate"] = (end_date or "9999-12-31").replace("-", "/")
        papers, total = [], 0
        for start in range(0, parameters["max_results"], 200):
            result = self._entrez(
                "esearch",
                **options,
                retstart=start,
                retmax=min(200, parameters["max_results"] - start),
            )["esearchresult"]
            if result.get("ERROR") or result.get("errorlist"):
                raise AcquisitionError("PubMed rejected the search expression")
            total = int(result["count"])
            ids = result.get("idlist", [])
            if not ids:
                break
            summaries = self._entrez("esummary", id=",".join(ids))["result"]
            for pmid in ids:
                item = summaries.get(pmid)
                if not item or item.get("error"):
                    raise AcquisitionError(
                        f"Missing PubMed summary for PMID {pmid}; retry the search"
                    )
                identifiers = {
                    a["idtype"]: a["value"] for a in item.get("articleids", [])
                }
                papers.append(
                    {
                        "pmid": pmid,
                        "pmcid": identifiers.get("pmc", ""),
                        "doi": identifiers.get("doi", ""),
                        "title": item.get("title", ""),
                        "journal": item.get("fulljournalname", ""),
                        "publication_date": item.get("pubdate", ""),
                        "authors": [a["name"] for a in item.get("authors", [])],
                    }
                )
            if start + len(ids) >= total:
                break
        return total, papers

    def _versions(self, pmcid):
        response = self._get(
            CLOUD + "/", {"list-type": "2", "prefix": pmcid + ".", "delimiter": "/"}
        )
        try:
            root = ElementTree.fromstring(response.content)
            if root.findtext("{*}IsTruncated") == "true":
                raise AcquisitionError("PMC version listing is truncated")
            prefixes = [e.text for e in root.findall("{*}CommonPrefixes/{*}Prefix")]
        except ElementTree.ParseError as exc:
            raise AcquisitionError("PMC returned invalid version metadata") from exc
        finally:
            response.close()
        return sorted(
            [
                p.rstrip("/")
                for p in prefixes
                if re.fullmatch(re.escape(pmcid) + r"\.[0-9]+/", p or "")
            ]
        )

    @staticmethod
    def _pdf_url(value):
        parsed = urlparse(value)
        if parsed.scheme == "s3" and parsed.netloc == "pmc-oa-opendata":
            value = CLOUD + parsed.path + ("?" + parsed.query if parsed.query else "")
            parsed = urlparse(value)
        if (
            parsed.scheme != "https"
            or parsed.netloc != "pmc-oa-opendata.s3.amazonaws.com"
        ):
            raise AcquisitionError(
                "PMC metadata references an unexpected download host"
            )
        return value

    def download(self, pmcid: str) -> tuple[bytes, dict[str, str]]:
        if not re.fullmatch(r"PMC[0-9]+", pmcid):
            raise ValueError("Invalid PMCID")
        candidates = []
        for version in self._versions(pmcid):
            metadata = self._json(f"{CLOUD}/{quote(version)}/{quote(version)}.json")
            if metadata.get("pdf_url"):
                candidates.append((version, metadata))
        if not candidates:
            raise FullTextUnavailable(f"{pmcid} has no distributed PDF in PMC Cloud")
        # Prefer the published article over a manuscript. Keep the exact chosen version.
        version, metadata = min(
            candidates,
            key=lambda item: (
                str(item[1].get("is_manuscript", "")).lower() in ("yes", "true", "1"),
                -int(item[0].rsplit(".", 1)[1]),
            ),
        )
        url = self._pdf_url(metadata["pdf_url"])
        response = self._get(url, stream=True)
        try:
            content = bytearray()
            for part in response.iter_content(chunk_size=65536):
                content.extend(part)
                if len(content) > self.max_pdf_bytes:
                    raise AcquisitionError(
                        "PDF exceeds the configured download size limit"
                    )
        except requests.RequestException as exc:
            raise AcquisitionError("PDF transfer interrupted") from exc
        finally:
            response.close()
        expected = parse_qs(urlparse(url).query).get("md5", [""])[0]
        if (
            expected
            and hashlib.md5(content, usedforsecurity=False).hexdigest() != expected
        ):
            raise AcquisitionError("PMC PDF checksum does not match its metadata")
        return bytes(content), {
            "version": version,
            "source_url": url,
            "license": metadata.get("license_code", ""),
        }
