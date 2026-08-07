"""
talonx_ingest.news.models
----------------------------
Data model for a single news/social feed article, normalized regardless
of which source produced it (NewsAPI or the Yahoo Finance RSS fallback).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class NewsArticle:
    ticker: str
    title: str
    url: str
    source: str  # e.g. "newsapi:reuters.com" or "rss:finance.yahoo.com"
    published_at: datetime | None
    summary: str  # article description/snippet -- what we actually embed

    @property
    def article_id(self) -> str:
        """
        Stable dedup key. Articles don't have a universal ID the way SEC
        filings have an accession number, so we hash the URL -- the one
        field both NewsAPI and RSS reliably provide and that uniquely
        identifies a specific article.
        """
        return hashlib.sha1(self.url.encode("utf-8")).hexdigest()