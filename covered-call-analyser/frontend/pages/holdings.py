"""
pages/holdings.py — Portfolio Holdings page for Breezy F&O.

Fetches equity and mutual fund holdings from the Breeze portfolio API
and displays them in two colour-coded tables with P&L breakdown.
"""

import os

import requests
import streamlit as st

from nav import NAV_CSS, brand_header, nav_bar

BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000").rstrip("/")

# ── Page setup ────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Holdings — Breezy F&O",
    page_icon="💼",
    layout="centered",
)

st.markdown(NAV_CSS, unsafe_allow_html=True)
nav_bar("holdings")
brand_header(
    "💼", "Holdings",
    subtitle="Live equity and mutual fund holdings from your ICICI Direct portfolio.",
)

# ── Data fetcher ──────────────────────────────────────────────────────────────


@st.cache_data(ttl=300)   # 5 min — Breeze rate-limits frequent calls
def _fetch_holdings() -> dict:
    r = requests.get(f"{BACKEND_URL}/holdings", timeout=30)
    r.raise_for_status()
    return r.json()


# ── HTML table renderer ───────────────────────────────────────────────────────


def _holdings_table_html(items: list[dict], label: str) -> str:
    """Render a holdings list as a styled HTML table with a summary row."""
    if not items:
        return (
            f'<p style="color:#8B949E;font-size:13px;padding:6px 0 12px;">'
            f"No {label} holdings found.</p>"
        )

    hd = (
        "padding:8px 10px;border-bottom:2px solid #30363D;"
        "color:#8B949E;font-size:11px;font-weight:600;white-space:nowrap;"
    )
    td_base = (
        "padding:6px 10px;border-bottom:1px solid #21262D;"
        "color:#C9D1D9;font-size:12px;font-family:'Courier New',monospace;"
        "white-space:nowrap;"
    )
    td_l = td_base + "text-align:left;"
    td_r = td_base + "text-align:right;"

    col_headers = [
        ("Name",         "text-align:left;"),
        ("Symbol / ISIN","text-align:left;"),
        ("Qty",          "text-align:right;"),
        ("Avg Cost (₹)", "text-align:right;"),
        ("CMP (₹)",      "text-align:right;"),
        ("Value (₹)",    "text-align:right;"),
        ("P&amp;L (₹)",  "text-align:right;"),
        ("P&amp;L %",    "text-align:right;"),
    ]

    out = [
        '<div style="overflow-x:auto;">',
        '<table style="width:100%;border-collapse:collapse;'
        "font-family:Inter,'Segoe UI',sans-serif;\">",
        "<thead><tr>",
    ]
    for h_label, h_align in col_headers:
        out.append(f'<th style="{hd}{h_align}">{h_label}</th>')
    out.append("</tr></thead><tbody>")

    total_value = sum(r["cur_value"] for r in items)
    total_pnl   = sum(r["pnl"] for r in items)
    total_cost  = sum(r["avg_cost"] * r["quantity"] for r in items)
    total_pnl_pct = (total_pnl / total_cost * 100) if total_cost else 0.0

    for r in items:
        pnl_clr  = "#3FB950" if r["pnl"] >= 0 else "#E05252"
        pnl_sign = "+" if r["pnl"] >= 0 else ""
        pct_sign = "+" if r["pnl_pct"] >= 0 else ""
        cmp_disp = f"₹{r['cmp']:,.2f}" if r["cmp"] else "—"

        out.append(
            f"<tr>"
            f'<td style="{td_l}">{r["name"] or "—"}</td>'
            f'<td style="{td_l}">'
            f'<span style="color:#58A6FF;">{r["symbol"] or "—"}</span>'
            f'<br><span style="color:#8B949E;font-size:10px;">{r["isin"] or "—"}</span>'
            f"</td>"
            f'<td style="{td_r}">{r["quantity"]:,.0f}</td>'
            f'<td style="{td_r}">₹{r["avg_cost"]:,.2f}</td>'
            f'<td style="{td_r}">{cmp_disp}</td>'
            f'<td style="{td_r}">₹{r["cur_value"]:,.0f}</td>'
            f'<td style="{td_r};color:{pnl_clr};">{pnl_sign}₹{r["pnl"]:,.0f}</td>'
            f'<td style="{td_r};color:{pnl_clr};">{pct_sign}{r["pnl_pct"]:.2f}%</td>'
            f"</tr>"
        )

    # Summary / totals row
    tot_clr  = "#3FB950" if total_pnl >= 0 else "#E05252"
    tot_sign = "+" if total_pnl >= 0 else ""
    pct_sign = "+" if total_pnl_pct >= 0 else ""
    out.append(
        f'<tr style="background:#161B22;">'
        f'<td style="{td_l}font-weight:700;color:#E6EDF3;" colspan="2">'
        f"Total ({len(items)} holdings)</td>"
        f'<td style="{td_r}"></td>'
        f'<td style="{td_r}"></td>'
        f'<td style="{td_r}"></td>'
        f'<td style="{td_r}font-weight:700;">₹{total_value:,.0f}</td>'
        f'<td style="{td_r}font-weight:700;color:{tot_clr};">'
        f"{tot_sign}₹{total_pnl:,.0f}</td>"
        f'<td style="{td_r}font-weight:700;color:{tot_clr};">'
        f"{pct_sign}{total_pnl_pct:.2f}%</td>"
        f"</tr>"
    )

    out.append("</tbody></table></div>")
    return "".join(out)


# ── Refresh control ───────────────────────────────────────────────────────────

col_btn, col_ts = st.columns([1, 3])
with col_btn:
    if st.button("🔄 Refresh", use_container_width=True, key="holdings_refresh"):
        st.cache_data.clear()
        st.rerun()

st.divider()

# ── Fetch ─────────────────────────────────────────────────────────────────────

try:
    data = _fetch_holdings()
except requests.exceptions.ConnectionError:
    st.error("Cannot connect to backend. Is the FastAPI server running?")
    st.stop()
except requests.HTTPError as exc:
    detail = ""
    try:
        detail = exc.response.json().get("detail", exc.response.text[:200])
    except Exception:
        detail = exc.response.text[:200]
    if exc.response.status_code == 429:
        st.warning(
            "⏳ Breeze API rate limit reached — too many requests in a short window. "
            "Please wait 60 seconds and then click **🔄 Refresh**."
        )
    else:
        st.error(f"Backend error {exc.response.status_code}: {detail}")
    st.stop()
except Exception as exc:
    st.error(f"Failed to fetch holdings: {exc}")
    st.stop()

equity = data.get("equity", [])
mf     = data.get("mutual_funds", [])
ts     = data.get("timestamp", "")

with col_ts:
    if ts:
        st.caption(
            f"Fetched at {ts[:19].replace('T', ' ')} UTC · "
            f"auto-refreshes every 60 s · source: ICICI Breeze"
        )

# ── Equity ────────────────────────────────────────────────────────────────────

st.markdown('<div class="section-hd">Equity Holdings</div>', unsafe_allow_html=True)
st.markdown(_holdings_table_html(equity, "equity"), unsafe_allow_html=True)

# ── Mutual Funds ──────────────────────────────────────────────────────────────

st.markdown(
    '<div class="section-hd">Mutual Fund Holdings</div>', unsafe_allow_html=True
)
st.markdown(_holdings_table_html(mf, "mutual fund"), unsafe_allow_html=True)
