from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import date, timedelta
from pathlib import Path

from src.dedup import paper_key
from src.models import Delivery, History, Paper, RecommendationRecord, Slot


def load_history(path: Path) -> History:
    if not path.exists():
        return History()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ValueError(f"Unable to read valid history from {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"History root must be a JSON object: {path}")
    return History.from_dict(payload)


def save_history(path: Path, history: History) -> None:
    """Atomically replace history so interrupted runs do not corrupt state."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        json.dumps(history.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def eligible(paper: Paper, history: History, today: date) -> bool:
    key = paper_key(paper)
    cutoff = today - timedelta(days=6)
    recent = [
        delivery
        for delivery in history.deliveries
        if delivery.key == key and cutoff <= delivery.delivered_on <= today
    ]
    return len(recent) < 3 and not any(item.delivered_on == today for item in recent)


def delivered_in_slot(history: History, key: str, today: date, slot: Slot) -> bool:
    return any(
        item.key == key and item.delivered_on == today and item.slot == slot
        for item in history.deliveries
    )


def record_delivery(
    history: History,
    papers: Sequence[Paper],
    slot: Slot,
    delivered_on: date,
) -> None:
    for paper in papers:
        key = paper_key(paper)
        history.deliveries.append(Delivery(key, delivered_on, slot))
        record = history.ever_recommended.get(key)
        if record is None:
            history.ever_recommended[key] = RecommendationRecord(
                first_recommended=delivered_on,
                last_recommended=delivered_on,
            )
        else:
            record.last_recommended = delivered_on
            record.count += 1


def prune_history(history: History, today: date) -> None:
    cutoff = today - timedelta(days=30)
    history.deliveries = [
        delivery for delivery in history.deliveries if delivery.delivered_on >= cutoff
    ]

