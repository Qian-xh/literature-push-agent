"""Resilient academic metadata source adapters."""

from src.fetchers.crossref import CrossrefFetcher
from src.fetchers.openalex import OpenAlexFetcher
from src.fetchers.semantic_scholar import SemanticScholarFetcher

__all__ = ["CrossrefFetcher", "OpenAlexFetcher", "SemanticScholarFetcher"]

