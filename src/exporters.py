from __future__ import annotations

import csv
import hashlib
import html
import logging
import re
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Any

import requests

from src.dedup import normalize_doi, normalize_title, paper_key
from src.fetchers.base import build_session
from src.models import EnrichedPaper, Slot

LOGGER = logging.getLogger(__name__)
CSV_FIELDS = [
    "title",
    "authors",
    "year",
    "journal",
    "doi",
    "url",
    "keywords",
    "dissertation_section",
    "priority",
    "endnote_group",
    "summary_zh",
    "why_read",
]

SLOT_LABELS = {
    Slot.MORNING: "早间文献推送",
    Slot.AFTERNOON: "午后文献推送",
    Slot.EVENING: "晚间文献推送",
}


def _single_line(value: object) -> str:
    return " ".join(str(value or "").replace("\r", " ").replace("\n", " ").split())


def _citation_url(paper: EnrichedPaper) -> str:
    if paper.url:
        return paper.url
    doi = normalize_doi(paper.doi)
    return f"https://doi.org/{doi}" if doi else ""


def render_html(papers: Sequence[EnrichedPaper], slot: Slot, today: date) -> str:
    cards: list[str] = []
    for index, paper in enumerate(papers, start=1):
        authors = "、".join(paper.authors) or "作者信息暂缺"
        year = str(paper.year or "年份暂缺")
        url = _citation_url(paper)
        link = (
            f'<a href="{html.escape(url, quote=True)}" style="color:#165d8c">打开文献</a>'
            if url
            else "暂无链接"
        )
        oa_link = (
            f' · <a href="{html.escape(paper.oa_pdf_url, quote=True)}" '
            'style="color:#24734a">开放获取 PDF</a>'
            if paper.oa_pdf_url
            else ""
        )
        stars = "★" * paper.priority + "☆" * (5 - paper.priority)
        keywords = "、".join(paper.keywords)
        safe_journal = html.escape(paper.journal or "暂缺")
        safe_doi = html.escape(normalize_doi(paper.doi) or "暂缺")
        safe_summary = html.escape(paper.summary_zh)
        safe_reason = html.escape(paper.why_read)
        safe_section = html.escape(paper.dissertation_section)
        safe_group = html.escape(paper.endnote_group)
        cards.append(
            f"""
            <section style="background:#ffffff;border:1px solid #dbe5ec;border-radius:10px;
              padding:18px 20px;margin:14px 0;box-shadow:0 1px 3px rgba(0,0,0,.05)">
              <div style="font-size:13px;color:#637381">推荐 {index}</div>
              <h2 style="font-size:19px;line-height:1.45;margin:5px 0 8px;color:#14364a">
                {html.escape(paper.title)}</h2>
              <p style="margin:5px 0;color:#415462">{html.escape(authors)}（{year}）</p>
              <p style="margin:5px 0"><strong>期刊/来源：</strong>{safe_journal}</p>
              <p style="margin:5px 0"><strong>DOI：</strong>
                {safe_doi} · {link}{oa_link}</p>
              <p style="margin:10px 0 5px"><strong>核心内容：</strong>
                {safe_summary}</p>
              <p style="margin:5px 0"><strong>为什么值得读：</strong>{safe_reason}</p>
              <p style="margin:5px 0"><strong>对应论文章节：</strong>{safe_section}</p>
              <p style="margin:5px 0"><strong>阅读优先级：</strong>
                <span style="color:#df8b17">{stars}</span></p>
              <p style="margin:5px 0"><strong>推荐关键词：</strong>{html.escape(keywords)}</p>
              <p style="margin:5px 0"><strong>建议 EndNote 分组：</strong>{safe_group}</p>
            </section>
            """
        )
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"></head>
<body style="margin:0;background:#f3f7f9;
  font-family:Arial,'Microsoft YaHei',sans-serif;color:#243746">
  <main style="max-width:760px;margin:auto;padding:24px">
    <header style="background:#174f6d;color:white;border-radius:12px;padding:22px">
      <h1 style="margin:0;font-size:25px">{SLOT_LABELS[slot]}｜{today.isoformat()}</h1>
      <p style="margin:8px 0 0;opacity:.9">横断山根土复合体—壤中流研究定向推荐</p>
    </header>
    {''.join(cards)}
    <footer style="font-size:12px;color:#6b7c87;margin-top:18px">
      本邮件由 literature-push-agent 自动生成；请以论文原文为准。
    </footer>
  </main>
</body></html>"""


def write_ris(papers: Sequence[EnrichedPaper], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    records: list[str] = []
    for paper in papers:
        lines = ["TY  - JOUR", f"TI  - {_single_line(paper.title)}"]
        lines.extend(f"AU  - {_single_line(author)}" for author in paper.authors)
        lines.extend(
            (
                f"PY  - {paper.year or ''}",
                f"JO  - {_single_line(paper.journal)}",
                f"DO  - {normalize_doi(paper.doi)}",
                f"UR  - {_single_line(_citation_url(paper))}",
                f"AB  - {_single_line(paper.summary_zh)}",
            )
        )
        lines.extend(f"KW  - {_single_line(keyword)}" for keyword in paper.keywords)
        note = (
            f"对应论文章节：{paper.dissertation_section}；优先级：{paper.priority}/5；"
            f"EndNote分组：{paper.endnote_group}；推荐理由：{paper.why_read}"
        )
        lines.extend((f"N1  - {_single_line(note)}", "ER  -", ""))
        records.append("\n".join(lines))
    path.write_text("\n".join(records), encoding="utf-8")
    return path


def _csv_row(paper: EnrichedPaper) -> dict[str, str | int | None]:
    return {
        "title": paper.title,
        "authors": "; ".join(paper.authors),
        "year": paper.year,
        "journal": paper.journal,
        "doi": normalize_doi(paper.doi),
        "url": _citation_url(paper),
        "keywords": "；".join(paper.keywords),
        "dissertation_section": paper.dissertation_section,
        "priority": paper.priority,
        "endnote_group": paper.endnote_group,
        "summary_zh": paper.summary_zh,
        "why_read": paper.why_read,
    }


def write_csv(papers: Sequence[EnrichedPaper], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(_csv_row(paper) for paper in papers)
    return path


def _bibtex_escape(value: object) -> str:
    text = _single_line(value).replace("\\", "\\textbackslash{}")
    for character in ("&", "%", "$", "#", "_", "{", "}"):
        text = text.replace(character, f"\\{character}")
    return text


def _bibtex_key(paper: EnrichedPaper) -> str:
    author = normalize_title(paper.authors[0]).split()[0] if paper.authors else "anon"
    title_word = normalize_title(paper.title).split()[0] if paper.title else "paper"
    digest = hashlib.sha1(paper_key(paper).encode("utf-8")).hexdigest()[:6]
    return f"{author}{paper.year or 'nd'}{title_word}{digest}"


def write_bibtex(papers: Sequence[EnrichedPaper], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    records: list[str] = []
    for paper in papers:
        note_value = (
            f"{paper.dissertation_section}; priority {paper.priority}/5; "
            f"{paper.endnote_group}"
        )
        fields = {
            "title": paper.title,
            "author": " and ".join(paper.authors),
            "year": paper.year or "",
            "journal": paper.journal,
            "doi": normalize_doi(paper.doi),
            "url": _citation_url(paper),
            "abstract": paper.summary_zh,
            "keywords": ", ".join(paper.keywords),
            "note": note_value,
        }
        rendered = ",\n".join(
            f"  {name} = {{{_bibtex_escape(value)}}}" for name, value in fields.items() if value
        )
        records.append(f"@article{{{_bibtex_key(paper)},\n{rendered}\n}}")
    path.write_text("\n\n".join(records) + "\n", encoding="utf-8")
    return path


def _safe_pdf_name(paper: EnrichedPaper, index: int) -> str:
    clean = re.sub(r"[^\w\- ]+", "", normalize_title(paper.title), flags=re.UNICODE)
    clean = re.sub(r"\s+", "_", clean).strip("_")[:55] or "paper"
    digest = hashlib.sha1(paper_key(paper).encode("utf-8")).hexdigest()[:8]
    return f"{index:02d}_{clean}_{digest}.pdf"


def download_oa_pdfs(
    papers: Sequence[EnrichedPaper],
    output_dir: Path,
    *,
    session: Any | None = None,
    timeout: tuple[float, float] = (5.0, 25.0),
    max_pdf_bytes: int = 8 * 1024 * 1024,
    remaining_attachment_bytes: int = 18 * 1024 * 1024,
) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    http = session or build_session()
    downloaded: list[Path] = []
    remaining = max(0, remaining_attachment_bytes)
    for index, paper in enumerate(papers, start=1):
        if not paper.oa_pdf_url or remaining <= 0:
            continue
        path = output_dir / _safe_pdf_name(paper, index)
        partial = path.with_suffix(".pdf.part")
        try:
            with http.get(
                paper.oa_pdf_url,
                timeout=timeout,
                stream=True,
                allow_redirects=True,
            ) as response:
                response.raise_for_status()
                content_type = str(response.headers.get("Content-Type", "")).casefold()
                declared = int(response.headers.get("Content-Length", 0) or 0)
                limit = min(max_pdf_bytes, remaining)
                if "application/pdf" not in content_type:
                    raise ValueError(f"unexpected content type {content_type or 'unknown'}")
                if declared and declared > limit:
                    raise ValueError(f"PDF is too large ({declared} bytes)")
                size = 0
                with partial.open("wb") as handle:
                    for chunk in response.iter_content(chunk_size=64 * 1024):
                        if not chunk:
                            continue
                        size += len(chunk)
                        if size > limit:
                            raise ValueError(f"PDF exceeded {limit} byte limit")
                        handle.write(chunk)
                if size < 4 or partial.read_bytes()[:4] != b"%PDF":
                    raise ValueError("download did not have a PDF signature")
                partial.replace(path)
                downloaded.append(path)
                remaining -= size
        except (requests.RequestException, OSError, ValueError) as exc:
            partial.unlink(missing_ok=True)
            path.unlink(missing_ok=True)
            LOGGER.warning("OA PDF download failed for %s: %s", paper.title, exc)
    return downloaded
