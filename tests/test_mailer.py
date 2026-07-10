from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pytest

from src.config import ConfigurationError, Settings
from src.mailer import build_message, send_email
from src.models import Slot


class FakeSMTP:
    instances: list[FakeSMTP] = []

    def __init__(self, host: str, port: int, timeout: float) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.login_args: tuple[str, str] | None = None
        self.sent: Any = None
        self.instances.append(self)

    def __enter__(self) -> FakeSMTP:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def login(self, address: str, password: str) -> None:
        self.login_args = (address, password)

    def send_message(self, message: Any) -> None:
        self.sent = message


def configured_settings() -> Settings:
    return Settings(
        gmail_address="sender@gmail.com",
        gmail_app_password="app-password",
        recipient_email="recipient@example.com",
        smtp_timeout=12,
    )


def test_build_message_has_slot_subject_html_and_attachments(tmp_path: Path) -> None:
    ris = tmp_path / "papers.ris"
    ris.write_text("TY  - JOUR\nER  -\n", encoding="utf-8")
    message = build_message(
        configured_settings(),
        Slot.MORNING,
        date(2026, 7, 10),
        "<h1>文献</h1>",
        [ris],
    )
    assert message["Subject"] == "早间文献推送｜2026-07-10"
    assert message["From"] == "sender@gmail.com"
    assert message["To"] == "recipient@example.com"
    assert any(part.get_content_type() == "text/html" for part in message.walk())
    assert any(part.get_filename() == "papers.ris" for part in message.iter_attachments())


def test_missing_gmail_credentials_has_actionable_error() -> None:
    message = build_message(Settings(), Slot.AFTERNOON, date(2026, 7, 10), "<p>x</p>", [])
    with pytest.raises(ConfigurationError, match="GMAIL_ADDRESS.*GMAIL_APP_PASSWORD"):
        send_email(Settings(), message, smtp_factory=FakeSMTP)


def test_send_email_uses_gmail_smtp_ssl_login() -> None:
    FakeSMTP.instances.clear()
    settings = configured_settings()
    message = build_message(settings, Slot.EVENING, date(2026, 7, 10), "<p>x</p>", [])
    send_email(settings, message, smtp_factory=FakeSMTP)
    smtp = FakeSMTP.instances[-1]
    assert (smtp.host, smtp.port, smtp.timeout) == ("smtp.gmail.com", 465, 12)
    assert smtp.login_args == ("sender@gmail.com", "app-password")
    assert smtp.sent is message

