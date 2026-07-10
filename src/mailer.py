from __future__ import annotations

import mimetypes
import smtplib
from collections.abc import Callable, Sequence
from datetime import date
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from src.config import Settings
from src.exporters import SLOT_LABELS
from src.models import Slot


def build_message(
    settings: Settings,
    slot: Slot,
    today: date,
    html_body: str,
    attachments: Sequence[Path],
) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = f"{SLOT_LABELS[slot]}｜{today.isoformat()}"
    message["From"] = settings.gmail_address or "unconfigured@gmail.com"
    message["To"] = settings.recipient_email
    message.set_content(
        "本邮件包含 HTML 格式的科研文献推送，请使用支持 HTML 的邮件客户端查看。"
    )
    message.add_alternative(html_body, subtype="html")
    for path in attachments:
        mime_type, _ = mimetypes.guess_type(path.name)
        if path.suffix.casefold() == ".ris":
            mime_type = "application/x-research-info-systems"
        maintype, subtype = (mime_type or "application/octet-stream").split("/", 1)
        message.add_attachment(
            path.read_bytes(),
            maintype=maintype,
            subtype=subtype,
            filename=path.name,
        )
    return message


def send_email(
    settings: Settings,
    message: EmailMessage,
    *,
    smtp_factory: Callable[..., Any] = smtplib.SMTP_SSL,
) -> None:
    settings.validate_mail()
    with smtp_factory("smtp.gmail.com", 465, timeout=settings.smtp_timeout) as smtp:
        smtp.login(settings.gmail_address, settings.gmail_app_password)
        smtp.send_message(message)

