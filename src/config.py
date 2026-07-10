from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


RESEARCH_TOPIC = "横断山不同植被带根土复合体对壤中流演化过程的调控机制"

SEARCH_TERMS: tuple[str, ...] = (
    "hillslope hydrology root soil preferential flow",
    "root soil complex macropore flow interflow",
    "subsurface stormflow hydrological connectivity",
    "root architecture soil hydraulic properties",
    "Hengduan Mountains ecohydrology mountain hazards",
    "runoff generation soil water pathways root induced soil structure",
)


class ConfigurationError(ValueError):
    """Raised when required runtime configuration is invalid or missing."""


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be an integer") from exc


@dataclass(slots=True)
class Settings:
    openai_api_key: str = ""
    openai_model: str = "gpt-4.1-mini"
    gmail_address: str = ""
    gmail_app_password: str = ""
    recipient_email: str = "qxh.igsnrr@gmail.com"
    max_papers: int = 5
    download_oa_pdf: bool = False
    http_timeout: tuple[float, float] = (5.0, 25.0)
    smtp_timeout: float = 30.0
    candidate_limit: int = 36
    output_dir: Path = field(default_factory=lambda: Path("output"))
    history_path: Path = field(default_factory=lambda: Path("data/history.json"))
    log_path: Path = field(default_factory=lambda: Path("output/agent.log"))
    max_pdf_bytes: int = 8 * 1024 * 1024
    max_attachment_bytes: int = 18 * 1024 * 1024

    @property
    def delivery_count(self) -> int:
        return min(3, self.max_papers)

    @classmethod
    def from_env(cls) -> Settings:
        max_papers = max(2, min(5, _env_int("MAX_PAPERS", 5)))
        return cls(
            openai_api_key=os.getenv("OPENAI_API_KEY", "").strip(),
            openai_model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini").strip()
            or "gpt-4.1-mini",
            gmail_address=os.getenv("GMAIL_ADDRESS", "").strip(),
            gmail_app_password=os.getenv("GMAIL_APP_PASSWORD", "").replace(" ", "").strip(),
            recipient_email=os.getenv("RECIPIENT_EMAIL", "qxh.igsnrr@gmail.com").strip()
            or "qxh.igsnrr@gmail.com",
            max_papers=max_papers,
            download_oa_pdf=_env_bool("DOWNLOAD_OA_PDF"),
            candidate_limit=max(10, _env_int("CANDIDATE_LIMIT", 36)),
            max_pdf_bytes=max(1, _env_int("MAX_PDF_MB", 8)) * 1024 * 1024,
            max_attachment_bytes=max(5, _env_int("MAX_ATTACHMENT_MB", 18)) * 1024 * 1024,
        )

    def validate_mail(self) -> None:
        missing = [
            name
            for name, value in (
                ("GMAIL_ADDRESS", self.gmail_address),
                ("GMAIL_APP_PASSWORD", self.gmail_app_password),
            )
            if not value
        ]
        if missing:
            joined = ", ".join(missing)
            raise ConfigurationError(
                f"Missing required Gmail credentials: {joined}. Configure repository Secrets."
            )
