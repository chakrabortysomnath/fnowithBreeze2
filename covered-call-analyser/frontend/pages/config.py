"""
pages/config.py — Lot size configuration page for Breezy F&O.

Accessible via the Streamlit sidebar as a second page when the app is run
with multipage support (pages/ directory).

Allows users to:
  - View the full lot size table with live search/filter
  - Add a new symbol with its lot size
  - Update an existing symbol's lot size

Note: Changes made here call POST /lot-sizes on the backend. They are
      in-memory only and are lost when the backend service restarts.
      For permanent changes, update _LOT_SIZES in backend/data_fetcher.py
      and redeploy.
"""

import os
import requests
import pandas as pd
import streamlit as st

BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000").rstrip("/")

# Brand colours — kept consistent with app.py
BLUE_PRIMARY = "#1A56DB"
TABLE_HEADER = "#C5CBF5"
INPUT_BG     = "#D4E8F7"

# ── Page setup ────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Breezy F&O — Config",
    page_icon="⚙️",
    layout="wide",
)

st.markdown(f"""
<style>
  #MainMenu, footer, header {{visibility: hidden;}}

  .brand-wrap {{
    display: flex; align-items: center; gap: 14px; margin-bottom: 4px;
  }}
  .brand-icon  {{ font-size: 36px; line-height: 1; }}
  .brand-title {{
    font-size: 32px; font-weight: 900; color: {BLUE_PRIMARY};
    letter-spacing: -1px; font-family: "Segoe UI", Inter, sans-serif;
  }}
  .brand-sub   {{
    font-size: 14px; color: #6B7280; margin-bottom: 18px;
  }}

  div[data-testid="stButton"] > button {{
    background-color: {BLUE_PRIMARY} !important; color: white !important;
    border-radius: 9999px !important; border: none !important;
    font-weight: 700 !important; font-size: 14px !important;
    height: 40px !important; width: 100% !important;
  }}
  div[data-testid="stButton"] > button:hover {{
    background-color: #1648C0 !important;
  }}

  div[data-testid="stTextInput"] input,
  div[data-testid="stNumberInput"] input {{
    background-color: {INPUT_BG} !important;
    border: none !important; border-radius: 8px !important;
  }}

  thead tr th {{
    background-color: {TABLE_HEADER} !important;
    color: #1A1A4E !important; font-weight: 700 !important;
  }}

  .warn-box {{
    background: #FEF3C7; border-left: 4px solid #F59E0B;
    border-radius: 6px; padding: 10px 14px; font-size: 13px;
    color: #78350F; margin-bottom: 12px;
  }}
</style>
""", unsafe_allow_html=True)

st.markdown("""
<div class="brand-wrap">
  <span class="brand-icon">⚙️</span>
  <span class="brand-title">Lot Size Configuration</span>
</div>
<div class="brand-sub">Manage the symbol → lot size table used by the analyser</div>
""", unsafe_allow_html=True)

st.markdown("""
<div class="warn-box">
  <strong>Note:</strong> Changes made here are <em>in-memory only</em> and are
  lost when the backend service restarts. For permanent changes, update
  <code>_LOT_SIZES</code> in <code>backend/data_fetcher.py</code> and redeploy.
</div>
""", unsafe_allow_html=True)


# ── Fetch current table ───────────────────────────────────────────────────────

@st.cache_data(ttl=5)   # short TTL so updates show quickly
def _fetch_table() -> dict[str, int] | None:
    try:
        r = requests.get(f"{BACKEND_URL}/lot-sizes", timeout=5)
        r.raise_for_status()
        return r.json()["lot_sizes"]
    except Exception as exc:
        st.error(f"Could not fetch lot sizes from backend: {exc}")
        return None


# ── Two-column layout ─────────────────────────────────────────────────────────

left, right = st.columns([1.6, 1], gap="large")

# ── LEFT — searchable lot size table ─────────────────────────────────────────

with left:
    st.subheader("Current lot sizes")

    table = _fetch_table()

    if table:
        search = st.text_input(
            "Filter symbols",
            placeholder="Type to filter — e.g. ADANI, NIFTY…",
            label_visibility="collapsed",
        )

        filtered = {
            k: v for k, v in sorted(table.items())
            if search.upper() in k
        } if search else dict(sorted(table.items()))

        df = pd.DataFrame(
            [{"Symbol": k, "Lot size": v} for k, v in filtered.items()],
        )
        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
            height=min(38 * len(df) + 38, 520),   # auto-size up to ~520 px
        )
        st.caption(
            f"Showing {len(filtered)} of {len(table)} symbols."
            + (" Try a different filter." if search and not filtered else "")
        )
    else:
        st.info("Backend unreachable — cannot load lot size table.")


# ── RIGHT — add / update form ─────────────────────────────────────────────────

with right:
    st.subheader("Add / update symbol")

    with st.form("upsert_form", clear_on_submit=True):
        new_symbol = st.text_input(
            "Symbol", placeholder="e.g. RELIANCE",
        ).strip().upper()

        new_lot = st.number_input(
            "Lot size", min_value=1, step=1, value=250,
        )

        submitted = st.form_submit_button("Save", use_container_width=True)

    if submitted:
        if not new_symbol:
            st.warning("Symbol cannot be empty.")
        else:
            try:
                r = requests.post(
                    f"{BACKEND_URL}/lot-sizes",
                    json={"symbol": new_symbol, "lot_size": int(new_lot)},
                    timeout=5,
                )
                r.raise_for_status()
                saved = r.json()
                st.success(
                    f"Saved: **{saved['symbol']}** = {saved['lot_size']:,}"
                )
                st.cache_data.clear()   # force table refresh
                st.rerun()
            except requests.HTTPError as exc:
                detail = ""
                try:
                    detail = exc.response.json().get("detail", "")
                except Exception:
                    pass
                st.error(f"Error {exc.response.status_code}: {detail or exc}")
            except Exception as exc:
                st.error(f"Request failed: {exc}")

    # ── Quick-reference: current value for a symbol ───────────────────────────
    st.divider()
    st.subheader("Look up a symbol")

    lookup = st.text_input(
        "Symbol to look up", placeholder="e.g. ADAPOR",
        label_visibility="collapsed",
        key="lookup_input",
    ).strip().upper()

    if lookup and table:
        if lookup in table:
            st.metric(label=lookup, value=f"{table[lookup]:,}")
        else:
            st.warning(f"**{lookup}** not found in the lot size table.")
            st.caption("Use the form above to add it.")
