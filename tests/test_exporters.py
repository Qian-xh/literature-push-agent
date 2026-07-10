from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from src.exporters import (
    CSV_FIELDS,
    download_oa_pdfs,
    render_html,
    write_bibtex,
    write_csv,
    write_ris,
)
from src.models import ALLOWED_SECTIONS, EnrichedPaper, Paper, Slot


def enriched_paper(**overrides: Any) -> EnrichedPaper:
    paper_values: dict[str, Any] = {
        "title": "Root & soil {flow}",
        "authors": ["Qian XH", "Smith J"],
        "year": 2026,
        "journal": "Hydrological Processes",
        "doi": "10.1000/root",
        "url": "https://doi.org/10.1000/root?x=1&y=2",
        "abstract": "Roots create macropores.",
        "oa_pdf_url": "https://example.org/root.pdf",
    }
    enriched_values: dict[str, Any] = {
        "summary_zh": "根系形成大孔隙并改变壤中流。",
        "why_read": "揭示结构与路径之间的联系。",
        "dissertation_section": ALLOWED_SECTIONS[1],
        "priority": 4,
        "keywords": ["根土复合体", "优先流"],
        "endnote_group": "根系-优先流",
    }
    for key, value in overrides.items():
        if key in paper_values:
            paper_values[key] = value
        else:
            enriched_values[key] = value
    return EnrichedPaper.from_paper(Paper(**paper_values), **enriched_values)


def test_ris_contains_required_fields_and_note(tmp_path: Path) -> None:
    path = write_ris([enriched_paper()], tmp_path / "papers.ris")
    text = path.read_text(encoding="utf-8")
    required_tags = (
        "TY  -",
        "TI  -",
        "AU  -",
        "PY  -",
        "JO  -",
        "DO  -",
        "UR  -",
        "AB  -",
        "KW  -",
        "N1  -",
        "ER  -",
    )
    for tag in required_tags:
        assert tag in text
    assert "3.2 根系调控下坡面多路径水分传输过程" in text
    assert "优先级：4/5" in text
    assert "EndNote分组：根系-优先流" in text
    assert text.count("AU  -") == 2


def test_csv_has_utf8_bom_and_exact_column_order(tmp_path: Path) -> None:
    path = write_csv([enriched_paper()], tmp_path / "papers.csv")
    raw = path.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    assert raw.decode("utf-8-sig").splitlines()[0].split(",") == CSV_FIELDS
    assert "根土复合体；优先流" in raw.decode("utf-8-sig")


def test_bibtex_escapes_special_values_and_has_stable_key(tmp_path: Path) -> None:
    first = write_bibtex([enriched_paper()], tmp_path / "first.bib").read_text(encoding="utf-8")
    second = write_bibtex([enriched_paper()], tmp_path / "second.bib").read_text(encoding="utf-8")
    assert first == second
    assert "@article{" in first
    assert "Root \\& soil \\{flow\\}" in first
    assert "doi = {10.1000/root}" in first


def test_html_escapes_metadata_and_renders_five_star_priority() -> None:
    text = render_html(
        [enriched_paper(title="Root < Soil")], Slot.MORNING, date(2026, 7, 10)
    )
    assert "Root &lt; Soil" in text
    assert "Root < Soil" not in text
    assert "★★★★☆" in text
    assert 'href="https://doi.org/10.1000/root?x=1&amp;y=2"' in text
    assert "早间文献推送" in text


class FakePdfResponse:
    def __init__(self, chunks: list[bytes], content_type: str = "application/pdf") -> None:
        self.chunks = chunks
        self.headers = {
            "Content-Type": content_type,
            "Content-Length": str(sum(len(chunk) for chunk in chunks)),
        }

    def raise_for_status(self) -> None:
        return None

    def iter_content(self, chunk_size: int) -> list[bytes]:
        return self.chunks

    def __enter__(self) -> FakePdfResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None


class FakePdfSession:
    def __init__(self, response: FakePdfResponse) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def get(self, url: str, **kwargs: Any) -> FakePdfResponse:
        self.calls.append({"url": url, **kwargs})
        return self.response


def test_oa_pdf_download_is_streamed_with_timeout(tmp_path: Path) -> None:
    session = FakePdfSession(FakePdfResponse([b"%PDF-1.7\n", b"body"]))
    result = download_oa_pdfs(
        [enriched_paper()],
        tmp_path,
        session=session,
        timeout=(2.0, 7.0),
        max_pdf_bytes=1024,
        remaining_attachment_bytes=1024,
    )
    assert len(result) == 1
    assert result[0].read_bytes().startswith(b"%PDF")
    assert session.calls[0]["stream"] is True
    assert session.calls[0]["timeout"] == (2.0, 7.0)


def test_invalid_or_oversized_pdf_is_skipped_without_raising(tmp_path: Path) -> None:
    non_pdf = FakePdfSession(FakePdfResponse([b"html"], content_type="text/html"))
    assert download_oa_pdfs(
        [enriched_paper()],
        tmp_path,
        session=non_pdf,
        max_pdf_bytes=10,
        remaining_attachment_bytes=10,
    ) == []
    oversized = FakePdfSession(FakePdfResponse([b"%PDF" + b"x" * 20]))
    assert download_oa_pdfs(
        [enriched_paper()],
        tmp_path,
        session=oversized,
        max_pdf_bytes=10,
        remaining_attachment_bytes=10,
    ) == []
