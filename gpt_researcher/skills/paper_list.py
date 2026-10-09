"""List discovered papers using the existing planning and retriever methods.

This path ends after metadata search. It never scrapes pages or writes reports.
"""

import asyncio
from urllib.parse import urlsplit


def _paper_from_result(result: dict, query: str) -> dict | None:
    url = result.get("href") or result.get("url") or ""
    if not isinstance(url, str):
        return None
    parsed_url = urlsplit(url)
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.hostname:
        return None
    title = result.get("title") or "Untitled paper"
    authors = result.get("authors") or []
    if isinstance(authors, str):
        authors = [authors]
    if not isinstance(authors, list):
        authors = []
    doi = result.get("doi") or ""
    if not doi and parsed_url.hostname in {"doi.org", "dx.doi.org"}:
        doi = parsed_url.path.lstrip("/")
    source = result.get("source") or parsed_url.hostname or "Unknown source"
    return {
        "title": str(title),
        "authors": [str(author) for author in authors if author],
        "year": result.get("year"),
        "abstract": str(result.get("abstract") or ""),
        "preview": str(result.get("body") or result.get("content") or ""),
        "doi": str(doi),
        "url": url,
        "sources": [str(source)],
        "queries": [query],
    }


async def find_papers(researcher, topic: str, *, decompose: bool = True,
                      max_results_per_source: int = 10) -> dict:
    """Search each configured retriever for each query and merge matching URLs/DOIs."""
    if decompose:
        planned = await researcher.research_conductor.plan_research(topic)
        queries = list(dict.fromkeys(q.strip() for q in planned if isinstance(q, str) and q.strip()))
    else:
        queries = [topic]
    if not queries:
        queries = [topic]

    batches = await asyncio.gather(*(
        researcher.quick_search(query, all_retrievers=True,
                                aggregated_summary=False,
                                max_results=max_results_per_source)
        for query in queries
    ), return_exceptions=True)

    papers = []
    seen_by_doi = {}
    seen_by_url = {}
    failed_queries = []
    for query, batch in zip(queries, batches):
        if isinstance(batch, BaseException):
            failed_queries.append(query)
            continue
        for result in batch:
            if not isinstance(result, dict):
                continue
            paper = _paper_from_result(result, query)
            if paper is None:
                continue
            doi_key = paper["doi"].lower()
            url_key = paper["url"].rstrip("/").lower()
            existing = seen_by_doi.get(doi_key) if doi_key else None
            existing = existing or seen_by_url.get(url_key)
            if existing is not None:
                for field in ("sources", "queries"):
                    for value in paper[field]:
                        if value not in existing[field]:
                            existing[field].append(value)
                for field in ("authors", "year", "abstract", "preview", "doi"):
                    if not existing[field] and paper[field]:
                        existing[field] = paper[field]
            else:
                existing = paper
                papers.append(paper)
            if doi_key:
                seen_by_doi[doi_key] = existing
            seen_by_url[url_key] = existing

    return {"topic": topic, "queries": queries, "papers": papers,
            "total": len(papers), "failed_queries": failed_queries}
