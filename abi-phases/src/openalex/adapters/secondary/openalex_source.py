"""Exact OpenAlex lookups, bounded retries and normalized public metadata."""

from time import sleep
from urllib.parse import quote, urljoin, urlparse

import requests

from openalex.domain.openalex_errors import OpenalexUnavailable
from openalex.domain.openalex_matching import work_id

API = "https://api.openalex.org"


class OpenalexSource:
    def __init__(self, api_key="", session=None, sleeper=sleep, interval=1.0):
        self.api_key = api_key
        self.session = session or requests.Session()
        self.sleep = sleeper
        self.interval = interval

    def lookup(self, identifier, before_request):
        url = f"{API}/works/{quote(identifier, safe=':')}"
        headers = {"User-Agent": "HealthyPhases-OpenAlex/1.0"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        redirects = 0
        for attempt in range(3):
            while True:
                before_request()
                self.sleep(self.interval)
                try:
                    response = self.session.get(
                        url, headers=headers, timeout=30, allow_redirects=False
                    )
                except requests.RequestException:
                    response = None
                if response is not None and response.status_code in (
                    301,
                    302,
                    307,
                    308,
                ):
                    target = urljoin(url, response.headers.get("Location", ""))
                    if (
                        urlparse(target).netloc != "api.openalex.org"
                        or urlparse(target).scheme != "https"
                        or redirects >= 3
                    ):
                        raise OpenalexUnavailable(
                            "OpenAlex returned an unsupported redirect"
                        )
                    url, redirects = target, redirects + 1
                    continue
                break
            if response is not None:
                if response.status_code == 404:
                    return None
                if response.status_code == 200:
                    try:
                        payload = response.json()
                        work_id(payload["id"])
                        return payload
                    except (ValueError, KeyError, TypeError) as exc:
                        raise OpenalexUnavailable(
                            "OpenAlex returned an invalid work record"
                        ) from exc
                if response.status_code in (401, 403):
                    raise OpenalexUnavailable(
                        "OpenAlex rejected the API credentials; check OPENALEX_API_KEY and resume"
                    )
                if response.status_code != 429 and response.status_code < 500:
                    raise OpenalexUnavailable(
                        f"OpenAlex rejected the lookup (HTTP {response.status_code})"
                    )
            if attempt < 2:
                retry_after = (
                    response.headers.get("Retry-After", "0")
                    if response is not None
                    else "0"
                )
                try:
                    delay = min(30, max(2**attempt, float(retry_after)))
                except ValueError:
                    delay = 2**attempt
                self.sleep(delay)
        raise OpenalexUnavailable(
            "OpenAlex unavailable or rate limited; resume later to retry from the checkpoint"
        )
