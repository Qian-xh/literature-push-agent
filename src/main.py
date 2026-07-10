from __future__ import annotations

import argparse
import logging
import smtplib
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from src.ai_enrichment import enrich_and_select, fallback_enrich
from src.config import Settings
from src.dedup import deduplicate, paper_key
from src.exporters import download_oa_pdfs, render_html, write_bibtex, write_csv, write_ris
from src.fetchers import CrossrefFetcher, OpenAlexFetcher, SemanticScholarFetcher
from src.fetchers.base import Fetcher
from src.history import load_history, prune_history, record_delivery, save_history
from src.mailer import build_message, send_email
from src.models import EnrichedPaper, Paper, Slot
from src.ranking import rank_papers

LOGGER = logging.getLogger(__name__)


def _beijing_today() -> date:
    from datetime import datetime

    return datetime.now(ZoneInfo("Asia/Shanghai")).date()


def _default_fetchers() -> list[Fetcher]:
    return [CrossrefFetcher(), OpenAlexFetcher(), SemanticScholarFetcher()]


@dataclass(slots=True)
class Dependencies:
    fetchers: Sequence[Fetcher] = field(default_factory=_default_fetchers)
    smtp_factory: Callable[..., Any] = smtplib.SMTP_SSL
    today_fn: Callable[[], date] = _beijing_today
    ai_client: Any | None = None
    pdf_session: Any | None = None


def _morning_pool(ranked: list[Paper], today: date) -> list[Paper]:
    recent = [
        paper
        for paper in ranked
        if paper.published is not None and 0 <= (today - paper.published).days <= 45
    ]
    return recent if len(recent) >= 2 else ranked


def _ensure_delivery_count(
    enriched: list[EnrichedPaper], ranked: Sequence[Paper], target_count: int
) -> list[EnrichedPaper]:
    result = list(enriched[:target_count])
    used = {paper_key(paper) for paper in result}
    for paper in ranked:
        if len(result) >= target_count:
            break
        if paper_key(paper) not in used:
            result.append(fallback_enrich(paper))
            used.add(paper_key(paper))
    return result


def _collect(
    fetchers: Sequence[Fetcher],
    slot: Slot,
    settings: Settings,
    today: date,
) -> list[Paper]:
    candidates: list[Paper] = []
    for fetcher in fetchers:
        try:
            papers = fetcher.fetch(slot, settings, today)
            LOGGER.info("Fetcher %s returned %d papers", fetcher.name, len(papers))
            candidates.extend(papers)
        except Exception as exc:  # A third-party adapter must never block healthy sources.
            LOGGER.warning("Fetcher %s failed: %s", fetcher.name, exc)
    return deduplicate(candidates)


def _export(
    papers: Sequence[EnrichedPaper],
    slot: Slot,
    today: date,
    settings: Settings,
    dependencies: Dependencies,
) -> tuple[str, list[Path]]:
    settings.output_dir.mkdir(parents=True, exist_ok=True)
    prefix = f"{today.isoformat()}-{slot.value}"
    html_body = render_html(papers, slot, today)
    html_path = settings.output_dir / f"{prefix}.html"
    html_path.write_text(html_body, encoding="utf-8")
    attachments = [
        write_ris(papers, settings.output_dir / f"{prefix}.ris"),
        write_csv(papers, settings.output_dir / f"{prefix}.csv"),
        write_bibtex(papers, settings.output_dir / f"{prefix}.bib"),
    ]
    base_size = sum(path.stat().st_size for path in attachments)
    if settings.download_oa_pdf:
        attachments.extend(
            download_oa_pdfs(
                papers,
                settings.output_dir / f"{prefix}-pdfs",
                session=dependencies.pdf_session,
                timeout=settings.http_timeout,
                max_pdf_bytes=settings.max_pdf_bytes,
                remaining_attachment_bytes=max(0, settings.max_attachment_bytes - base_size),
            )
        )
    return html_body, attachments


def run(
    slot: Slot,
    settings: Settings | None = None,
    dependencies: Dependencies | None = None,
) -> int:
    runtime_settings = settings or Settings.from_env()
    deps = dependencies or Dependencies()
    today = deps.today_fn()
    try:
        history = load_history(runtime_settings.history_path)
        prune_history(history, today)
        candidates = _collect(deps.fetchers, slot, runtime_settings, today)
        if not candidates:
            raise RuntimeError("All literature sources failed or returned no candidates")
        ranked = rank_papers(candidates, slot, history, today)
        if slot is Slot.MORNING:
            ranked = _morning_pool(ranked, today)
        if len(ranked) < 2:
            raise RuntimeError(
                f"Only {len(ranked)} eligible paper(s) remain; at least 2 are required"
            )
        target_count = min(runtime_settings.delivery_count, len(ranked))
        candidate_pool = ranked[: max(target_count * 4, target_count)]
        enriched = enrich_and_select(candidate_pool, runtime_settings, deps.ai_client)
        selected = _ensure_delivery_count(enriched, ranked, target_count)
        if len(selected) < 2:
            raise RuntimeError("Enrichment produced fewer than 2 deliverable papers")
        html_body, attachments = _export(selected, slot, today, runtime_settings, deps)
        message = build_message(runtime_settings, slot, today, html_body, attachments)
        send_email(runtime_settings, message, smtp_factory=deps.smtp_factory)
        record_delivery(history, selected, slot, today)
        prune_history(history, today)
        save_history(runtime_settings.history_path, history)
        LOGGER.info("Delivered %d papers for %s", len(selected), slot.value)
        return 0
    except Exception:
        LOGGER.exception("Literature push failed for slot %s", slot.value)
        return 1


def configure_logging(settings: Settings) -> None:
    settings.log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(settings.log_path, encoding="utf-8"),
        ],
        force=True,
    )


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scheduled research literature push agent")
    parser.add_argument("--slot", choices=[slot.value for slot in Slot], required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    settings = Settings.from_env()
    configure_logging(settings)
    return run(Slot(args.slot), settings)


if __name__ == "__main__":
    raise SystemExit(main())
