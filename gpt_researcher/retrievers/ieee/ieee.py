"""IEEE Xplore metadata search for the existing retriever fan-out."""

import logging
import os
from html import unescape
from re import search, sub

import requests


logger = logging.getLogger(__name__)


class IEEESearch:
    requires_scraping = True
    BASE_URL = "https://ieeexploreapi.ieee.org/api/v1/search/articles"

    def __init__(self, query: str, query_domains=None):
        self.query = query
        self.api_key = os.getenv("IEEE_API_KEY", "").strip()

    def search(self, max_results: int = 20) -> list[dict[str, str]]:
        if not self.api_key or max_results < 1:
            return []
        try:
            response = requests.get(
                self.BASE_URL,
                params={"apikey": self.api_key, "querytext": self.query,
                        "max_records": min(max_results, 200)},
                timeout=20,
            )
            response.raise_for_status()
            records = response.json().get("articles", [])
        except (requests.RequestException, ValueError, AttributeError):
            # Request exceptions can contain the key-bearing URL. Never log them.
            logger.warning("IEEE Xplore search failed")
            return []

        results = []
        for record in records if isinstance(records, list) else []:
            if not isinstance(record, dict):
                continue
            number = record.get("article_number")
            href = record.get("abstract_url") or record.get("html_url")
            if not href and number:
                href = f"https://ieeexplore.ieee.org/document/{number}"
            if not href and record.get("doi"):
                href = f"https://doi.org/{record['doi']}"
            title = record.get("title")
            if title and href:
                abstract = record.get("abstract") or ""
                authors = record.get("authors") or {}
                if isinstance(authors, dict):
                    authors = authors.get("authors") or []
                authors = [item.get("full_name") or item.get("name") for item in authors
                           if isinstance(item, dict)] if isinstance(authors, list) else []
                year_match = search(r"\b(?:19|20)\d{2}\b", str(record.get("publication_year") or record.get("publication_date") or ""))
                results.append({"title": unescape(sub(r"<[^>]+>", " ", title)).strip(),
                                "href": href,
                                "body": unescape(sub(r"<[^>]+>", " ", abstract)).strip(),
                                "abstract": unescape(sub(r"<[^>]+>", " ", abstract)).strip(),
                                "authors": [name for name in authors if name],
                                "year": int(year_match.group()) if year_match else None,
                                "doi": record.get("doi") or "",
                                "source": "IEEE Xplore"})
        return results
