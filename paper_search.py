"""Retrieve paper metadata from IEEE Xplore and Springer Nature.

This entry point deliberately does not create a GPTResearcher agent. It only
queries metadata APIs and, when requested, scores returned abstracts with the
project's existing Jev client.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict, dataclass
from html import unescape
import json
import os
from pathlib import Path
import re
import sys
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


IEEE_URL = "https://ieeexploreapi.ieee.org/api/v1/search/articles"
SPRINGER_URL = "https://api.springernature.com/meta/v2/json"
PROVIDERS = ("ieee", "springer")
KEY_NAMES = {"ieee": "IEEE_API_KEY", "springer": "SPRINGER_API_KEY"}


class PaperSearchError(RuntimeError):
    """An API request failed without exposing its key-bearing URL."""


@dataclass
class Paper:
    source: str
    title: str
    authors: list[str]
    year: int | None
    abstract: str
    doi: str
    link: str
    jev_score: float | None = None


def load_env_file(path: Path) -> None:
    """Read the API keys from an ignored local .env file if one exists."""
    if not path.is_file():
        return
    supported = set(KEY_NAMES.values()) | {"TYPESAFE_API_KEY"}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        if name in supported:
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            os.environ.setdefault(name, value)


def _get_json(base_url: str, params: dict, opener: Callable = urlopen) -> dict:
    # Both providers require keys in query parameters. Never include the full
    # request URL or the response body in an exception or log message.
    request = Request(
        f"{base_url}?{urlencode(params)}",
        headers={"User-Agent": "GPT-Researcher-Paper-Search/1.0", "Accept": "application/json"},
    )
    try:
        with opener(request, timeout=20) as response:
            payload = json.load(response)
    except HTTPError as exc:
        exc.close()
        raise PaperSearchError(f"API returned HTTP {exc.code}") from None
    except (URLError, TimeoutError, OSError) as exc:
        raise PaperSearchError(f"API request failed ({type(exc).__name__})") from None
    except (ValueError, UnicodeError):
        raise PaperSearchError("API returned invalid JSON") from None
    if not isinstance(payload, dict):
        raise PaperSearchError("API returned an unexpected JSON shape")
    return payload


def _text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return unescape(re.sub(r"<[^>]*>", " ", value)).strip()


def _year(*values: object) -> int | None:
    for value in values:
        match = re.search(r"\b(?:19|20)\d{2}\b", str(value or ""))
        if match:
            return int(match.group())
    return None


def _doi(value: object) -> str:
    doi = _text(value)
    return re.sub(r"^(?:doi:|https?://(?:dx\.)?doi\.org/)", "", doi, flags=re.I).strip()


def _ieee_authors(value: object) -> list[str]:
    if isinstance(value, dict):
        value = value.get("authors", [])
    if not isinstance(value, list):
        return []
    return [name for item in value if isinstance(item, dict)
            if (name := _text(item.get("full_name") or item.get("name")))]


def parse_ieee(payload: dict) -> list[Paper]:
    records = payload.get("articles") or []
    if not isinstance(records, list):
        raise PaperSearchError("IEEE returned an unexpected articles field")
    papers = []
    for item in records:
        if not isinstance(item, dict):
            continue
        doi = _doi(item.get("doi"))
        article_number = _text(item.get("article_number"))
        link = _text(item.get("abstract_url") or item.get("html_url"))
        if not link and article_number:
            link = f"https://ieeexplore.ieee.org/document/{article_number}"
        if not link and doi:
            link = f"https://doi.org/{doi}"
        title = _text(item.get("title"))
        if title and link:
            papers.append(Paper("IEEE", title, _ieee_authors(item.get("authors")),
                                _year(item.get("publication_year"), item.get("publication_date")),
                                _text(item.get("abstract")), doi, link))
    return papers


def _springer_authors(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [name for item in value if isinstance(item, dict)
            if (name := _text(item.get("creator") or item.get("name")))]


def _springer_link(value: object) -> str:
    if isinstance(value, str):
        return _text(value)
    if not isinstance(value, list):
        return ""
    candidates = [item for item in value if isinstance(item, dict) and item.get("value")]
    preferred = next((item for item in candidates if item.get("format") == "html"
                      and item.get("platform") == "web"), None)
    return _text((preferred or (candidates[0] if candidates else {})).get("value"))


def parse_springer(payload: dict) -> list[Paper]:
    records = payload.get("records") or []
    if not isinstance(records, list):
        raise PaperSearchError("Springer returned an unexpected records field")
    papers = []
    for item in records:
        if not isinstance(item, dict):
            continue
        doi = _doi(item.get("doi") or item.get("identifier"))
        link = _springer_link(item.get("url")) or (f"https://doi.org/{doi}" if doi else "")
        title = _text(item.get("title"))
        if title and link:
            papers.append(Paper("Springer", title, _springer_authors(item.get("creators")),
                                _year(item.get("publicationDate"), item.get("coverDate")),
                                _text(item.get("abstract")), doi, link))
    return papers


def search_papers(query: str, providers: list[str], per_provider: int,
                  *, opener: Callable = urlopen) -> tuple[list[Paper], list[str]]:
    """Search provider metadata only; return records and safe error messages."""
    if not query.strip():
        raise ValueError("Query must not be empty")
    if not 1 <= per_provider <= 200:
        raise ValueError("per_provider must be between 1 and 200")
    papers: list[Paper] = []
    warnings: list[str] = []
    for provider in providers:
        if provider not in PROVIDERS:
            raise ValueError(f"Unknown provider: {provider}")
        key = os.environ.get(KEY_NAMES[provider], "").strip()
        if not key:
            warnings.append(f"{provider}: set {KEY_NAMES[provider]} to enable this source")
            continue
        try:
            if provider == "ieee":
                payload = _get_json(IEEE_URL, {"apikey": key, "querytext": query,
                                               "max_records": per_provider}, opener)
                papers.extend(parse_ieee(payload))
            else:
                payload = _get_json(SPRINGER_URL, {"api_key": key, "q": query,
                                                   "s": 1, "p": per_provider}, opener)
                papers.extend(parse_springer(payload))
        except PaperSearchError as exc:
            warnings.append(f"{provider}: {exc}")
    return papers, warnings


async def rank_with_jev(papers: list[Paper], query: str,
                        *, client_factory: Callable | None = None) -> list[Paper]:
    """Score returned titles and abstracts with the project's Jev client."""
    if not papers:
        return papers
    if client_factory is None:
        from gpt_researcher.context.jev_filter import JevClient
        client_factory = JevClient

    client = client_factory()
    async with client.session() as session:
        scores = await asyncio.gather(*(
            client.score_relevance(session, query, f"Title: {paper.title}\nAbstract: {paper.abstract}")
            for paper in papers
        ))
    for paper, score in zip(papers, scores):
        paper.jev_score = score
    return sorted(papers, key=lambda paper: -(paper.jev_score or 0))


def _print_list(papers: list[Paper]) -> None:
    for number, paper in enumerate(papers, 1):
        print(f"{number}. {paper.title} [{paper.source}]"
              + (f" · {paper.year}" if paper.year else "")
              + (f" · Jev {paper.jev_score:.2f}" if paper.jev_score is not None else ""))
        print(f"   Authors: {', '.join(paper.authors) or 'Not supplied'}")
        print(f"   DOI: {paper.doi or 'Not supplied'}")
        print(f"   Link: {paper.link}")
        print(f"   Abstract: {paper.abstract or 'Not supplied'}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="List IEEE and Springer paper metadata without running research agents")
    parser.add_argument("query", help="Paper search terms")
    parser.add_argument("--providers", nargs="+", choices=PROVIDERS, default=list(PROVIDERS))
    parser.add_argument("--per-provider", type=int, default=10, metavar="N")
    parser.add_argument("--rank-with-jev", action="store_true", help="Score abstracts with the existing Jev API client")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of a numbered list")
    args = parser.parse_args(argv)
    load_env_file(Path(__file__).resolve().parent / ".env")
    try:
        papers, warnings = search_papers(args.query, args.providers, args.per_provider)
    except ValueError as exc:
        parser.error(str(exc))
    if args.rank_with_jev and papers:
        if not os.environ.get("TYPESAFE_API_KEY"):
            warnings.append("Jev ranking skipped: set TYPESAFE_API_KEY to enable it")
        else:
            try:
                papers = asyncio.run(rank_with_jev(papers, args.query))
            except Exception as exc:
                warnings.append(f"Jev ranking failed ({type(exc).__name__}); showing provider order")
    if args.json:
        print(json.dumps([asdict(paper) for paper in papers], ensure_ascii=False, indent=2))
    else:
        _print_list(papers)
    for warning in warnings:
        print(f"Warning: {warning}", file=sys.stderr)
    return 0 if papers else 2


if __name__ == "__main__":
    raise SystemExit(main())
