"""Offline tests for the academic discovery extension. No network/LLM calls."""
import csv
import json

from gpt_researcher import academic_search as acad


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def test_normalize_doi():
    assert acad.normalize_doi("https://doi.org/10.1234/ABC") == "10.1234/abc"
    assert acad.normalize_doi("DOI: 10.1234/X ") == "10.1234/x"
    assert acad.normalize_doi(None) == ""


def test_semantic_scholar_returns_non_open_access_records(monkeypatch):
    observed = {}

    def fake_get(url, params, headers, timeout):
        observed["params"] = params
        return FakeResponse({"data": [
            {
                "paperId": "123", "title": "Restricted journal article",
                "year": 2024, "authors": [{"name": "Jane Doe"}],
                "externalIds": {"DOI": "10.1000/TEST"},
                "abstract": "A useful abstract",
                "isOpenAccess": False, "openAccessPdf": None,
                "url": "https://example.org/article"
            }
        ]})

    monkeypatch.setattr(acad.requests, "get", fake_get)
    papers = acad.AcademicSemanticScholarSearch("biosensor").search_records(5)
    assert len(papers) == 1
    assert papers[0]["doi"] == "10.1000/test"
    assert papers[0]["open_access_pdf_url"] == ""
    assert papers[0]["is_open_access"] is False
    assert "externalIds" in observed["params"]["fields"]


def test_openalex_keeps_metadata_and_reconstructs_abstract(monkeypatch):
    def fake_get(url, params, timeout):
        return FakeResponse({"results": [{
            "title": "Biochip learning", "doi": "https://doi.org/10.11/A",
            "publication_year": 2025, "publication_date": "2025-03-01",
            "authorships": [{"author": {"display_name": "Jane Doe"}}],
            "primary_location": {
                "landing_page_url": "https://journal.example.com/paper",
                "source": {"display_name": "Sensors", "host_organization_name": "Publisher"}
            },
            "best_oa_location": None,
            "open_access": {"is_oa": False},
            "abstract_inverted_index": {"sensor": [0], "learning": [1]},
            "cited_by_count": 17,
        }]})

    monkeypatch.setattr(acad.requests, "get", fake_get)
    papers = acad.AcademicOpenAlexSearch("sensor").search_records(5)
    assert papers[0]["abstract"] == "sensor learning"
    assert papers[0]["authors"] == "Jane Doe"
    assert papers[0]["doi"] == "10.11/a"
    assert papers[0]["paper_url"] == "https://journal.example.com/paper"
    assert papers[0]["citation_count"] == 17


def test_dedup_merges_sources_and_missing_abstract():
    a = acad._make_record(title="Biosensors", doi="10.11/X",
                          authors="Jane Doe", publication_year=2024,
                          sources="openalex", abstract="")
    b = acad._make_record(title="Biosensors", doi="https://doi.org/10.11/x",
                          authors="Jane Doe", publication_year=2024,
                          sources="semantic_scholar", abstract="Detailed abstract")
    unique = acad.deduplicate([a, b])
    assert len(unique) == 1
    assert unique[0]["sources"] == "openalex; semantic_scholar"
    assert unique[0]["abstract"] == "Detailed abstract"


def test_distinct_dois_never_merge():
    a = acad._make_record(title="Same title", doi="10.11/a",
                          authors="Jane Doe", publication_year=2024, sources="openalex")
    b = acad._make_record(title="Same title", doi="10.11/b",
                          authors="Jane Doe", publication_year=2024, sources="semantic_scholar")
    assert len(acad.deduplicate([a, b])) == 2


def test_search_pipeline_partial_failure(monkeypatch):
    def good(self, max_results):
        return [acad._make_record(title="Machine learning biosensor",
                                  publication_year=2025, sources="openalex")]

    def bad(self, max_results):
        raise acad.requests.Timeout("unavailable")

    monkeypatch.setattr(acad.AcademicOpenAlexSearch, "search_records", good)
    monkeypatch.setattr(acad.AcademicSemanticScholarSearch, "search_records", bad)
    papers, counts, errors = acad.search_academic(
        "biosensors", limit=3, from_year=2024, contains="machine learning"
    )
    assert len(papers) == 1
    assert counts == {"openalex": 1, "semantic_scholar": 0}
    assert "semantic_scholar" in errors


def test_export_csv_json(tmp_path):
    papers = [acad._make_record(title="Sensors", doi="10.1/test", sources="openalex")]
    csv_path = acad.export_records(papers, tmp_path / "records.csv")
    json_path = acad.export_records(papers, tmp_path / "records.json")
    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["title"] == "Sensors"
    assert rows[0]["screening_status"] == "pending"
    assert json.loads(json_path.read_text(encoding="utf-8"))[0]["doi"] == "10.1/test"
