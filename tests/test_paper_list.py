"""Offline checks for the list-only search path."""

import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest


MODULE_PATH = Path(__file__).resolve().parents[1] / "gpt_researcher" / "skills" / "paper_list.py"
spec = importlib.util.spec_from_file_location("paper_list_under_test", MODULE_PATH)
paper_list = importlib.util.module_from_spec(spec)
spec.loader.exec_module(paper_list)


class PaperListTests(unittest.TestCase):
    def test_decomposes_fans_out_and_merges_without_report(self):
        calls = []

        async def plan_research(topic):
            calls.append(("plan", topic))
            return ["solar cells", "battery cells"]

        async def quick_search(query, **kwargs):
            calls.append(("search", query, kwargs))
            if query == "solar cells":
                return [{"title": "Shared paper", "href": "https://example.org/one",
                         "doi": "10.1234/shared", "source": "IEEE Xplore", "authors": ["A. One"]}]
            return [{"title": "Shared paper", "href": "https://other.org/one",
                     "doi": "10.1234/shared", "source": "Springer Nature", "abstract": "More detail"},
                    {"title": "Second paper", "href": "https://example.org/two",
                     "source": "ScienceDirect"}]

        researcher = SimpleNamespace(
            research_conductor=SimpleNamespace(plan_research=plan_research),
            quick_search=quick_search,
        )
        result = asyncio.run(paper_list.find_papers(researcher, "cells", max_results_per_source=7))

        self.assertEqual(result["queries"], ["solar cells", "battery cells"])
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["papers"][0]["sources"], ["IEEE Xplore", "Springer Nature"])
        self.assertEqual(result["papers"][0]["abstract"], "More detail")
        self.assertEqual(result["papers"][0]["queries"], ["solar cells", "battery cells"])
        self.assertEqual(calls[0], ("plan", "cells"))
        self.assertTrue(all(call[2]["all_retrievers"] for call in calls[1:]))
        self.assertTrue(all(call[2]["max_results"] == 7 for call in calls[1:]))

    def test_direct_list_skips_decomposition_and_unsafe_links(self):
        async def plan_research(_topic):
            self.fail("Planning should not run")

        async def quick_search(_query, **_kwargs):
            return [{"title": "Safe", "href": "https://example.org/paper"},
                    {"title": "Unsafe", "href": "javascript:alert(1)"}]

        researcher = SimpleNamespace(
            research_conductor=SimpleNamespace(plan_research=plan_research),
            quick_search=quick_search,
        )
        result = asyncio.run(paper_list.find_papers(researcher, "cells", decompose=False))
        self.assertEqual(result["queries"], ["cells"])
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["papers"][0]["title"], "Safe")


if __name__ == "__main__":
    unittest.main()
