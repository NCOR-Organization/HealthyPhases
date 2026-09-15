"""Compatibility stream API backed by the current PMC Cloud distribution."""

from io import BytesIO
from typing import BinaryIO

from pubmed.adapters.secondary.pubmed_ncbi import NcbiSource


class PubMedCentralDownloader:
    def open_pmc_pdf_stream(
        self, pmcid: str, oa_file_list_path: str = "oa_file_list.txt"
    ) -> BinaryIO:
        """Return a PDF stream; the legacy file-list argument is accepted but unused."""
        content, _metadata = NcbiSource().download(pmcid)
        return BytesIO(content)
