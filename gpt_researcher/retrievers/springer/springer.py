"""Springer Nature Meta v2 search for the existing retriever fan-out."""

import logging
import os
from html import unescape
from re import sub

import requests


logger = logging.getLogger(__name__)


class SpringerSearch:
    requires_scraping = True
    BASE_URL = "https://api.springernature.com/meta/v2/json"

    def __init__(self, query: str, query_domains=None):
        self.query = query
        self.api_key = os.getenv("SPRINGER_API_KEY", "").strip()

    def search(self, max_results: int = 20) -> list[dict[str, str]]:
        if not self.api_key or max_results < 1:
            return []
        try:
            response = requests.get(
                self.BASE_URL,
                params={"api_key": self.api_key, "q": self.query, "s": 1,
                        "p": min(max_results, 100)},
                timeout=20,
            )
            response.raise_for_status()
            records = response.json().get("records", [])
        except (requests.RequestException, ValueError, AttributeError):
            logger.warning("Springer Nature search failed")
            return []

        results = []
        for record in records if isinstance(records, list) else []:
            if not isinstance(record, dict):
                continue
            links = record.get("url") or []
            href = next((link.get("value") for link in links
                         if isinstance(link, dict) and link.get("format") == "html"
                         and link.get("platform") == "web" and link.get("value")), None)
            if not href and record.get("doi"):
                href = f"https://doi.org/{record['doi']}"
            title = record.get("title")
            if title and href:
                abstract = record.get("abstract") or ""
                results.append({"title": unescape(sub(r"<[^>]+>", " ", title)).strip(),
                                "href": href,
                                "body": unescape(sub(r"<[^>]+>", " ", abstract)).strip()})
        return results
