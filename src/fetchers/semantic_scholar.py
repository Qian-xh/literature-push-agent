from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

import requests

from src.config import Settings
from src.dedup import normalize_doi
from src.fetchers.base import CORE_QUERY, build_session
from src.models import Paper, Slot


LOGGER = logging.getLogger(__name__)


class SemanticScholarFetcher:
    name = "semantic_scholar"
    endpoint = "https://api.semanticscholar.org/graph/v1/paper/search"

    def __init__(self, session: requests.Session | None = None) -> None:
        self.session = session or build_session()

    def fetch(self, slot: Slot, settings: Settings, today: date) -> list[Paper]:
        params: dict[str, Any] = {
            "query": CORE_QUERY.replace('"', "").replace(" OR ", " "),
            "limit": min(settings.candidate_limit, 100),
            "fields": (
                "title,authors,year,venue,publicationDate,externalIds,url,abstract,"
                "citationCount,influentialCitationCount,publicationTypes,openAccessPdf"
            ),
        }
        if slot is Slot.MORNING:
            params["publicationDateOrYear"] = (
                f"{(today - timedelta(days=90)).isoformat()}:{today.isoformat()}"
            )
        try:
            response = self.session.get(self.endpoint, params=params, timeout=settings.http_timeout)
            response.raise_for_status()
            return [
                paper
                for item in response.json().get("data", [])
                if (paper := self._map(item)) is not None
            ]
        except (requests.RequestException, ValueError, TypeError, KeyError) as exc:
            LOGGER.warning("Semantic Scholar request failed: %s", exc)
            return []

    @staticmethod
    def _map(item: dict[str, Any]) -> Paper | None:
        title = str(item.get("title", "")).strip()
        if not title:
            return None
        external_ids = item.get("externalIds") or {}
        publication_types = item.get("publicationTypes") or []
        open_pdf = item.get("openAccessPdf") or {}
        published: date | None = None
        try:
            if item.get("publicationDate"):
                published = date.fromisoformat(str(item["publicationDate"]))
        except ValueError:
            published = None
        year_value = item.get("year") or (published.year if published else None)
        return Paper(
            title=title,
            authors=[
                str(author.get("name", "")).strip()
                for author in item.get("authors", [])
                if author.get("name")
            ],
            year=int(year_value) if year_value else None,
            journal=str(item.get("venue", "")).strip(),
            doi=normalize_doi(str(external_ids.get("DOI", ""))),
            url=str(item.get("url", "")).strip(),
            abstract=str(item.get("abstract", "") or "").strip(),
            published=published,
            cited_by=int(item.get("citationCount", 0) or 0),
            influential_citations=int(item.get("influentialCitationCount", 0) or 0),
            work_type=str(publication_types[0] if publication_types else "article").casefold(),
            sources=["semantic_scholar"],
            oa_pdf_url=str(open_pdf.get("url", "")).strip(),
        )
