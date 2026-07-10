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


def _abstract(index: Any) -> str:
    if not isinstance(index, dict):
        return ""
    positioned: list[tuple[int, str]] = []
    for word, positions in index.items():
        if isinstance(positions, list):
            positioned.extend((int(position), str(word)) for position in positions)
    return " ".join(word for _, word in sorted(positioned))


def _parse_date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)) if value else None
    except ValueError:
        return None


class OpenAlexFetcher:
    name = "openalex"
    endpoint = "https://api.openalex.org/works"

    def __init__(self, session: requests.Session | None = None) -> None:
        self.session = session or build_session()

    def fetch(self, slot: Slot, settings: Settings, today: date) -> list[Paper]:
        filters: list[str] = []
        if slot is Slot.MORNING:
            filters.extend(
                (
                    f"from_publication_date:{(today - timedelta(days=90)).isoformat()}",
                    f"to_publication_date:{today.isoformat()}",
                )
            )
        params: dict[str, Any] = {
            "search": CORE_QUERY.replace('"', ""),
            "per-page": settings.candidate_limit,
            "sort": "publication_date:desc" if slot is Slot.MORNING else "cited_by_count:desc",
        }
        if filters:
            params["filter"] = ",".join(filters)
        if settings.gmail_address:
            params["mailto"] = settings.gmail_address
        try:
            response = self.session.get(self.endpoint, params=params, timeout=settings.http_timeout)
            response.raise_for_status()
            return [
                paper
                for item in response.json().get("results", [])
                if (paper := self._map(item)) is not None
            ]
        except (requests.RequestException, ValueError, TypeError, KeyError) as exc:
            LOGGER.warning("OpenAlex request failed: %s", exc)
            return []

    @staticmethod
    def _map(item: dict[str, Any]) -> Paper | None:
        title = str(item.get("title", "")).strip()
        if not title:
            return None
        location = item.get("primary_location") or {}
        source = location.get("source") or {}
        open_access = item.get("open_access") or {}
        best_oa = item.get("best_oa_location") or {}
        is_oa = bool(open_access.get("is_oa"))
        published = _parse_date(item.get("publication_date"))
        authors = [
            str(authorship.get("author", {}).get("display_name", "")).strip()
            for authorship in item.get("authorships", [])
        ]
        concepts = [
            str(concept.get("display_name", "")).strip()
            for concept in item.get("concepts", [])
            if float(concept.get("score", 0) or 0) >= 0.5
        ]
        year_value = item.get("publication_year") or (published.year if published else None)
        return Paper(
            title=title,
            authors=[author for author in authors if author],
            year=int(year_value) if year_value else None,
            journal=str(source.get("display_name", "")).strip(),
            doi=normalize_doi(str(item.get("doi", ""))),
            url=str(location.get("landing_page_url") or item.get("id") or "").strip(),
            abstract=_abstract(item.get("abstract_inverted_index")),
            keywords=[concept for concept in concepts if concept],
            published=published,
            cited_by=int(item.get("cited_by_count", 0) or 0),
            work_type=str(item.get("type", "article") or "article"),
            sources=["openalex"],
            oa_pdf_url=str(best_oa.get("pdf_url", "")).strip() if is_oa else "",
        )
