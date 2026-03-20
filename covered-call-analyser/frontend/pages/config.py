"""
pages/config.py — Master data configuration page for Breezy F&O.

Provides review, edit, add, and delete capabilities for all master data:
  1. Lot Sizes         — persisted to frontend/lot_sizes.json
  2. NSE Symbol Mapping — persisted to frontend/nse_symbols.json
  3. Equity Metadata   — persisted to frontend/equity_meta.json
  4. Breeze Session    — daily session token refresh + logout
"""

import json
import os
import sys

import pandas as pd
import requests
import streamlit as st

# Allow importing auth.py from the parent frontend/ directory
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from auth import check_auth
from nav import NAV_CSS, nav_bar

BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000").rstrip("/")

# ── Page setup ────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Config — Breezy F&O",
    page_icon="⚙️",
    layout="centered",
)

check_auth()

st.markdown(NAV_CSS, unsafe_allow_html=True)
nav_bar("config")

# ── Brand header ──────────────────────────────────────────────────────────────

st.markdown("""
<div style="display:flex; align-items:center; gap:12px; margin-bottom:4px;">
  <span style="font-size:36px; line-height:1;">⚙️</span>
  <span style="font-size:32px; font-weight:900; color:#58A6FF;
               letter-spacing:-1px; font-family:'Segoe UI',Inter,sans-serif;">
    Configuration
  </span>
</div>
<p style="color:#8B949E; font-size:13px; margin-bottom:18px;">
  Manage all master data — lot sizes, symbol mappings, equity metadata and Breeze session.
  All changes are persisted to JSON files and survive backend restarts.
</p>
""", unsafe_allow_html=True)

# ── Data fetchers ─────────────────────────────────────────────────────────────


@st.cache_data(ttl=5)
def _fetch_lot_sizes() -> dict[str, int] | None:
    try:
        r = requests.get(f"{BACKEND_URL}/lot-sizes", timeout=5)
        r.raise_for_status()
        return r.json()["lot_sizes"]
    except Exception as exc:
        st.error(f"Could not fetch lot sizes: {exc}")
        return None


@st.cache_data(ttl=5)
def _fetch_nse_symbols() -> dict[str, str] | None:
    try:
        r = requests.get(f"{BACKEND_URL}/nse-symbols", timeout=5)
        r.raise_for_status()
        return r.json()["symbols"]
    except Exception as exc:
        st.error(f"Could not fetch NSE symbols: {exc}")
        return None


@st.cache_data(ttl=10)
def _fetch_equity_meta() -> dict | None:
    try:
        r = requests.get(f"{BACKEND_URL}/equity-meta", timeout=5)
        r.raise_for_status()
        return r.json()["metadata"]
    except Exception as exc:
        st.error(f"Could not fetch equity metadata: {exc}")
        return None


@st.cache_data(ttl=15)
def _fetch_health() -> dict | None:
    try:
        r = requests.get(f"{BACKEND_URL}/health", timeout=5)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


# ── 4 Sub-tabs ────────────────────────────────────────────────────────────────

tab1, tab2, tab3, tab4 = st.tabs([
    "📊 Lot Sizes",
    "🔗 NSE Symbol Mapping",
    "🏷️ Equity Metadata",
    "🔑 Breeze Session",
])

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 1 — Lot Sizes
# ═══════════════════════════════════════════════════════════════════════════════

with tab1:
    st.info(
        "Changes are **persisted** to `lot_sizes.json` and survive backend restarts.",
        icon="💾",
    )

    table = _fetch_lot_sizes()

    # ── View & Search ──
    st.subheader("Current Lot Sizes")
    if table:
        search = st.text_input(
            "Filter symbols",
            placeholder="Type to filter — e.g. ADANI, NIFTY…",
            label_visibility="collapsed",
            key="ls_search",
        )
        filtered = (
            {k: v for k, v in sorted(table.items()) if search.upper() in k}
            if search else dict(sorted(table.items()))
        )
        df = pd.DataFrame([{"Symbol": k, "Lot Size": v} for k, v in filtered.items()])
        st.dataframe(df, use_container_width=True, hide_index=True,
                     height=min(38 * len(df) + 38, 480))
        st.caption(
            f"Showing {len(filtered)} of {len(table)} symbols."
            + (" Try a different filter." if search and not filtered else "")
        )

        # Download current table as JSON
        st.download_button(
            label="⬇️ Export lot_sizes.json",
            data=json.dumps(dict(sorted(table.items())), indent=2) + "\n",
            file_name="lot_sizes.json",
            mime="application/json",
            use_container_width=True,
        )
    else:
        st.info("Backend unreachable — cannot load lot size table.")

    # ── Add / Update ──
    st.divider()
    st.subheader("Add / Update Symbol")
    with st.form("ls_upsert_form", clear_on_submit=True):
        new_sym  = st.text_input("Symbol", placeholder="e.g. RELIANCE").strip().upper()
        new_lot  = st.number_input("Lot size", min_value=1, step=1, value=250)
        ls_saved = st.form_submit_button("Save", use_container_width=True)

    if ls_saved:
        if not new_sym:
            st.warning("Symbol cannot be empty.")
        else:
            try:
                r = requests.post(
                    f"{BACKEND_URL}/lot-sizes",
                    json={"symbol": new_sym, "lot_size": int(new_lot)},
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

    # ── Delete ──
    st.divider()
    st.subheader("Delete Symbol")
    with st.form("ls_delete_form", clear_on_submit=True):
        del_sym   = st.text_input("Symbol to delete", placeholder="e.g. RELIANCE").strip().upper()
        ls_deleted = st.form_submit_button("Delete", use_container_width=True)

    if ls_deleted:
        if not del_sym:
            st.warning("Symbol cannot be empty.")
        else:
            try:
                r = requests.delete(f"{BACKEND_URL}/lot-sizes/{del_sym}", timeout=5)
                if r.status_code == 204:
                    st.success(f"Deleted: **{del_sym}**")
                    st.cache_data.clear()
                    st.rerun()
                elif r.status_code == 404:
                    st.warning(f"**{del_sym}** not found in lot size table.")
                else:
                    r.raise_for_status()
            except requests.HTTPError as exc:
                st.error(f"Error {exc.response.status_code}: {exc}")
            except Exception as exc:
                st.error(f"Request failed: {exc}")

    # ── Lookup ──
    st.divider()
    st.subheader("Look Up a Symbol")
    lookup = st.text_input(
        "Symbol to look up", placeholder="e.g. ADAPOR",
        label_visibility="collapsed",
        key="ls_lookup",
    ).strip().upper()

    if lookup and table:
        if lookup in table:
            st.metric(label=lookup, value=f"{table[lookup]:,}")
        else:
            st.warning(f"**{lookup}** not found.")
            st.caption("Use the form above to add it.")


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 2 — NSE Symbol Mapping
# ═══════════════════════════════════════════════════════════════════════════════

with tab2:
    st.info(
        "Changes are **persisted** to `nse_symbols.json` and survive backend restarts.",
        icon="💾",
    )
    st.caption(
        "This mapping translates F&O shortcodes (used by Breeze API) to NSE equity tickers "
        "(used by yfinance for historical price data)."
    )

    nse_data = _fetch_nse_symbols()

    # ── View & Search ──
    st.subheader("F&O Shortcode → NSE Ticker Mapping")
    if nse_data:
        nse_search = st.text_input(
            "Filter by F&O code or NSE ticker",
            placeholder="e.g. RELIND, INFOSYS…",
            label_visibility="collapsed",
            key="nse_search",
        ).strip().upper()

        if nse_search:
            filtered_nse = {
                k: v for k, v in sorted(nse_data.items())
                if nse_search in k or nse_search in v
            }
        else:
            filtered_nse = dict(sorted(nse_data.items()))

        nse_df = pd.DataFrame(
            [{"F&O Code": k, "NSE Ticker": v} for k, v in filtered_nse.items()]
        )
        st.dataframe(nse_df, use_container_width=True, hide_index=True,
                     height=min(38 * len(nse_df) + 38, 480))
        st.caption(
            f"Showing {len(filtered_nse)} of {len(nse_data)} mappings."
            + (" Try a different filter." if nse_search and not filtered_nse else "")
        )

        st.download_button(
            label="⬇️ Export nse_symbols.json",
            data=json.dumps(dict(sorted(nse_data.items())), indent=2) + "\n",
            file_name="nse_symbols.json",
            mime="application/json",
            use_container_width=True,
        )
    else:
        st.info("Backend unreachable — cannot load NSE symbol mapping.")

    # ── Add / Update ──
    st.divider()
    st.subheader("Add / Update Mapping")
    with st.form("nse_upsert_form", clear_on_submit=True):
        nse_fo_code   = st.text_input("F&O Shortcode", placeholder="e.g. RELIND").strip().upper()
        nse_ticker    = st.text_input("NSE Ticker",    placeholder="e.g. RELIANCE").strip().upper()
        nse_saved     = st.form_submit_button("Save", use_container_width=True)

    if nse_saved:
        if not nse_fo_code or not nse_ticker:
            st.warning("Both F&O shortcode and NSE ticker are required.")
        else:
            try:
                r = requests.post(
                    f"{BACKEND_URL}/nse-symbols",
                    json={"fo_code": nse_fo_code, "nse_ticker": nse_ticker},
                    timeout=5,
                )
                r.raise_for_status()
                saved = r.json()
                st.success(f"Saved: **{saved['fo_code']}** → {saved['nse_ticker']}")
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

    # ── Delete ──
    st.divider()
    st.subheader("Delete Mapping")
    with st.form("nse_delete_form", clear_on_submit=True):
        del_fo_code  = st.text_input("F&O Code to delete", placeholder="e.g. RELIND").strip().upper()
        nse_deleted  = st.form_submit_button("Delete", use_container_width=True)

    if nse_deleted:
        if not del_fo_code:
            st.warning("F&O code cannot be empty.")
        else:
            try:
                r = requests.delete(f"{BACKEND_URL}/nse-symbols/{del_fo_code}", timeout=5)
                if r.status_code == 204:
                    st.success(f"Deleted mapping for **{del_fo_code}**")
                    st.cache_data.clear()
                    st.rerun()
                elif r.status_code == 404:
                    st.warning(f"**{del_fo_code}** not found in NSE symbol mapping.")
                else:
                    r.raise_for_status()
            except requests.HTTPError as exc:
                st.error(f"Error {exc.response.status_code}: {exc}")
            except Exception as exc:
                st.error(f"Request failed: {exc}")

    # ── Lookup ──
    st.divider()
    st.subheader("Look Up a Mapping")
    nse_lookup = st.text_input(
        "F&O code to look up", placeholder="e.g. INFTEC",
        label_visibility="collapsed",
        key="nse_lookup",
    ).strip().upper()

    if nse_lookup and nse_data:
        if nse_lookup in nse_data:
            st.metric(label=nse_lookup, value=nse_data[nse_lookup])
        else:
            st.warning(f"**{nse_lookup}** not found in NSE symbol mapping.")


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 3 — Equity Metadata
# ═══════════════════════════════════════════════════════════════════════════════

with tab3:
    st.info(
        "Changes are **persisted** to `equity_meta.json` and survive backend restarts. "
        "This data provides sector/industry classification used by the Analyse tab.",
        icon="💾",
    )

    eq_data = _fetch_equity_meta()

    # ── View & Search ──
    st.subheader("Equity Metadata (Sector & Industry)")
    if eq_data:
        eq_search = st.text_input(
            "Filter by symbol, sector or industry",
            placeholder="e.g. Technology, HDFBAN, Banks…",
            label_visibility="collapsed",
            key="eq_search",
        ).strip().upper()

        if eq_search:
            filtered_eq = {
                k: v for k, v in sorted(eq_data.items())
                if eq_search in k
                   or eq_search in v.get("sector", "").upper()
                   or eq_search in v.get("industry", "").upper()
            }
        else:
            filtered_eq = dict(sorted(eq_data.items()))

        eq_df = pd.DataFrame([
            {"Symbol": k, "Sector": v.get("sector", ""), "Industry": v.get("industry", "")}
            for k, v in filtered_eq.items()
        ])
        st.dataframe(eq_df, use_container_width=True, hide_index=True,
                     height=min(38 * len(eq_df) + 38, 480))
        st.caption(
            f"Showing {len(filtered_eq)} of {len(eq_data)} entries."
            + (" Try a different filter." if eq_search and not filtered_eq else "")
        )

        st.download_button(
            label="⬇️ Export equity_meta.json",
            data=json.dumps(dict(sorted(eq_data.items())), indent=2) + "\n",
            file_name="equity_meta.json",
            mime="application/json",
            use_container_width=True,
        )
    else:
        st.info("Backend unreachable — cannot load equity metadata.")

    # ── Add / Update ──
    st.divider()
    st.subheader("Add / Update Equity Metadata")
    with st.form("eq_upsert_form", clear_on_submit=True):
        eq_symbol   = st.text_input("Symbol (F&O code)", placeholder="e.g. RELIND").strip().upper()
        eq_sector   = st.text_input("Sector",   placeholder="e.g. Energy")
        eq_industry = st.text_input("Industry", placeholder="e.g. Oil & Gas Integrated")
        eq_saved    = st.form_submit_button("Save", use_container_width=True)

    if eq_saved:
        if not eq_symbol or not eq_sector or not eq_industry:
            st.warning("Symbol, sector, and industry are all required.")
        else:
            try:
                r = requests.post(
                    f"{BACKEND_URL}/equity-meta",
                    json={"symbol": eq_symbol, "sector": eq_sector, "industry": eq_industry},
                    timeout=5,
                )
                r.raise_for_status()
                saved = r.json()
                st.success(
                    f"Saved: **{saved['symbol']}** — {saved['sector']} / {saved['industry']}"
                )
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

    # ── Delete ──
    st.divider()
    st.subheader("Delete Equity Metadata")
    with st.form("eq_delete_form", clear_on_submit=True):
        del_eq_sym  = st.text_input("Symbol to delete", placeholder="e.g. RELIND").strip().upper()
        eq_deleted  = st.form_submit_button("Delete", use_container_width=True)

    if eq_deleted:
        if not del_eq_sym:
            st.warning("Symbol cannot be empty.")
        else:
            try:
                r = requests.delete(f"{BACKEND_URL}/equity-meta/{del_eq_sym}", timeout=5)
                if r.status_code == 204:
                    st.success(f"Deleted metadata for **{del_eq_sym}**")
                    st.cache_data.clear()
                    st.rerun()
                elif r.status_code == 404:
                    st.warning(f"**{del_eq_sym}** not found in equity metadata.")
                else:
                    r.raise_for_status()
            except requests.HTTPError as exc:
                st.error(f"Error {exc.response.status_code}: {exc}")
            except Exception as exc:
                st.error(f"Request failed: {exc}")

    # ── Lookup ──
    st.divider()
    st.subheader("Look Up a Symbol")
    eq_lookup = st.text_input(
        "Symbol to look up", placeholder="e.g. INFTEC",
        label_visibility="collapsed",
        key="eq_lookup",
    ).strip().upper()

    if eq_lookup and eq_data:
        if eq_lookup in eq_data:
            meta = eq_data[eq_lookup]
            c1, c2 = st.columns(2)
            c1.metric("Sector",   meta.get("sector", "—"))
            c2.metric("Industry", meta.get("industry", "—"))
        else:
            st.warning(f"**{eq_lookup}** not found in equity metadata.")
            st.caption("Use the form above to add it.")


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 4 — Breeze Session
# ═══════════════════════════════════════════════════════════════════════════════

with tab4:
    # ── Connection status banner ──
    health = _fetch_health()
    if health:
        connected = health.get("breeze_connected", False)
        if connected:
            st.success("Breeze API is **connected** and responding.", icon="✅")
        else:
            st.warning("Backend is reachable but **Breeze is disconnected**. Refresh the token below.", icon="⚠️")
    else:
        st.error("Backend unreachable — cannot check Breeze connection status.", icon="🔴")

    st.markdown("### Refresh Daily Session Token")
    st.markdown(
        "Breeze session tokens expire at midnight each day. Use this form to hot-swap "
        "the token without restarting the backend service."
    )

    with st.expander("How to generate a fresh token"):
        st.markdown("""
1. Open in your browser (replace `YOUR_API_KEY` with your actual key):
   `https://api.icicidirect.com/apiuser/login?api_key=YOUR_API_KEY`
2. Log in with your ICICI Direct username, password and TOTP code.
3. After login, the browser is redirected to a URL like:
   `https://...?apisession=<TOKEN>&...`
4. Copy the value after `apisession=` (stop at the next `&`) and paste it below.
        """)

    with st.form("session_refresh_form", clear_on_submit=True):
        new_token = st.text_input(
            "New Session Token",
            type="password",
            placeholder="Paste today's apisession token…",
        )
        do_refresh = st.form_submit_button("Refresh Session", use_container_width=True)

    if do_refresh:
        if not new_token.strip():
            st.warning("Token cannot be empty.")
        else:
            with st.spinner("Connecting to Breeze with new token…"):
                try:
                    r = requests.post(
                        f"{BACKEND_URL}/refresh-session",
                        json={"session_token": new_token.strip()},
                        timeout=20,
                    )
                    if r.status_code == 200:
                        st.session_state.breeze_ok = True
                        st.success(
                            f"Session refreshed successfully at "
                            f"{r.json().get('timestamp', 'unknown time')}. "
                            "Breeze API is now connected."
                        )
                        st.cache_data.clear()
                        st.rerun()
                    else:
                        try:
                            detail = r.json().get("detail", r.text)
                        except Exception:
                            detail = r.text
                        st.error(
                            f"**Failed to refresh session** (HTTP {r.status_code}).\n\n"
                            f"{detail}"
                        )
                except requests.exceptions.ConnectionError:
                    st.error("Cannot reach the backend. Check that the service is running.")
                except requests.exceptions.Timeout:
                    st.error("Backend timed out. The Breeze API may be slow — try again.")
                except Exception as exc:
                    st.error(f"Unexpected error: {exc}")

    # ── Log out ──
    st.divider()
    st.subheader("Log Out")
    st.caption(
        "Clears the Breeze session from this browser tab. "
        "You will be taken back to the login screen. "
        "The backend session remains active."
    )
    if st.button("Log Out of This Session", use_container_width=True):
        st.session_state.breeze_ok = False
        st.rerun()
