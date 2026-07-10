from __future__ import annotations

from src.dedup import deduplicate, normalize_doi, normalize_title, paper_key
from src.models import Paper


def test_normalize_doi_removes_url_prefix_and_case() -> None:
    assert normalize_doi(" https://DOI.org/10.1000/ABC.1 ") == "10.1000/abc.1"
    assert normalize_doi("doi:10.1000/ABC.1") == "10.1000/abc.1"


def test_title_key_is_used_when_doi_is_missing() -> None:
    left = Paper(title="Root–Soil  Complex: Preferential Flow!")
    right = Paper(title="root soil complex preferential flow")
    assert normalize_title(left.title) == normalize_title(right.title)
    assert paper_key(left) == paper_key(right)


def test_deduplicates_doi_variants_and_merges_richer_metadata() -> None:
    sparse = Paper(
        title="Root flow",
        doi="https://doi.org/10.1000/ABC",
        authors=["A Author"],
        sources=["crossref"],
    )
    rich = Paper(
        title="Root flow in hillslopes",
        doi="10.1000/abc",
        authors=["A Author", "B Author"],
        abstract="A detailed abstract about preferential flow.",
        cited_by=42,
        oa_pdf_url="https://example.org/paper.pdf",
        sources=["openalex"],
    )

    result = deduplicate([sparse, rich])

    assert len(result) == 1
    assert result[0].title == "Root flow in hillslopes"
    assert result[0].abstract.startswith("A detailed")
    assert result[0].cited_by == 42
    assert result[0].sources == ["crossref", "openalex"]


def test_deduplicates_normalized_titles_without_doi() -> None:
    result = deduplicate(
        [
            Paper(title="Hydrological connectivity on hillslopes", journal="A"),
            Paper(title="Hydrological Connectivity on Hillslopes!", abstract="Abstract"),
        ]
    )
    assert len(result) == 1
    assert result[0].abstract == "Abstract"

