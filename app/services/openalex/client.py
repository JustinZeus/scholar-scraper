import logging

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.logging_utils import structured_log
from app.services.openalex.types import OpenAlexWork

logger = logging.getLogger(__name__)

OPENALEX_BASE_URL = "https://api.openalex.org"


class OpenAlexClientError(Exception):
    pass


class OpenAlexRateLimitError(OpenAlexClientError):
    """Transient rate limit (too many requests per second)."""

    pass


class OpenAlexBudgetExhaustedError(OpenAlexClientError):
    """Daily API budget exhausted — retrying is futile until midnight UTC."""

    pass


class OpenAlexClient:
    def __init__(
        self,
        api_key: str | None = None,
        mailto: str | None = None,
        timeout: float = 10.0,
    ) -> None:
        self.api_key = api_key
        self.mailto = mailto
        self.timeout = timeout

    @property
    def _base_params(self) -> dict[str, str]:
        params = {}
        if self.mailto:
            params["mailto"] = self.mailto
        if self.api_key:
            params["api_key"] = self.api_key
        return params

    @retry(
        retry=retry_if_exception_type((httpx.NetworkError, httpx.TimeoutException)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    async def get_work_by_doi(self, doi: str) -> OpenAlexWork | None:
        """Fetch a single work by DOI directly."""
        clean_doi = doi.replace("https://doi.org/", "")
        if not clean_doi:
            return None

        url = f"{OPENALEX_BASE_URL}/works/{clean_doi}"

        headers = {}
        if self.mailto:
            headers["User-Agent"] = f"scholar-scraper/1.0 (mailto:{self.mailto})"
        else:
            headers["User-Agent"] = "scholar-scraper/1.0"

        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True, headers=headers) as client:
            response = await client.get(url, params=self._base_params)

        if response.status_code == 404:
            return None
        if response.status_code == 429:
            remaining = response.headers.get("X-RateLimit-Remaining-USD", "")
            if remaining == "0" or remaining.startswith("-"):
                raise OpenAlexBudgetExhaustedError("Daily API budget exhausted; retrying won't help until midnight UTC")
            raise OpenAlexRateLimitError("Rate limit exceeded fetching OpenAlex work by DOI")
        if response.status_code >= 400:
            structured_log(
                logger,
                "warning",
                "openalex.api_error",
                status_code=response.status_code,
                response_preview=response.text[:500],
            )
            raise OpenAlexClientError(f"API Error {response.status_code}")

        data = response.json()
        return OpenAlexWork.from_api_dict(data)

    @retry(
        retry=retry_if_exception_type((httpx.NetworkError, httpx.TimeoutException)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    async def get_works_by_filter(
        self,
        filters: dict[str, str],
        limit: int = 50,
    ) -> list[OpenAlexWork]:
        """
        Fetch works using the ?filter= query parameter.
        Supports fetching multiple records by joining filters with | (OR logic).
        """
        if not filters:
            return []

        # Example: {"doi": "10.foo|10.bar", "title.search": "query"}
        filter_str = ",".join(f"{k}:{v}" for k, v in filters.items())

        params = self._base_params.copy()
        params["filter"] = filter_str
        params["per-page"] = str(limit)

        url = f"{OPENALEX_BASE_URL}/works"

        headers = {}
        if self.mailto:
            headers["User-Agent"] = f"scholar-scraper/1.0 (mailto:{self.mailto})"
        else:
            headers["User-Agent"] = "scholar-scraper/1.0"

        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True, headers=headers) as client:
            response = await client.get(url, params=params)

        if response.status_code == 429:
            remaining = response.headers.get("X-RateLimit-Remaining-USD", "")
            if remaining == "0" or remaining.startswith("-"):
                raise OpenAlexBudgetExhaustedError("Daily API budget exhausted; retrying won't help until midnight UTC")
            raise OpenAlexRateLimitError("Rate limit exceeded fetching OpenAlex works list")
        if response.status_code >= 400:
            structured_log(
                logger,
                "warning",
                "openalex.api_error_with_filters",
                filters=filters,
                status_code=response.status_code,
                response_preview=response.text[:500],
            )
            raise OpenAlexClientError(f"API Error {response.status_code}")

        data = response.json()
        results = data.get("results") or []

        parsed_works = []
        for raw_work in results:
            try:
                parsed_works.append(OpenAlexWork.from_api_dict(raw_work))
            except Exception as exc:
                structured_log(
                    logger,
                    "warning",
                    "openalex.parse_failed",
                    error=str(exc),
                )
                continue

        return parsed_works
