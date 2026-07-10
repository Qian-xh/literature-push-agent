from __future__ import annotations

from datetime import date
from typing import Protocol

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from src.config import Settings
from src.models import Paper, Slot


USER_AGENT = "literature-push-agent/0.1 (+https://github.com/Qian-xh/literature-push-agent)"
CORE_QUERY = (
    '"hillslope hydrology" OR "root soil" OR "preferential flow" OR '
    '"macropore flow" OR "subsurface stormflow" OR interflow OR '
    '"hydrological connectivity" OR "root architecture"'
)


class Fetcher(Protocol):
    name: str

    def fetch(self, slot: Slot, settings: Settings, today: date) -> list[Paper]: ...


def build_session() -> requests.Session:
    retry = Retry(
        total=3,
        connect=3,
        read=3,
        backoff_factor=0.8,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session

