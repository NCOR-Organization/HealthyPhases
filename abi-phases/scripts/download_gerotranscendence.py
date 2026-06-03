"""One-off: search PubMed for 'gerotranscendence' and download all PMC OA PDFs."""

import concurrent.futures
from pathlib import Path

from naas_abi_marketplace.applications.pubmed.integrations.PubMedAPI import (
    PubMedAPIConfiguration,
    PubMedIntegration,
)
from naas_abi_marketplace.applications.pubmed.integrations.PubMedAPI.PubMedCentralDownloader import (
    PubMedCentralDownloader,
)

QUERY = "gerotranscendence"
START_DATE = "1990/01/01"
MAX_RESULTS = 500
OA_FILE_LIST = "/Users/maximejublou/dev/ncor/HealthyPhases/abi_/oa_file_list.txt"
OUT_DIR = Path("src/phases/papers/gero/pmc")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    integration = PubMedIntegration(PubMedAPIConfiguration())
    results = integration.search_date_range(
        QUERY, start_date=START_DATE, max_results=MAX_RESULTS
    )
    print(f"Found {len(results)} results for '{QUERY}'")

    downloadable = [r for r in results if r.pmcid]
    print(f"{len(downloadable)} have a PMCID")

    downloader = PubMedCentralDownloader()

    def fetch(summary):
        pmcid = summary.pmcid
        out = OUT_DIR / f"{pmcid}.pdf"
        if out.exists():
            return pmcid, "skip (exists)"
        try:
            stream = downloader.open_pmc_pdf_stream(pmcid, OA_FILE_LIST)
            out.write_bytes(stream.read())
            return pmcid, f"ok ({out.stat().st_size} bytes)"
        except FileNotFoundError as e:
            return pmcid, f"not in OA list: {e}"
        except Exception as e:
            return pmcid, f"error: {type(e).__name__}: {e}"

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        for pmcid, status in ex.map(fetch, downloadable):
            print(f"  {pmcid}: {status}")

    print(f"\nDone. PDFs in {OUT_DIR.resolve()}")


if __name__ == "__main__":
    main()
