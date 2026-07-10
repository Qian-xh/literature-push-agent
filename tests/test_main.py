from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from src.config import Settings
from src.history import load_history
from src.main import Dependencies, run
from src.models import Paper, Slot

TODAY = date(2026, 7, 10)


def papers() -> list[Paper]:
    return [
        Paper(
            title=f"Root soil preferential flow study {index}",
            authors=[f"Author {index}"],
            year=2020 + index,
            journal="Hydrology",
            doi=f"10.1000/{index}",
            url=f"https://doi.org/10.1000/{index}",
            abstract="Root macropore hydrological connectivity and subsurface stormflow.",
            cited_by=index * 10,
        )
        for index in range(1, 4)
    ]


class StaticFetcher:
    name = "static"

    def __init__(self, values: list[Paper]) -> None:
        self.values = values

    def fetch(self, slot: Slot, settings: Settings, today: date) -> list[Paper]:
        return self.values


class FailingFetcher:
    name = "failing"

    def fetch(self, slot: Slot, settings: Settings, today: date) -> list[Paper]:
        raise RuntimeError("source unavailable")


class FakeSMTP:
    fail = False

    def __init__(self, host: str, port: int, timeout: float) -> None:
        self.host = host

    def __enter__(self) -> FakeSMTP:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def login(self, address: str, password: str) -> None:
        if self.fail:
            raise RuntimeError("smtp failed")

    def send_message(self, message: Any) -> None:
        return None


def settings(tmp_path: Path) -> Settings:
    return Settings(
        gmail_address="sender@gmail.com",
        gmail_app_password="app-password",
        recipient_email="recipient@example.com",
        output_dir=tmp_path / "output",
        history_path=tmp_path / "data" / "history.json",
        log_path=tmp_path / "output" / "agent.log",
    )


def dependencies(fetchers: list[Any]) -> Dependencies:
    return Dependencies(fetchers=fetchers, smtp_factory=FakeSMTP, today_fn=lambda: TODAY)


def test_history_is_not_updated_when_smtp_fails_but_exports_remain(tmp_path: Path) -> None:
    FakeSMTP.fail = True
    result = run(Slot.MORNING, settings(tmp_path), dependencies([StaticFetcher(papers())]))
    FakeSMTP.fail = False

    assert result == 1
    assert load_history(settings(tmp_path).history_path).deliveries == []
    assert list(settings(tmp_path).output_dir.glob("*.ris"))
    assert list(settings(tmp_path).output_dir.glob("*.csv"))


def test_history_is_updated_only_after_smtp_success(tmp_path: Path) -> None:
    FakeSMTP.fail = False
    result = run(Slot.AFTERNOON, settings(tmp_path), dependencies([StaticFetcher(papers())]))
    history = load_history(settings(tmp_path).history_path)
    assert result == 0
    assert len(history.deliveries) == 3
    assert {delivery.slot for delivery in history.deliveries} == {Slot.AFTERNOON}


def test_one_fetcher_failure_does_not_stop_other_sources(tmp_path: Path, caplog) -> None:
    result = run(
        Slot.EVENING,
        settings(tmp_path),
        dependencies([FailingFetcher(), StaticFetcher(papers())]),
    )
    assert result == 0
    assert "Fetcher failing failed" in caplog.text


def test_fewer_than_two_eligible_papers_fails_without_sending(tmp_path: Path) -> None:
    result = run(
        Slot.MORNING,
        settings(tmp_path),
        dependencies([StaticFetcher(papers()[:1])]),
    )
    assert result == 1
    assert not settings(tmp_path).history_path.exists()
