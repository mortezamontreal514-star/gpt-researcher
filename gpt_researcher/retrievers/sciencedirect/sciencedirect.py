"""ScienceDirect Search API v2 retriever for the existing fan-out."""

import logging
import os
from re import search

import requests


logger = logging.getLogger(__name__)


class ScienceDirectSearch:
    requires_scraping = True
    BASE_URL = "https://api.elsevier.com/content/search/sciencedirect"

    def __init__(self, query: str, query_domains=None):
        self.query = query
        self.api_key = os.getenv("ELSEVIER_API_KEY", "").strip()

    def search(self, max_results: int = 20) -> list[dict[str, str]]:
        if not self.api_key or max_results < 1:
            return []
        count = next((n for n in (10, 25, 50, 100) if n >= max_results), 100)
        try:
            response = requests.get(
                self.BASE_URL,
                headers={"X-ELS-APIKey": self.api_key, "Accept": "application/json"},
                params={"query": self.query, "count": count, "start": 0},
                timeout=20,
            )
            response.raise_for_status()
            entries = response.json().get("search-results", {}).get("entry", [])
        except (requests.RequestException, ValueError, AttributeError):
            logger.warning("ScienceDirect search failed")
            return []

        results = []
        for entry in entries if isinstance(entries, list) else []:
            if not isinstance(entry, dict):
                continue
            links = entry.get("link") or []
            href = next((link.get("@href") for link in links
                         if isinstance(link, dict) and link.get("@ref") == "scidir"), None)
            if not href and entry.get("prism:doi"):
                href = f"https://doi.org/{entry['prism:doi']}"
            title = entry.get("dc:title")
            if title and href:
                authors_node = entry.get("authors") or {}
                authors = (authors_node.get("author") or []) if isinstance(authors_node, dict) else []
                if isinstance(authors, dict):
                    authors = [authors]
                names = [(author.get("$") or author.get("ce:indexed-name")) for author in authors
                         if isinstance(author, dict)]
                if not names and entry.get("dc:creator"):
                    names = [entry["dc:creator"]]
                year_match = search(r"\b(?:19|20)\d{2}\b", str(entry.get("prism:coverDate") or ""))
                results.append({"title": title, "href": href,
                                "body": entry.get("prism:teaser") or "",
                                "abstract": entry.get("dc:description") or "",
                                "authors": [name for name in names if name],
                                "year": int(year_match.group()) if year_match else None,
                                "doi": entry.get("prism:doi") or "",
                                "source": "ScienceDirect"})
            if len(results) >= max_results:
                break
        return results
