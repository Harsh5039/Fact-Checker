"""Core pipeline: PDF -> claims -> live web evidence -> verdicts.

Uses only 2 Gemini requests per document (1 to extract claims, 1 to judge ALL claims),
so the free tier (about 20 requests/day) allows roughly 10 documents a day.
"""
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date

from ddgs import DDGS
from google import genai
from google.genai import types
from pypdf import PdfReader

# One model, or several separated by commas (tried in order if one is out of quota).
MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
MAX_CLAIMS = 12
MAX_CHARS = 60000


def read_pdf(file) -> str:
    reader = PdfReader(file)
    return "\n".join((p.extract_text() or "") for p in reader.pages).strip()


def _json(text: str):
    text = re.sub(r"```(?:json)?", "", text).strip()
    m = re.search(r"(\[.*\]|\{.*\})", text, re.S)
    return json.loads(m.group(1) if m else text)


def _ask(client, system: str, user: str) -> str:
    """Call Gemini; retry temporary errors; fall back to the next model if quota is gone."""
    models = [m.strip() for m in MODEL.split(",") if m.strip()]
    last = None
    for model in models:
        for attempt in range(4):
            try:
                r = client.models.generate_content(
                    model=model,
                    contents=user,
                    config=types.GenerateContentConfig(
                        system_instruction=system,
                        response_mime_type="application/json",
                    ),
                )
                return r.text or ""
            except Exception as e:
                last, msg = e, str(e)
                if "PerDay" in msg or "404" in msg or "NOT_FOUND" in msg:
                    break  # this model is unusable today -> try next model
                if any(k in msg for k in ("429", "503", "RESOURCE_EXHAUSTED", "UNAVAILABLE")):
                    time.sleep(8 * (attempt + 1))
                    continue
                raise
    raise last


def extract_claims(client, text: str) -> list[dict]:
    system = (
        "You extract checkable factual claims from marketing documents. "
        "Return ONLY a JSON array. Each item: "
        '{"claim": exact statement with its number/date, '
        '"category": "stat|date|financial|technical", '
        '"search_query": a precise web search query to verify it}. '
        "Only include claims with specific, verifiable figures, dates, rankings or named facts. "
        "Skip opinions and vague statements. Keep the year/entity in the claim."
    )
    return _json(_ask(client, system, f"Document:\n{text[:MAX_CHARS]}"))[:MAX_CLAIMS]


def search(query: str) -> list[dict]:
    """Live web search via DuckDuckGo (no API key)."""
    for attempt in range(3):
        try:
            res = DDGS(timeout=10).text(query, max_results=5)
            out = [{"title": r.get("title", ""), "url": r.get("href", ""),
                    "content": (r.get("body") or "")[:600]} for r in res]
            if out:
                return out
        except Exception:
            pass
        time.sleep(2 * (attempt + 1))
    return []


def judge_all(client, claims: list[dict], evidence: list[list[dict]]) -> list[dict]:
    system = (
        f"Today's date is {date.today().isoformat()}. You are a strict fact-checker. "
        "For EACH numbered claim, judge it using the web evidence given for that claim "
        "(compare numbers, units, entities, dates; prefer official and recent sources). "
        "If the evidence is empty or irrelevant you may use well-established common knowledge, "
        "but say so in the explanation.\n"
        "Status rules:\n"
        "- Verified: matches the evidence (minor rounding is fine).\n"
        "- Inaccurate: outdated or partly wrong; give the correct/current value.\n"
        "- False: evidence or well-established fact contradicts it, OR nothing supports it. "
        'Set "basis" to "contradicted" or "no_evidence".\n'
        "Return ONLY a JSON array with one object per claim: "
        '{"id": number, "status": "Verified|Inaccurate|False", '
        '"basis": "supported|outdated|contradicted|no_evidence", '
        '"correct_fact": "the real fact with figure and date, or empty", '
        '"explanation": "1-2 sentences", "source_urls": ["urls actually used"]}'
    )
    blocks = []
    for i, (c, ev) in enumerate(zip(claims, evidence)):
        e = "\n".join(f"  [{j+1}] {x['title']} ({x['url']}): {x['content']}" for j, x in enumerate(ev)) or "  (no web results)"
        blocks.append(f"CLAIM {i}: {c['claim']}\nEVIDENCE:\n{e}")
    return _json(_ask(client, system, "\n\n".join(blocks)))


def run(file, gemini_key: str, progress=None):
    client = genai.Client(api_key=gemini_key)
    text = read_pdf(file)
    if len(text) < 30:
        raise ValueError("No extractable text found (scanned PDF?). Upload a text-based PDF.")
    claims = extract_claims(client, text)
    if progress:
        progress(f"Found {len(claims)} claims. Searching the live web...")
    with ThreadPoolExecutor(max_workers=4) as ex:  # DuckDuckGo has no Gemini quota cost
        evidence = list(ex.map(lambda c: search(c.get("search_query") or c["claim"]), claims))
    if progress:
        progress("Comparing claims with evidence...")
    try:
        verdicts = {int(v["id"]): v for v in judge_all(client, claims, evidence)}
    except Exception as e:
        verdicts, err = {}, str(e)[:300]
    results = []
    for i, c in enumerate(claims):
        v = verdicts.get(i)
        if v is None:
            v = {"status": "Unverified", "basis": "",
                 "explanation": "Could not complete verification (AI quota or service error). Please retry later.",
                 "correct_fact": "", "source_urls": []}
        results.append({**c, **v})
    return results
