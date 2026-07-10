from __future__ import annotations

import pytest

from src.config import Settings
from src.models import ALLOWED_SECTIONS, EnrichedPaper, Paper


def sample_paper() -> Paper:
    return Paper(title="Root-soil preferential flow", authors=["Qian XH"], year=2026)


def test_settings_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "RECIPIENT_EMAIL",
        "OPENAI_MODEL",
        "MAX_PAPERS",
        "DOWNLOAD_OA_PDF",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = Settings.from_env()

    assert settings.recipient_email == "qxh.igsnrr@gmail.com"
    assert settings.openai_model == "gpt-4.1-mini"
    assert settings.max_papers == 5
    assert settings.download_oa_pdf is False


def test_settings_parse_boolean_and_clamp_max_papers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAX_PAPERS", "1")
    monkeypatch.setenv("DOWNLOAD_OA_PDF", "YES")

    settings = Settings.from_env()

    assert settings.max_papers == 2
    assert settings.download_oa_pdf is True


def test_enriched_paper_rejects_invalid_priority() -> None:
    with pytest.raises(ValueError, match="priority"):
        EnrichedPaper.from_paper(
            sample_paper(),
            summary_zh="摘要",
            why_read="理由",
            dissertation_section=ALLOWED_SECTIONS[0],
            priority=6,
            keywords=["优先流"],
            endnote_group="根土结构",
        )


def test_enriched_paper_rejects_invalid_section() -> None:
    with pytest.raises(ValueError, match="dissertation_section"):
        EnrichedPaper.from_paper(
            sample_paper(),
            summary_zh="摘要",
            why_read="理由",
            dissertation_section="invalid",
            priority=4,
            keywords=["优先流"],
            endnote_group="根土结构",
        )
