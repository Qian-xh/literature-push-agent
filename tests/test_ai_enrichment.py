from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from src.ai_enrichment import enrich_and_select, fallback_enrich, validate_payload
from src.config import Settings
from src.models import ALLOWED_SECTIONS, Paper


def candidate() -> Paper:
    return Paper(
        title="Root-induced macropore flow on forested hillslopes",
        authors=["A Author"],
        year=2021,
        journal="Hydrological Processes",
        doi="10.1000/root",
        url="https://doi.org/10.1000/root",
        abstract="Roots create connected macropores that alter subsurface stormflow.",
        cited_by=25,
        score=55,
    )


def valid_item(**overrides: object) -> dict[str, object]:
    item: dict[str, object] = {
        "title": candidate().title,
        "authors": candidate().authors,
        "year": candidate().year,
        "journal": candidate().journal,
        "doi": candidate().doi,
        "url": candidate().url,
        "summary_zh": "根系形成连通大孔隙并改变坡面壤中流路径。",
        "why_read": "可用于解释根系结构如何调节优先流。",
        "dissertation_section": ALLOWED_SECTIONS[1],
        "priority": 5,
        "keywords": ["根系", "大孔隙流", "壤中流"],
        "endnote_group": "根系-优先流",
    }
    item.update(overrides)
    return item


class FakeResponses:
    def __init__(self, values: list[str]) -> None:
        self.values = list(values)
        self.calls = 0
        self.kwargs: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> SimpleNamespace:
        self.calls += 1
        self.kwargs.append(kwargs)
        return SimpleNamespace(output_text=self.values.pop(0))


class FakeClient:
    def __init__(self, values: list[str]) -> None:
        self.responses = FakeResponses(values)


def settings() -> Settings:
    return Settings(openai_api_key="test-key", max_papers=3)


def test_valid_payload_is_bound_to_original_candidate_metadata() -> None:
    payload = {"papers": [valid_item(authors=["Invented Author"], journal="Invented Journal")]}
    result = validate_payload(payload, [candidate()])
    assert result[0].authors == ["A Author"]
    assert result[0].journal == "Hydrological Processes"
    assert result[0].summary_zh.startswith("根系")


def test_invalid_json_is_retried_once_then_valid_result_is_used() -> None:
    client = FakeClient(["not json", json.dumps({"papers": [valid_item()]}, ensure_ascii=False)])
    result = enrich_and_select([candidate()], settings(), client)
    assert result[0].priority == 5
    assert client.responses.calls == 2
    assert client.responses.kwargs[0]["model"] == "gpt-4.1-mini"


def test_second_invalid_response_uses_local_fallback() -> None:
    client = FakeClient(["bad", "still bad"])
    result = enrich_and_select([candidate()], settings(), client)
    assert len(result) == 1
    assert result[0].summary_zh
    assert result[0].dissertation_section in ALLOWED_SECTIONS
    assert 1 <= result[0].priority <= 5
    assert client.responses.calls == 2


def test_missing_openai_key_uses_fallback_without_client() -> None:
    result = enrich_and_select([candidate()], Settings(openai_api_key=""), None)
    assert result == [fallback_enrich(candidate())]


def test_model_cannot_introduce_unknown_paper() -> None:
    with pytest.raises(ValueError, match="candidate"):
        validate_payload(
            {"papers": [valid_item(title="Invented", doi="10.1000/fake")]},
            [candidate()],
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("priority", 9),
        ("priority", "5"),
        ("dissertation_section", "invalid"),
        ("keywords", []),
    ],
)
def test_strict_fields_are_validated(field: str, value: object) -> None:
    with pytest.raises(ValueError):
        validate_payload({"papers": [valid_item(**{field: value})]}, [candidate()])
