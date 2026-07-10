from __future__ import annotations

from pathlib import Path

import yaml

WORKFLOW = Path(".github/workflows/literature.yml")


def load_workflow() -> dict:
    payload = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def triggers(workflow: dict) -> dict:
    value = workflow.get("on", workflow.get(True))
    assert isinstance(value, dict)
    return value


def test_workflow_has_all_crons_and_manual_slots() -> None:
    workflow = load_workflow()
    events = triggers(workflow)
    assert {item["cron"] for item in events["schedule"]} == {
        "0 1 * * *",
        "30 6 * * *",
        "30 11 * * *",
    }
    slot = events["workflow_dispatch"]["inputs"]["slot"]
    assert slot["type"] == "choice"
    assert slot["required"] is True
    assert slot["options"] == ["morning", "afternoon", "evening"]


def test_workflow_has_permissions_timeout_tests_artifacts_and_history_commit() -> None:
    workflow = load_workflow()
    assert workflow["permissions"]["contents"] == "write"
    job = workflow["jobs"]["literature-push"]
    assert job["timeout-minutes"] <= 30
    steps = job["steps"]
    text = WORKFLOW.read_text(encoding="utf-8")
    assert any(step.get("uses") == "actions/checkout@v7" for step in steps)
    assert any(step.get("uses") == "actions/setup-python@v6" for step in steps)
    assert "python -m pytest" in text
    assert "python -m ruff check" in text
    assert "python -m src.main" in text
    assert "actions/upload-artifact@v7" in text
    assert "if: always()" in text
    assert "data/history.json" in text
    assert "git push" in text


def test_workflow_exposes_required_secrets_and_variables() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    for secret in ("OPENAI_API_KEY", "GMAIL_ADDRESS", "GMAIL_APP_PASSWORD"):
        assert f"secrets.{secret}" in text
    for variable in ("RECIPIENT_EMAIL", "OPENAI_MODEL", "MAX_PAPERS", "DOWNLOAD_OA_PDF"):
        assert f"vars.{variable}" in text
