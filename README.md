# TruthLens – PDF Fact-Checker ("Truth Layer")

Upload a PDF; the app extracts specific claims (stats, dates, financial/technical figures),
searches the live web for evidence, and flags each claim as **Verified**, **Inaccurate** or **False**,
with the correct fact and source links.

## How it works
1. **Extract** – `pypdf` reads the text; Gemini returns a JSON list of verifiable claims plus a search query for each.
2. **Verify** – each claim is searched via DuckDuckGo (no key).
3. **Judge** – Gemini compares numbers, units, entities and dates in the evidence only (not memory). Today's date is injected so outdated stats are caught.
4. **Report** – status, reason, corrected fact and source URLs; downloadable CSV.

| Status | Meaning |
|---|---|
| Verified | Evidence matches the claim |
| Inaccurate | Outdated or partly wrong; the current value is given |
| False | Contradicted by evidence, or no evidence found (`basis` shows which) |

## Run locally
```bash
pip install -r requirements.txt
export GEMINI_API_KEY=...   # free at aistudio.google.com
streamlit run app.py
```

## Deploy (Streamlit Community Cloud)
1. Push this folder to a public GitHub repo.
2. share.streamlit.io → New app → pick the repo, main file `app.py`.
3. App settings → Secrets → paste:
```toml
GEMINI_API_KEY = "your-key"
```
4. Deploy and test with your own PDF.

## Limitations
- Scanned PDFs without a text layer are not supported (no OCR).
- Verdict quality depends on search results; "no evidence" is weaker than "contradicted", and the UI says which.
- Capped at 12 claims per document and ~60k characters to control cost.
- Config: `GEMINI_MODEL` env/secret overrides the default model (gemini-3.8-flash). Free-tier rate limits apply; the app retries automatically, so large PDFs can take a minute or two.

- Uses 2 Gemini requests per document (extract + judge all claims), so the free tier (~20 requests/day) covers about 10 documents a day. `GEMINI_MODEL` can list several models separated by commas; the next is used if one runs out of quota.
