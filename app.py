import os

import pandas as pd
import streamlit as st

import factcheck

st.set_page_config(page_title="TruthLens – PDF Fact-Checker", page_icon="🔎", layout="wide")


def secret(name):
    try:
        return st.secrets[name]
    except Exception:
        return os.getenv(name, "")


GEMINI_KEY = secret("GEMINI_API_KEY")
if secret("GEMINI_MODEL"):
    factcheck.MODEL = secret("GEMINI_MODEL")

STYLE = {
    "Verified": ("✅", "#16a34a"),
    "Inaccurate": ("⚠️", "#d97706"),
    "False": ("❌", "#dc2626"),
    "Unverified": ("⏳", "#6b7280"),
}

st.title("🔎 TruthLens – PDF Fact-Checker")
st.caption("Upload a PDF. We extract stats, dates and figures, check them against the live web, "
           "and show the correct facts with sources.")

with st.sidebar:
    st.header("How it works")
    st.markdown(
        "1. Extract claims from the PDF\n2. Search the live web per claim\n"
        "3. Compare numbers, dates and context\n4. Label each claim\n\n"
        "**Verified** – matches evidence\n\n**Inaccurate** – outdated or partly wrong\n\n"
        "**False** – contradicted, or no evidence found (the reason is shown)"
    )

if not GEMINI_KEY:
    st.error("GEMINI_API_KEY is not configured. Add it in the app secrets.")
    st.stop()

up = st.file_uploader("Upload a PDF", type=["pdf"])

if up and st.button("Run fact-check", type="primary"):
    status = st.empty()
    try:
        with st.spinner("Reading PDF and extracting claims..."):
            results = factcheck.run(up, GEMINI_KEY, progress=status.info)
        status.empty()
        st.session_state["results"] = results
    except Exception as e:
        status.empty()
        st.error(f"Something went wrong: {e}")

results = st.session_state.get("results")
if results:
    counts = pd.Series([r.get("status", "False") for r in results]).value_counts()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Claims checked", len(results))
    c2.metric("✅ Verified", int(counts.get("Verified", 0)))
    c3.metric("⚠️ Inaccurate", int(counts.get("Inaccurate", 0)))
    c4.metric("❌ False", int(counts.get("False", 0)))
    st.divider()

    for i, r in enumerate(results, 1):
        s = r.get("status", "False")
        icon, color = STYLE.get(s, STYLE["False"])
        basis = r.get("basis", "")
        with st.container(border=True):
            st.markdown(f"**{i}. {r['claim']}**")
            st.markdown(f"<span style='color:{color};font-weight:700'>{icon} {s}</span>"
                        f"{' · ' + basis.replace('_', ' ') if basis else ''}", unsafe_allow_html=True)
            st.write(r.get("explanation", ""))
            if r.get("correct_fact") and s != "Verified":
                st.success(f"**Correct fact:** {r['correct_fact']}")
            urls = r.get("source_urls") or []
            if urls:
                st.markdown("Sources: " + " · ".join(f"[{j+1}]({u})" for j, u in enumerate(urls)))

    df = pd.DataFrame([{
        "claim": r["claim"], "status": r.get("status"), "basis": r.get("basis"),
        "correct_fact": r.get("correct_fact"), "explanation": r.get("explanation"),
        "sources": ", ".join(r.get("source_urls") or []),
    } for r in results])
    st.download_button("Download report (CSV)", df.to_csv(index=False), "factcheck_report.csv", "text/csv")
