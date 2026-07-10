from __future__ import annotations

import logging
import re
from datetime import date, timedelta
from typing import Any

import requests

from src.config import Settings
from src.fetchers.base import CORE_QUERY, build_session
from src.models import Paper, Slot


LOGGER = logging.getLogger(__name__)
TAG_PATTERN = re.compile(r"<[^>]+>")


def _first(value: Any) -> str:
    if isinstance(value, list) and value:
        return str(value[0])
    return str(value or "")


def _published(item: dict[str, Any]) -> date | None:
    for field in ("published-print", "published-online", "published", "issued"):
        parts = item.get(field, {}).get("date-parts", [])
        if not parts or not parts[0]:
            continue
        values = [int(value) for value in parts[0]]
        try:
            return date(values[0], values[1] if len(values) > 1 else 1, values[2] if len(values) > 2 else 1)
        except (ValueError, TypeError):
            continue
    return None


def _authors(item: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for author in item.get("author", []):
        name = str(author.get("name", "")).strip()
        if not name:
            name = " ".join(
                value
                for value in (
                    str(author.get("given", "")).strip(),
                    str(author.get("family", "")).strip(),
                )
                if value
            )
        if name:
            result.append(name)
    return result


class CrossrefFetcher:
    name = "crossref"
    endpoint = "https://api.crossref.org/works"

    def __init__(self, session: requests.Session | None = None) -> None:
        self.session = session or build_session()

    def fetch(self, slot: Slot, settings: Settings, today: date) -> list[Paper]:
        filters = ["type:journal-article"]
        if slot is Slot.MORNING:
            filters.extend(
                (
                    f"from-pub-date:{(today - timedelta(days=90)).isoformat()}",
                    f"until-pub-date:{today.isoformat()}",
                )
            )
        params = {
            "query.bibliographic": CORE_QUERY,
            "filter": ",".join(filters),
            "rows": settings.candidate_limit,
            "sort": "published" if slot is Slot.MORNING else "relevance",
            "order": "desc",
        }
        if settings.gmail_address:
            params["mailto"] = settings.gmail_address
        try:
            response = self.session.get(self.endpoint, params=params, timeout=settings.http_timeout)
            response.raise_for_status()
            items = response.json().get("message", {}).get("items", [])
            return [paper for item in items if (paper := self._map(item)) is not None]
        except (requests.RequestException, ValueError, TypeError, KeyError) as exc:
            LOGGER.warning("Crossref request failed: %s", exc)
            return []

    @staticmethod
    def _map(item: dict[str, Any]) -> Paper | None:
        title = _first(item.get("title")).strip()
        if not title:
            return None
        published = _published(item)
        abstract = TAG_PATTERN.sub(" ", str(item.get("abstract", "")))
        return Paper(
            title=" ".join(title.split()),
            authors=_authors(item),
            year=published.year if published else None,
            journal=_first(item.get("container-title")).strip(),
            doi=str(item.get("DOI", "")).strip(),
            url=str(item.get("URL", "")).strip(),
            abstract=" ".join(abstract.split()),
            published=published,
            cited_by=int(item.get("is-referenced-by-count", 0) or 0),
            work_type=str(item.get("subtype") or item.get("type") or "article"),
            sources=["crossref"],
        )

