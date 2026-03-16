"""
pages/config.py — Lot size configuration page for Breezy F&O.

Single-column layout with dark theme and top navigation.
"""

import os
import requests
import pandas as pd
import streamlit as st

from nav import NAV_CSS, nav_bar

BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000").rstrip("/")

# ── Page setup ────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Config — Breezy F&O",
    page_icon="⚙️",
    layout="centered",
)

st.markdown(NAV_CSS, unsafe_allow_html=True)
nav_bar("config")

# ── Brand header ──────────────────────────────────────────────────────────────

st.markdown("""
<div style="display:flex; align-items:center; gap:12px; margin-bottom:4px;">
  <span style="font-size:36px; line-height:1;">⚙️</span>
  <span style="font-size:32px; font-weight:900; color:#58A6FF;
               letter-spacing:-1px; font-family:'Segoe UI',Inter,sans-serif;">
    Lot Size Configuration
  </span>
</div>
<p style="color:#8B949E; font-size:13px; margin-bottom:18px;">
  Manage the symbol &rarr; lot size table used by the analyser
</p>
""", unsafe_allow_html=True)

st.warning(
    "**Note:** Changes made here are *in-memory only* and are lost when the backend "
    "service restarts. For permanent changes, update `_LOT_SIZES` in "
    "`backend/data_fetcher.py` and redeploy."
)

# ── Fetch current table ───────────────────────────────────────────────────────

@st.cache_data(ttl=5)
def _fetch_table() -> dict[str, int] | None:
    try:
        r = requests.get(f"{BACKEND_URL}/lot-sizes", timeout=5)
        r.raise_for_status()
        return r.json()["lot_sizes"]
    except Exception as exc:
        st.error(f"Could not fetch lot sizes from backend: {exc}")
        return None


# ── Lot size table ────────────────────────────────────────────────────────────

st.divider()
st.subheader("Current lot sizes")

table = _fetch_table()

if table:
    search = st.text_input(
        "Filter symbols",
        placeholder="Type to filter — e.g. ADANI, NIFTY…",
        label_visibility="collapsed",
    )

    filtered = (
        {k: v for k, v in sorted(table.items()) if search.upper() in k}
        if search else dict(sorted(table.items()))
    )

    df = pd.DataFrame([{"Symbol": k, "Lot size": v} for k, v in filtered.items()])
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        height=min(38 * len(df) + 38, 480),
    )
    st.caption(
        f"Showing {len(filtered)} of {len(table)} symbols."
        + (" Try a different filter." if search and not filtered else "")
    )
else:
    st.info("Backend unreachable — cannot load lot size table.")

# ── Add / update form ─────────────────────────────────────────────────────────

st.divider()
st.subheader("Add / update symbol")

with st.form("upsert_form", clear_on_submit=True):
    new_symbol = st.text_input("Symbol", placeholder="e.g. RELIANCE").strip().upper()
    new_lot    = st.number_input("Lot size", min_value=1, step=1, value=250)
    submitted  = st.form_submit_button("Save", use_container_width=True)

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
            st.success(f"Saved: **{saved['symbol']}** = {saved['lot_size']:,}")
            st.cache_data.clear()
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

# ── Look up a symbol ──────────────────────────────────────────────────────────

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
