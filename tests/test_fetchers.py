from __future__ import annotations

from datetime import date
from typing import Any

import requests

from src.config import Settings
from src.fetchers.base import build_session
from src.fetchers.crossref import CrossrefFetcher
from src.fetchers.openalex import OpenAlexFetcher
from src.fetchers.semantic_scholar import SemanticScholarFetcher
from src.models import Slot


class FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self.payload


class FakeSession:
    def __init__(
        self,
        responses: list[dict[str, Any]] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.responses = list(responses or [])
        self.error = error
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append((url, kwargs))
        if self.error is not None:
            raise self.error
        return FakeResponse(self.responses.pop(0))


def settings() -> Settings:
    return Settings(candidate_limit=20, http_timeout=(2.0, 7.0))


def test_retry_session_covers_transient_statuses() -> None:
    session = build_session()
    retries = session.get_adapter("https://").max_retries
    assert retries.total == 3
    assert {429, 500, 502, 503, 504}.issubset(set(retries.status_forcelist))


def test_crossref_maps_doi_authors_date_and_timeout() -> None:
    session = FakeSession(
        [
            {
                "message": {
                    "items": [
                        {
                            "DOI": "10.1000/ABC",
                            "title": ["Root flow"],
                            "author": [
                                {"given": "Ada", "family": "Lovelace"},
                                {"name": "Research Group"},
                            ],
                            "published": {"date-parts": [[2026, 7, 1]]},
                            "container-title": ["Hydrology Journal"],
                            "URL": "https://doi.org/10.1000/ABC",
                            "abstract": "<jats:p>Preferential flow.</jats:p>",
                            "is-referenced-by-count": 12,
                            "type": "journal-article",
                        }
                    ]
                }
            }
        ]
    )
    result = CrossrefFetcher(session).fetch(Slot.MORNING, settings(), date(2026, 7, 10))

    assert len(result) == 1
    assert result[0].doi == "10.1000/ABC"
    assert result[0].authors == ["Ada Lovelace", "Research Group"]
    assert result[0].published == date(2026, 7, 1)
    assert result[0].journal == "Hydrology Journal"
    assert result[0].sources == ["crossref"]
    assert session.calls[0][1]["timeout"] == (2.0, 7.0)
    assert "from-pub-date" in session.calls[0][1]["params"]["filter"]


def test_openalex_maps_citations_abstract_type_and_oa_pdf() -> None:
    session = FakeSession(
        [
            {
                "results": [
                    {
                        "title": "Root pathways",
                        "doi": "https://doi.org/10.1000/root",
                        "publication_year": 2020,
                        "publication_date": "2020-06-02",
                        "authorships": [
                            {"author": {"display_name": "A Author"}},
                        ],
                        "primary_location": {
                            "landing_page_url": "https://example.org/root",
                            "source": {"display_name": "Water Resources Research"},
                        },
                        "cited_by_count": 44,
                        "type": "review",
                        "abstract_inverted_index": {
                            "Root": [0],
                            "flow": [1],
                            "pathways": [2],
                        },
                        "open_access": {"is_oa": True},
                        "best_oa_location": {
                            "pdf_url": "https://example.org/root.pdf",
                        },
                        "concepts": [{"display_name": "Hydrology", "score": 0.9}],
                    }
                ]
            }
        ]
    )

    result = OpenAlexFetcher(session).fetch(Slot.EVENING, settings(), date(2026, 7, 10))

    assert result[0].doi == "10.1000/root"
    assert result[0].abstract == "Root flow pathways"
    assert result[0].cited_by == 44
    assert result[0].work_type == "review"
    assert result[0].oa_pdf_url == "https://example.org/root.pdf"
    assert result[0].keywords == ["Hydrology"]
    assert session.calls[0][1]["timeout"] == (2.0, 7.0)


def test_openalex_does_not_expose_pdf_when_work_is_not_oa() -> None:
    session = FakeSession(
        [
            {
                "results": [
                    {
                        "title": "Closed paper",
                        "open_access": {"is_oa": False},
                        "best_oa_location": {"pdf_url": "https://example.org/closed.pdf"},
                    }
                ]
            }
        ]
    )
    result = OpenAlexFetcher(session).fetch(Slot.AFTERNOON, settings(), date(2026, 7, 10))
    assert result[0].oa_pdf_url == ""


def test_openalex_keeps_publication_year_when_exact_date_is_missing() -> None:
    session = FakeSession(
        [{"results": [{"title": "Year only", "publication_year": 2012}]}]
    )
    result = OpenAlexFetcher(session).fetch(Slot.AFTERNOON, settings(), date(2026, 7, 10))
    assert result[0].year == 2012


def test_semantic_scholar_timeout_returns_no_results(caplog) -> None:
    session = FakeSession(error=requests.Timeout("slow"))
    result = SemanticScholarFetcher(session).fetch(
        Slot.AFTERNOON, settings(), date(2026, 7, 10)
    )
    assert result == []
    assert "Semantic Scholar request failed" in caplog.text
