from __future__ import annotations

from datetime import date, timedelta

from src.history import eligible, load_history, prune_history, record_delivery, save_history
from src.models import Delivery, History, Paper, RecommendationRecord, Slot


def test_missing_history_file_loads_empty(tmp_path) -> None:
    history = load_history(tmp_path / "missing.json")
    assert history == History()


def test_rejects_fourth_delivery_within_seven_days() -> None:
    today = date(2026, 7, 10)
    key = "doi:10.1000/a"
    history = History(
        deliveries=[
            Delivery(key, today - timedelta(days=6), Slot.MORNING),
            Delivery(key, today - timedelta(days=3), Slot.AFTERNOON),
            Delivery(key, today - timedelta(days=1), Slot.EVENING),
        ]
    )
    assert eligible(Paper(title="A", doi="10.1000/a"), history, today) is False


def test_same_day_delivery_is_excluded_even_below_weekly_cap() -> None:
    today = date(2026, 7, 10)
    history = History(deliveries=[Delivery("doi:10.1000/a", today, Slot.MORNING)])
    assert eligible(Paper(title="A", doi="10.1000/a"), history, today) is False


def test_seven_day_window_is_inclusive_of_today_and_previous_six_days() -> None:
    today = date(2026, 7, 10)
    key = "doi:10.1000/a"
    history = History(
        deliveries=[
            Delivery(key, today - timedelta(days=7), Slot.MORNING),
            Delivery(key, today - timedelta(days=6), Slot.MORNING),
            Delivery(key, today - timedelta(days=3), Slot.MORNING),
        ]
    )
    assert eligible(Paper(title="A", doi="10.1000/a"), history, today) is True


def test_record_delivery_updates_long_term_marker_and_round_trips(tmp_path) -> None:
    today = date(2026, 7, 10)
    history = History()
    papers = [Paper(title="A", doi="10.1000/a"), Paper(title="B")]

    record_delivery(history, papers, Slot.AFTERNOON, today)
    save_history(tmp_path / "history.json", history)
    loaded = load_history(tmp_path / "history.json")

    assert len(loaded.deliveries) == 2
    assert loaded.ever_recommended["doi:10.1000/a"].count == 1
    assert loaded.ever_recommended["title:b"].last_recommended == today


def test_prune_removes_old_deliveries_but_keeps_ever_recommended() -> None:
    today = date(2026, 7, 10)
    key = "doi:10.1000/a"
    record = RecommendationRecord(today - timedelta(days=90), today - timedelta(days=31), 4)
    history = History(
        ever_recommended={key: record},
        deliveries=[
            Delivery(key, today - timedelta(days=31), Slot.MORNING),
            Delivery(key, today - timedelta(days=30), Slot.AFTERNOON),
        ],
    )

    prune_history(history, today)

    assert history.deliveries == [Delivery(key, today - timedelta(days=30), Slot.AFTERNOON)]
    assert history.ever_recommended[key] == record
