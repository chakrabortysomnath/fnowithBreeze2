"""
pages/glossary.py — Ready Reckoner: definitions of every key term in Breezy F&O.

Term data is stored in frontend/glossary_terms.json so it can be updated
without touching Python code.
"""

import json
import os
import pathlib
import sys

import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from nav import NAV_CSS, nav_bar

st.set_page_config(
    page_title="Ready Reckoner — Breezy F&O",
    page_icon="📖",
    layout="centered",
)

st.markdown(NAV_CSS, unsafe_allow_html=True)
nav_bar("glossary")

st.markdown("""
<div style="display:flex; align-items:center; gap:12px; margin-bottom:4px;">
  <span style="font-size:36px; line-height:1;">📖</span>
  <span style="font-size:32px; font-weight:900; color:#58A6FF;
               letter-spacing:-1px; font-family:'Segoe UI',Inter,sans-serif;">
    Ready Reckoner
  </span>
</div>
<p style="color:#8B949E; font-size:13px; margin-bottom:18px;">
  Plain-English definitions for every term, metric and abbreviation used in this app.
  Use the search box below or browse by section.
</p>
""", unsafe_allow_html=True)

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
