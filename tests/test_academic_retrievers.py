"""Offline contract checks for the three academic retriever adapters."""

import importlib.util
import os
from pathlib import Path
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1] / "gpt_researcher" / "retrievers"


def load_retriever(name):
    path = ROOT / name / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"test_{name}_module", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AcademicRetrieverTests(unittest.TestCase):
    def test_ieee_contract(self):
        module = load_retriever("ieee")
        response = Mock()
        response.json.return_value = {"articles": [{
            "title": "<b>Power systems</b>", "abstract": "<p>Study</p>",
            "article_number": "12345", "publication_year": "2024",
            "authors": {"authors": [{"full_name": "A. Lee"}]}, "doi": "10.1109/example",
        }]}
        with patch.dict(os.environ, {"IEEE_API_KEY": "secret"}), patch.object(module.requests, "get", return_value=response) as get:
            retriever = module.IEEESearch("power")
            results = retriever.search(5)
        self.assertTrue(retriever.requires_scraping)
        self.assertEqual(results[0]["title"], "Power systems")
        self.assertEqual(results[0]["href"], "https://ieeexplore.ieee.org/document/12345")
        self.assertEqual(results[0]["body"], "Study")
        self.assertEqual(results[0]["source"], "IEEE Xplore")
        self.assertEqual((results[0]["authors"], results[0]["year"], results[0]["doi"]),
                         (["A. Lee"], 2024, "10.1109/example"))
        self.assertEqual(get.call_args.kwargs["params"]["querytext"], "power")

    def test_springer_contract(self):
        module = load_retriever("springer")
        response = Mock()
        response.json.return_value = {"records": [{
            "title": "Storage", "abstract": "<p>Abstract</p>",
            "creators": [{"creator": "B. Chen"}], "publicationDate": "2023-06-15",
            "identifier": "doi:10.1007/example",
            "url": [{"format": "html", "platform": "web", "value": "https://link.springer.com/article/1"}],
        }]}
        with patch.dict(os.environ, {"SPRINGER_API_KEY": "secret"}), patch.object(module.requests, "get", return_value=response) as get:
            retriever = module.SpringerSearch("storage")
            results = retriever.search(5)
        self.assertTrue(retriever.requires_scraping)
        self.assertEqual(results[0]["title"], "Storage")
        self.assertEqual(results[0]["href"], "https://link.springer.com/article/1")
        self.assertEqual(results[0]["abstract"], "Abstract")
        self.assertEqual(results[0]["source"], "Springer Nature")
        self.assertEqual((results[0]["authors"], results[0]["year"], results[0]["doi"]),
                         (["B. Chen"], 2023, "10.1007/example"))
        self.assertEqual(get.call_args.kwargs["params"]["q"], "storage")

    def test_sciencedirect_contract(self):
        module = load_retriever("sciencedirect")
        response = Mock()
        response.json.return_value = {"search-results": {"entry": [{
            "dc:title": "Cells", "prism:teaser": "Teaser",
            "dc:creator": "C. Young", "prism:coverDate": "2022-03-10",
            "prism:doi": "10.1016/example",
            "link": [{"@ref": "scidir", "@href": "https://www.sciencedirect.com/science/article/pii/1"}],
        }]}}
        with patch.dict(os.environ, {"ELSEVIER_API_KEY": "secret"}), patch.object(module.requests, "get", return_value=response) as get:
            retriever = module.ScienceDirectSearch("cells")
            results = retriever.search(5)
        self.assertTrue(retriever.requires_scraping)
        self.assertEqual(results[0]["title"], "Cells")
        self.assertEqual(results[0]["href"], "https://www.sciencedirect.com/science/article/pii/1")
        self.assertEqual(results[0]["body"], "Teaser")
        self.assertEqual(results[0]["source"], "ScienceDirect")
        self.assertEqual((results[0]["authors"], results[0]["year"], results[0]["doi"]),
                         (["C. Young"], 2022, "10.1016/example"))
        self.assertEqual(get.call_args.kwargs["headers"]["X-ELS-APIKey"], "secret")
        self.assertEqual(get.call_args.kwargs["params"]["query"], "cells")

    def test_missing_keys_make_no_requests(self):
        for name, cls, key in (("ieee", "IEEESearch", "IEEE_API_KEY"),
                               ("springer", "SpringerSearch", "SPRINGER_API_KEY"),
                               ("sciencedirect", "ScienceDirectSearch", "ELSEVIER_API_KEY")):
            module = load_retriever(name)
            with patch.dict(os.environ, {key: ""}), patch.object(module.requests, "get") as get:
                self.assertEqual(getattr(module, cls)("query").search(), [])
            get.assert_not_called()


if __name__ == "__main__":
    unittest.main()
