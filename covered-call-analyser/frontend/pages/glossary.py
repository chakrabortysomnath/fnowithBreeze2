"""
pages/glossary.py — Ready Reckoner: definitions of every key term in Breezy F&O.

Term data is stored in frontend/glossary_terms.json so it can be updated
without touching Python code.
"""

import json
import pathlib

import streamlit as st

from nav import NAV_CSS, brand_header, nav_bar

st.set_page_config(
    page_title="Ready Reckoner — Breezy F&O",
    page_icon="📖",
    layout="centered",
)

st.markdown(NAV_CSS, unsafe_allow_html=True)
nav_bar("glossary")
brand_header(
    "📖", "Ready Reckoner",
    subtitle=(
        "Plain-English definitions for every term, metric and abbreviation used in this app. "
        "Use the search box below or browse by section."
    ),
)

# ── Load terms from JSON ───────────────────────────────────────────────────────

_TERMS_PATH = pathlib.Path(__file__).parent.parent / "glossary_terms.json"

try:
    SECTIONS = json.loads(_TERMS_PATH.read_text(encoding="utf-8"))
except FileNotFoundError:
    st.error(f"glossary_terms.json not found at {_TERMS_PATH}.")
    st.stop()
except json.JSONDecodeError as exc:
    st.error(f"glossary_terms.json is malformed: {exc}")
    st.stop()

# ── Search ─────────────────────────────────────────────────────────────────────

query = st.text_input(
    "Search terms",
    placeholder="e.g. theta, breakeven, ITM…",
    label_visibility="collapsed",
    key="glossary_search",
).strip().lower()

# ── Render ─────────────────────────────────────────────────────────────────────

total_shown = 0

for section in SECTIONS:
    section_title = section["section"]
    emoji         = section.get("emoji", "")
    terms         = section.get("terms", [])

    visible = [
        t for t in terms
        if not query
        or query in t["term"].lower()
        or query in t["definition"].lower()
    ]
    if not visible:
        continue

    st.markdown(
        f'<p class="section-hd">{emoji} {section_title}</p>',
        unsafe_allow_html=True,
    )

    for entry in visible:
        with st.expander(entry["term"]):
            st.markdown(entry["definition"])
        total_shown += 1

if total_shown == 0:
    st.info(f'No terms matched **"{query}"**. Try a shorter or different keyword.')
else:
    st.caption(f"Showing {total_shown} term{'s' if total_shown != 1 else ''}.")
