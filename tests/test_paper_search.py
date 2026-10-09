"""Offline checks for the retrieval-only paper list."""

from io import BytesIO
import asyncio
import json
import os
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

import paper_search


class PaperSearchTests(unittest.TestCase):
    def test_both_sources_return_requested_metadata_without_agents(self):
        seen = []

        def opener(request, timeout):
            seen.append((request.full_url, timeout))
            if "ieeexploreapi" in request.full_url:
                payload = {"articles": [{
                    "title": "<b>Power systems</b>", "authors": {"authors": [{"full_name": "A. Lee"}]},
                    "publication_year": "2024", "abstract": "An IEEE abstract.",
                    "doi": "10.1109/example", "article_number": "12345",
                }]}
            else:
                payload = {"records": [{
                    "title": "Energy storage", "creators": [{"creator": "B. Chen"}],
                    "publicationDate": "2023-06-15", "abstract": "<p>A Springer abstract.</p>",
                    "identifier": "doi:10.1007/example",
                    "url": [{"format": "html", "platform": "web", "value": "https://link.springer.com/a"}],
                }]}
            return BytesIO(json.dumps(payload).encode())

        with patch.dict(os.environ, {"IEEE_API_KEY": "ieee-secret", "SPRINGER_API_KEY": "springer-secret"}):
            papers, warnings = paper_search.search_papers("energy storage", ["ieee", "springer"], 5, opener=opener)

        self.assertEqual(warnings, [])
        self.assertEqual(len(papers), 2)
        self.assertEqual(papers[0].authors, ["A. Lee"])
        self.assertEqual((papers[0].year, papers[0].doi), (2024, "10.1109/example"))
        self.assertEqual(papers[1].abstract, "A Springer abstract.")
        self.assertEqual((papers[1].authors, papers[1].year), (["B. Chen"], 2023))
        self.assertEqual(len(seen), 2)
        self.assertTrue(all(timeout == 20 for _, timeout in seen))

    def test_missing_key_skips_source_without_network(self):
        with patch.dict(os.environ, {"IEEE_API_KEY": ""}):
            papers, warnings = paper_search.search_papers(
                "query", ["ieee"], 10, opener=lambda *_args, **_kwargs: self.fail("network used")
            )
        self.assertEqual(papers, [])
        self.assertIn("IEEE_API_KEY", warnings[0])

    def test_http_error_does_not_reveal_api_key(self):
        def opener(request, timeout):
            raise HTTPError(request.full_url, 429, "rate limited", {}, None)

        with patch.dict(os.environ, {"IEEE_API_KEY": "private-key"}):
            papers, warnings = paper_search.search_papers("query", ["ieee"], 10, opener=opener)
        self.assertEqual(papers, [])
        self.assertIn("429", warnings[0])
        self.assertNotIn("private-key", warnings[0])

    def test_optional_jev_ranks_existing_list_without_filtering_papers(self):
        class FakeSession:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return False

        class FakeJevClient:
            def session(self):
                return FakeSession()

            async def score_relevance(self, _session, _query, passage):
                return 3.0 if "Relevant" in passage else 0.5

        papers = [
            paper_search.Paper("IEEE", "Other", [], None, "x", "", "https://example.org/a"),
            paper_search.Paper("Springer", "Relevant", [], None, "y", "", "https://example.org/b"),
        ]
        ranked = asyncio.run(paper_search.rank_with_jev(
            papers, "query", client_factory=FakeJevClient
        ))
        self.assertEqual([paper.title for paper in ranked], ["Relevant", "Other"])
        self.assertEqual(len(ranked), 2)
        self.assertEqual(ranked[0].jev_score, 3.0)


if __name__ == "__main__":
    unittest.main()
