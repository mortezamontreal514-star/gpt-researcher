# Retrieval-only paper search

`paper_search.py` lists metadata from IEEE Xplore and Springer Nature. It does
not run the GPT Researcher agent, scrape pages, download PDFs, or write reports.
Each result contains its source, title, authors, year, abstract, DOI, and a
paper link when the provider supplies them. Missing fields remain empty.

## Configure your accounts

Create a local `.env` file in the repository root with your own keys:

```dotenv
IEEE_API_KEY=your_ieee_xplore_metadata_api_key
SPRINGER_API_KEY=your_springer_nature_api_key
TYPESAFE_API_KEY=your_typesafe_jev_key
```

The repository ignores `.env`. Keep your actual keys there or in environment
variables; never commit them. The Jev key is needed only with
`--rank-with-jev`. Neither `OPENAI_API_KEY` nor `TAVILY_API_KEY` is required for
this retrieval-only command.

The search uses the [IEEE Xplore Metadata Search API](https://developer.ieee.org/docs/read/Searching_the_IEEE_Xplore_Metadata_API)
and [Springer Nature Meta v2 API](https://dev.springernature.com/docs/api-endpoints/meta-api/).
Use the metadata API keys from those accounts. Jev uses the existing
`TYPESAFE_API_KEY` configuration. These are metadata requests, not the
providers' full-text APIs.

## Search

Run from the repository root:

```powershell
python paper_search.py "battery management systems"
python paper_search.py "battery management systems" --providers ieee --per-provider 20
python paper_search.py "battery management systems" --rank-with-jev
python paper_search.py "battery management systems" --json
```

The default is ten results per provider. `--rank-with-jev` sends each returned
title and abstract to the existing Jev client for usefulness scoring, then
sorts the list by score. It is optional and can consume Jev API usage. Basic
search makes requests only to the selected paper APIs. Jev ranking requires
the normal project Python dependencies from `requirements.txt`; basic search
uses the Python standard library.

The list is metadata discovery. A returned link may lead to subscription
content; this command does not retrieve the full text.

## Offline verification

```powershell
python -m unittest tests.test_paper_search
```

The tests use fake HTTP responses and make no external requests.
