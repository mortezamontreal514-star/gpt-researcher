"""The list button and API route stay separate from report generation."""

import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from backend.server.app import app


class PaperListRouteTests(unittest.TestCase):
    def test_button_and_list_endpoint_without_external_calls(self):
        payload = {"topic": "cells", "queries": ["solar cells"], "papers": [],
                   "total": 0, "failed_queries": []}
        with patch("gpt_researcher.GPTResearcher") as researcher_class, patch(
            "gpt_researcher.skills.paper_list.find_papers", new_callable=AsyncMock,
            return_value=payload,
        ) as find_papers:
            with TestClient(app) as client:
                page = client.get("/")
                response = client.post("/api/papers/search", json={
                    "topic": "cells", "decompose": False, "max_results_per_source": 7,
                })

        self.assertEqual(page.status_code, 200)
        self.assertIn('id="findPapersButton"', page.text)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), payload)
        researcher_class.assert_called_once_with(query="cells", verbose=False)
        find_papers.assert_awaited_once_with(
            researcher_class.return_value, "cells", decompose=False,
            max_results_per_source=7,
        )

    def test_blank_topic_is_rejected_before_search(self):
        with patch("gpt_researcher.GPTResearcher") as researcher_class:
            with TestClient(app) as client:
                response = client.post("/api/papers/search", json={"topic": "   "})
        self.assertEqual(response.status_code, 422)
        researcher_class.assert_not_called()


if __name__ == "__main__":
    unittest.main()
