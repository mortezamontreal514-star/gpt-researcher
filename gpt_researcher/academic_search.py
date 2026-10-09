"""Academic metadata discovery for GPT Researcher (no LLM or scraping).

Run with: python -m gpt_researcher.academic_search --query "biosensor machine learning"
The existing GPTResearcher report and scraping workflows are unchanged.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import requests

# Reuse GPT Researcher's existing academic retrievers and their API configuration.
from gpt_researcher.retrievers.openalex.openalex import OpenAlexSearch
from gpt_researcher.retrievers.semantic_scholar.semantic_scholar import SemanticScholarSearch


FIELDS = (
    "title", "authors", "publication_year", "publication_date", "journal",
    "publisher", "doi", "abstract", "paper_url", "open_access_pdf_url",
    "is_open_access", "citation_count", "sources", "screening_status",
)
SUPPORTED_SOURCES = ("openalex", "semantic_scholar")


def normalize_doi(value: Any) -> str:
    """Use the DOI itself, not a mix of publisher links and DOI URLs."""
    if not isinstance(value, str):
        return ""
    value = value.strip()
    value = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", value, flags=re.I)
    return value.strip().lower()


def _names(items: Any, name_key: str = "name") -> str:
    if not isinstance(items, list):
        return ""
    return "; ".join(str(item.get(name_key)).strip()
                     for item in items if isinstance(item, dict) and item.get(name_key))


def _make_record(**kwargs: Any) -> dict[str, Any]:
    record = {field: "" for field in FIELDS}
    record.update(kwargs)
    record["doi"] = normalize_doi(record["doi"])
    record["screening_status"] = "pending"
    return record


class AcademicOpenAlexSearch(OpenAlexSearch):
    """Metadata version of GPT Researcher's OpenAlex retriever.

    Unlike the ordinary report retriever, preserve identifiers, authors, dates
    and the journal. Do not prefer a PDF to the paper's landing page.
    """

    def search_records(self, max_results: int = 20) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        page = 1
        while len(records) < max_results:
            batch_size = min(25, max_results - len(records))
            params: dict[str, Any] = {
                "search": self.query,
                "per_page": batch_size,
                "page": page,
                "sort": self.sort,
            }
            if self.email:
                params["mailto"] = self.email
            if self.api_key:
                params["api_key"] = self.api_key
            response = requests.get(self.BASE_URL, params=params, timeout=20)
            response.raise_for_status()
            payload = response.json()
            works = payload.get("results", []) if isinstance(payload, dict) else []
            if not isinstance(works, list):
                raise ValueError("Unexpected OpenAlex API response")
            if not works:
                break
            for work in works:
                if not isinstance(work, dict) or not work.get("title"):
                    continue
                location = work.get("primary_location") or {}
                if not isinstance(location, dict):
                    location = {}
                venue = location.get("source") or {}
                if not isinstance(venue, dict):
                    venue = {}
                oa = work.get("best_oa_location") or {}
                if not isinstance(oa, dict):
                    oa = {}
                access = work.get("open_access") or {}
                if not isinstance(access, dict):
                    access = {}
                author_names = [
                    {"name": (a.get("author") or {}).get("display_name")}
                    for a in work.get("authorships", [])
                    if isinstance(a, dict) and isinstance(a.get("author"), dict)
                ]
                records.append(_make_record(
                    title=work["title"],
                    authors=_names(author_names),
                    publication_year=work.get("publication_year") or "",
                    publication_date=work.get("publication_date") or "",
                    journal=venue.get("display_name") or "",
                    publisher=venue.get("host_organization_name") or "",
                    doi=work.get("doi") or "",
                    abstract=self._reconstruct_abstract(work.get("abstract_inverted_index")) or "",
                    paper_url=location.get("landing_page_url") or work.get("doi") or work.get("id") or "",
                    open_access_pdf_url=oa.get("pdf_url") or "",
                    is_open_access=access.get("is_oa", ""),
                    citation_count=work.get("cited_by_count", ""),
                    sources="openalex",
                ))
                if len(records) >= max_results:
                    break
            if len(works) < batch_size:
                break
            page += 1
        return records


class AcademicSemanticScholarSearch(SemanticScholarSearch):
    """Metadata version that DOES NOT discard non-open-access articles."""

    def search_records(self, max_results: int = 20) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        offset = 0
        headers: dict[str, str] = {}
        api_key = os.getenv("SEMANTIC_SCHOLAR_API_KEY")
        if api_key:
            headers["x-api-key"] = api_key
        fields = (
            "paperId,title,abstract,url,venue,year,authors,externalIds,"
            "publicationDate,citationCount,isOpenAccess,openAccessPdf,journal"
        )
        while len(records) < max_results:
            batch_size = min(100, max_results - len(records))
            response = requests.get(
                self.BASE_URL,
                params={"query": self.query, "fields": fields, "limit": batch_size, "offset": offset},
                headers=headers,
                timeout=20,
            )
            response.raise_for_status()
            payload = response.json()
            works = payload.get("data", []) if isinstance(payload, dict) else []
            if not isinstance(works, list):
                raise ValueError("Unexpected Semantic Scholar API response")
            if not works:
                break
            for work in works:
                if not isinstance(work, dict) or not work.get("title"):
                    continue
                ids = work.get("externalIds") or {}
                if not isinstance(ids, dict):
                    ids = {}
                pdf = work.get("openAccessPdf") or {}
                if not isinstance(pdf, dict):
                    pdf = {}
                journal = work.get("journal") or {}
                if not isinstance(journal, dict):
                    journal = {}
                paper_id = work.get("paperId")
                paper_url = work.get("url") or (
                    "https://www.semanticscholar.org/paper/" + paper_id if paper_id else ""
                )
                records.append(_make_record(
                    title=work["title"],
                    authors=_names(work.get("authors")),
                    publication_year=work.get("year") or "",
                    publication_date=work.get("publicationDate") or "",
                    journal=journal.get("name") or work.get("venue") or "",
                    doi=ids.get("DOI") or "",
                    abstract=work.get("abstract") or "",
                    paper_url=paper_url,
                    open_access_pdf_url=pdf.get("url") or "",
                    is_open_access=work.get("isOpenAccess", ""),
                    citation_count=work.get("citationCount", ""),
                    sources="semantic_scholar",
                ))
                if len(records) >= max_results:
                    break
            offset += len(works)
            if len(works) < batch_size:
                break
        return records


def _fingerprint(paper: dict[str, Any]) -> tuple[str, str, str] | None:
    """Only title + year + first author qualifies for DOI-less fallback."""
    title = re.sub(r"[\W_]+", " ", str(paper.get("title") or "").lower()).strip()
    year = str(paper.get("publication_year") or "")
    first_author = (str(paper.get("authors") or "").split(";")[0]).strip().lower()
    if not (title and year and first_author):
        return None
    return (title, year, re.sub(r"[\W_]+", "", first_author))


def deduplicate(papers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge matching DOI, or conservative title/year/author, retaining sources."""
    output: list[dict[str, Any]] = []
    by_doi: dict[str, int] = {}
    by_title: dict[tuple[str, str, str], int] = {}
    for original in papers:
        paper = dict(original)
        paper["doi"] = normalize_doi(paper.get("doi"))
        doi = paper["doi"]
        fp = _fingerprint(paper)
        index = by_doi.get(doi) if doi else None
        if index is None and fp in by_title:
            candidate = output[by_title[fp]]
            # Conflicting DOIs never merge on fuzzy identity.
            if not (doi and candidate.get("doi") and doi != candidate["doi"]):
                index = by_title[fp]
        if index is None:
            index = len(output)
            output.append(paper)
        else:
            existing = output[index]
            sources = set(filter(None, str(existing.get("sources") or "").split("; ")))
            sources.update(filter(None, str(paper.get("sources") or "").split("; ")))
            existing["sources"] = "; ".join(sorted(sources))
            for field in FIELDS:
                if field in ("sources", "screening_status"):
                    continue
                if not existing.get(field) and paper.get(field):
                    existing[field] = paper[field]
                if field == "abstract" and len(str(paper.get(field) or "")) > len(str(existing.get(field) or "")):
                    existing[field] = paper[field]
        current = output[index]
        if current.get("doi"):
            by_doi[current["doi"]] = index
        if doi:
            by_doi[doi] = index
        if fp:
            by_title[fp] = index
    return output


def search_academic(
    query: str, sources: tuple[str, ...] = SUPPORTED_SOURCES, limit: int = 20,
    from_year: int | None = None, to_year: int | None = None,
    contains: str = "",
) -> tuple[list[dict[str, Any]], dict[str, int], dict[str, str]]:
    """Direct API search only. Never instantiates GPTResearcher or any LLM."""
    if not query.strip():
        raise ValueError("Query cannot be empty")
    if limit < 1 or limit > 1000:
        raise ValueError("Limit must be between 1 and 1000 per source")
    if from_year is not None and to_year is not None and from_year > to_year:
        raise ValueError("Start year must not exceed end year")
    retrievers = {
        "openalex": AcademicOpenAlexSearch,
        "semantic_scholar": AcademicSemanticScholarSearch,
    }
    raw: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    errors: dict[str, str] = {}
    for source in sources:
        if source not in retrievers:
            raise ValueError("Unsupported source: " + source)
        try:
            items = retrievers[source](query).search_records(max_results=limit)
            counts[source] = len(items)
            raw.extend(items)
        except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
            counts[source] = 0
            errors[source] = f"{type(exc).__name__}: {exc}"
    filtered = []
    for paper in raw:
        year = paper.get("publication_year")
        if from_year is not None and (not year or int(year) < from_year):
            continue
        if to_year is not None and (not year or int(year) > to_year):
            continue
        text = (str(paper.get("title") or "") + " " + str(paper.get("abstract") or "")).lower()
        if contains and contains.lower() not in text:
            continue
        filtered.append(paper)
    return deduplicate(filtered), counts, errors


def export_records(papers: list[dict[str, Any]], destination: str | Path) -> Path:
    """CSV for screening in Excel, or JSON for downstream tools."""
    path = Path(destination)
    if path.suffix.lower() not in (".csv", ".json"):
        raise ValueError("Output must end with .csv or .json")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".json":
        path.write_text(json.dumps(papers, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        with path.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(papers)
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="GPT Researcher academic metadata search (no LLM)")
    parser.add_argument("--query", required=True, help="Academic search keywords")
    parser.add_argument("--sources", default="openalex,semantic_scholar",
                        help="Comma-separated academic sources")
    parser.add_argument("--limit", type=int, default=20, help="Maximum records per source (1-1000)")
    parser.add_argument("--from-year", type=int)
    parser.add_argument("--to-year", type=int)
    parser.add_argument("--contains", default="", help="Filter title/abstract by keyword")
    parser.add_argument("--output", default="academic_results.csv", help=".csv or .json output")
    args = parser.parse_args(argv)
    sources = tuple(x.strip() for x in args.sources.split(",") if x.strip())
    if not sources:
        parser.error("At least one source is required")
    try:
        papers, counts, errors = search_academic(
            args.query, sources, args.limit, args.from_year, args.to_year, args.contains
        )
        path = export_records(papers, args.output)
    except ValueError as exc:
        parser.error(str(exc))
    for source, count in counts.items():
        print(f"{source}: {count} returned")
    for source, error in errors.items():
        print(f"{source} failed: {error}", file=sys.stderr)
    print(f"Unique filtered papers: {len(papers)}; exported to: {path.resolve()}")
    return 2 if errors and len(errors) == len(sources) else 0


if __name__ == "__main__":
    raise SystemExit(main())
