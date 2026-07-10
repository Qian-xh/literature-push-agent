from __future__ import annotations

import re
import unicodedata
from dataclasses import replace

from src.models import Paper


DOI_PREFIX = re.compile(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", re.IGNORECASE)


def normalize_doi(value: str) -> str:
    """Return a lowercase bare DOI suitable for stable identity matching."""
    return DOI_PREFIX.sub("", value.strip()).strip().lower().rstrip(". ")


def normalize_title(value: str) -> str:
    """Normalize punctuation, Unicode variants, whitespace, and case in a title."""
    normalized = unicodedata.normalize("NFKD", value).casefold()
    normalized = "".join(character if character.isalnum() else " " for character in normalized)
    return " ".join(normalized.split())


def paper_key(paper: Paper) -> str:
    doi = normalize_doi(paper.doi)
    return f"doi:{doi}" if doi else f"title:{normalize_title(paper.title)}"


def _prefer_text(current: str, incoming: str) -> str:
    return incoming if len(incoming.strip()) > len(current.strip()) else current


def _merge(target: Paper, incoming: Paper) -> None:
    target.title = _prefer_text(target.title, incoming.title)
    target.abstract = _prefer_text(target.abstract, incoming.abstract)
    target.journal = _prefer_text(target.journal, incoming.journal)
    target.url = target.url or incoming.url
    target.oa_pdf_url = target.oa_pdf_url or incoming.oa_pdf_url
    target.doi = normalize_doi(target.doi or incoming.doi)
    if len(incoming.authors) > len(target.authors):
        target.authors = list(incoming.authors)
    target.year = target.year or incoming.year
    if target.published is None or (
        incoming.published is not None and incoming.published < target.published
    ):
        target.published = incoming.published or target.published
    target.cited_by = max(target.cited_by, incoming.cited_by)
    target.influential_citations = max(
        target.influential_citations, incoming.influential_citations
    )
    if target.work_type == "article" and incoming.work_type != "article":
        target.work_type = incoming.work_type
    target.sources = list(dict.fromkeys([*target.sources, *incoming.sources]))
    target.keywords = list(dict.fromkeys([*target.keywords, *incoming.keywords]))


def deduplicate(papers: list[Paper]) -> list[Paper]:
    """Deduplicate papers and merge complementary metadata without mutating inputs."""
    merged: dict[str, Paper] = {}
    doi_aliases: dict[str, str] = {}
    for source in papers:
        paper = replace(
            source,
            authors=list(source.authors),
            keywords=list(source.keywords),
            sources=list(source.sources),
        )
        key = paper_key(paper)
        title_key = f"title:{normalize_title(paper.title)}"
        existing_key = key if key in merged else doi_aliases.get(title_key)
        if existing_key is None:
            merged[key] = paper
            if normalize_doi(paper.doi):
                doi_aliases[title_key] = key
            continue
        _merge(merged[existing_key], paper)
    return list(merged.values())

