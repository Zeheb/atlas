import time
from typing import Any

import requests

from atlas.config.settings import Settings


class BSEHttpClient:
    """HTTP transport for the BSE India web API.

    Manages a warm session (required for the BSE API to respond without
    redirecting), enforces the configured rate limit, and retries on 429.
    """

    _BASE_URL = "https://www.bseindia.com/"
    _API_BASE = "https://api.bseindia.com/BseIndiaAPI/api"

    _HEADERS: dict[str, str] = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/134.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.5",
        "Origin": "https://www.bseindia.com/",
        "Referer": "https://www.bseindia.com/",
        "Connection": "keep-alive",
    }

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._session: requests.Session | None = None
        self._min_interval: float = 1.0 / settings.http_rate_limit_rps
        self._last_call: float = 0.0

    def _ensure_session(self) -> requests.Session:
        if self._session is not None:
            return self._session
        session = requests.Session()
        session.headers.update(self._HEADERS)
        session.get(self._BASE_URL, timeout=self._settings.http_timeout_seconds)
        self._session = session
        return session

    def _throttle(self) -> None:
        gap = self._min_interval - (time.monotonic() - self._last_call)
        if gap > 0:
            time.sleep(gap)
        self._last_call = time.monotonic()

    def get_json(self, path: str, params: dict[str, Any]) -> Any:
        """GET an API endpoint and return the parsed JSON body.

        Retries up to http_max_retries times on HTTP 429. All other non-2xx
        responses raise requests.HTTPError immediately.
        """
        session = self._ensure_session()
        url = f"{self._API_BASE}/{path}"
        max_attempts = self._settings.http_max_retries + 1
        for attempt in range(max_attempts):
            self._throttle()
            resp = session.get(
                url, params=params, timeout=self._settings.http_timeout_seconds
            )
            if resp.status_code == 429 and attempt < max_attempts - 1:
                time.sleep(2.0**attempt)
                continue
            resp.raise_for_status()
            return resp.json()
        raise AssertionError("unreachable")  # pragma: no cover

    def get_bytes(self, url: str) -> bytes:
        """GET a URL and return the raw response body."""
        session = self._ensure_session()
        self._throttle()
        resp = session.get(url, timeout=self._settings.http_timeout_seconds)
        resp.raise_for_status()
        return resp.content

    def close(self) -> None:
        if self._session is not None:
            self._session.close()
            self._session = None

    def __enter__(self) -> "BSEHttpClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
