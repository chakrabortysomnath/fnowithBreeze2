"""
frontend/app.py — Breezy F&O covered call analyser UI.

Single-column layout with dark theme and top navigation.
"""

import os
import requests
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from nav import NAV_CSS, nav_bar

# ── Config ────────────────────────────────────────────────────────────────────

BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000").rstrip("/")

STRIKE_COLORS = {
    "ITM":   "#6A8FBF",
    "ATM":   "#58A6FF",
    "OTM+1": "#20A4A0",
    "OTM+2": "#39D0C8",
}
GRID_COLOR = "#30363D"

# yfinance tickers for index F&O codes (not in the NSE equity mapping)
_INDEX_YF_TICKERS = {
    "NIFTY":     "^NSEI",
    "BANKNIFTY": "^NSEBANK",
    "FINNIFTY":  "^NSEMDCP50",
}

# ── Page setup ────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Breezy F&O",
    page_icon="🤏",
    layout="centered",
)

st.markdown(NAV_CSS, unsafe_allow_html=True)
nav_bar("analyse")

# ── Brand header ──────────────────────────────────────────────────────────────

st.markdown("""
<div style="display:flex; align-items:center; gap:14px; margin-bottom:8px;">
  <span style="font-size:44px; line-height:1;">🤏</span>
  <span style="font-size:36px; font-weight:900; color:#58A6FF;
               letter-spacing:-1px; font-family:'Segoe UI',Inter,sans-serif;">
    Breezy F&amp;O
  </span>
</div>
""", unsafe_allow_html=True)

# ── Backend health ────────────────────────────────────────────────────────────

try:
    h = requests.get(f"{BACKEND_URL}/health", timeout=5).json()
    if h.get("breeze_connected"):
        st.success("● Breeze connected")
    else:
        st.warning("⚠ Backend reachable — Breeze disconnected. Refresh session token.")
except Exception:
    st.error("✕ Backend unreachable")

# ── Session state ─────────────────────────────────────────────────────────────

for key, default in [
    ("expiries",      []),
    ("symbol_loaded", ""),
    ("result",        None),
    ("last_qty_held", 0),
]:
    if key not in st.session_state:
        st.session_state[key] = default

# ── Helpers ───────────────────────────────────────────────────────────────────

def _encode(sym: str) -> str:
    return sym.strip().upper().replace("&", "%26")


@st.cache_data(ttl=300)
def _fetch_nse_symbol_map() -> dict[str, str]:
    """Return F&O shortcode → NSE equity ticker from the backend config."""
    try:
        r = requests.get(f"{BACKEND_URL}/lot-sizes", timeout=5)
        r.raise_for_status()
        return r.json().get("nse_symbols", {})
    except Exception:
        return {}


def _yf_ticker(symbol: str, nse_map: dict[str, str]) -> str:
    """Resolve an F&O shortcode to a yfinance-compatible ticker."""
    sym = symbol.upper()
    if sym in _INDEX_YF_TICKERS:
        return _INDEX_YF_TICKERS[sym]
    nse = nse_map.get(sym)
    return f"{nse}.NS" if nse else f"{sym}.NS"


@st.cache_data(ttl=300)
def _fetch_symbols() -> list[str]:
    try:
        r = requests.get(f"{BACKEND_URL}/lot-sizes", timeout=5)
        r.raise_for_status()
        return sorted(r.json()["lot_sizes"].keys())
    except Exception:
        return []


def _fetch_expiries(symbol: str) -> list[str]:
    r = requests.get(f"{BACKEND_URL}/expiries/{_encode(symbol)}", timeout=10)
    r.raise_for_status()
    return r.json()["expiries"]


def _fetch_analyse(payload: dict) -> dict:
    r = requests.post(f"{BACKEND_URL}/analyse", json=payload, timeout=30)
    r.raise_for_status()
    return r.json()


@st.cache_data(ttl=600)
def _fetch_ohlc(ticker: str) -> pd.DataFrame | None:
    """Fetch 30-day daily OHLC from yfinance. ticker is a resolved yfinance symbol."""
    import yfinance as yf
    try:
        df = yf.download(ticker, period="1mo", interval="1d",
                         progress=False, auto_adjust=True)
        if df.empty:
            return None
        df.index = pd.to_datetime(df.index)
        return df
    except Exception:
        return None


def _fmt_inr(v) -> str:
    if v is None:
        return "-"
    return f"₹{v:,.2f}"


def _base_layout(height=260):
    return dict(
        plot_bgcolor="#161B22",
        paper_bgcolor="#0D1117",
        margin=dict(l=8, r=8, t=40, b=36),
        font=dict(family="Inter, Segoe UI, sans-serif", size=12, color="#E6EDF3"),
        legend=dict(orientation="h", yanchor="bottom", y=1.05,
                    xanchor="left", x=0, font=dict(size=12)),
        height=height,
    )


# ── Input form ────────────────────────────────────────────────────────────────

# Section 1: Select Symbol
st.subheader("Select Symbol")

symbols     = _fetch_symbols()
prev_symbol = st.session_state.symbol_loaded
default_idx = symbols.index(prev_symbol) if prev_symbol in symbols else 0

symbol = st.selectbox(
    "Symbol",
    options=symbols if symbols else [""],
    index=default_idx,
    label_visibility="collapsed",
    placeholder="Search NSE F&O symbol…",
)

if symbol and symbol != st.session_state.symbol_loaded:
    try:
        st.session_state.expiries      = _fetch_expiries(symbol)
        st.session_state.symbol_loaded = symbol
        st.session_state.result        = None
    except Exception as exc:
        st.error(f"Could not load expiries for {symbol}: {exc}")

if not symbols:
    st.caption("⚠ Could not load symbol list — backend may be unreachable.")

# Section 2: Select Strike Date
st.subheader("Select Strike Date")

expiry_date = None
if st.session_state.expiries:
    expiry_date = st.radio(
        "Expiry",
        options=st.session_state.expiries,
        horizontal=True,
        label_visibility="collapsed",
    )
else:
    st.caption("Select a symbol above to load expiry dates.")

# Section 3: Configuration
st.subheader("Configuration")

configure_holdings = st.checkbox("Configure: Holdings")

qty_held  = 0
avg_price = 0.0
if configure_holdings:
    q_col, p_col = st.columns(2)
    with q_col:
        qty_held = st.number_input("Shares held", min_value=0, step=1, value=250)
    with p_col:
        avg_price = st.number_input(
            "Avg purchase price (₹)", min_value=0.0, step=0.5, value=0.0,
            help="Leave 0 to use live CMP as cost basis.",
        )

brokerage = 40.0
stt_rate  = 0.001
gst_rate  = 0.18

configure_charges = st.checkbox("Configure: Charges")
if configure_charges:
    ch1, ch2, ch3 = st.columns(3)
    with ch1:
        brokerage = st.number_input("Brokerage / lot (₹)", min_value=1.0,
                                     step=1.0, value=40.0)
    with ch2:
        stt_rate = st.number_input("STT rate", min_value=0.0001, max_value=0.05,
                                    step=0.0001, value=0.001, format="%.4f")
    with ch3:
        gst_rate = st.number_input("GST rate", min_value=0.01, max_value=0.30,
                                    step=0.01, value=0.18, format="%.2f")

analyse_clicked = st.button("Analyse", use_container_width=True,
                            disabled=(expiry_date is None or not symbol))

if analyse_clicked and expiry_date and symbol:
    with st.spinner("Fetching data and running analysis…"):
        try:
            st.session_state.result = _fetch_analyse({
                "symbol":             symbol,
                "expiry_date":        expiry_date,
                "already_holds":      configure_holdings,
                "quantity_held":      qty_held,
                "avg_purchase_price": avg_price,
                "brokerage":          brokerage,
                "stt_rate":           stt_rate,
                "gst_rate":           gst_rate,
            })
            st.session_state["last_qty_held"] = qty_held
        except requests.HTTPError as exc:
            detail = ""
            try:
                detail = exc.response.json().get("detail", "")
            except Exception:
                pass
            st.error(f"Error {exc.response.status_code}: {detail or exc}")
        except Exception as exc:
            st.error(f"Request failed: {exc}")

# ── Results ───────────────────────────────────────────────────────────────────

res = st.session_state.result

if res:
    pos = res["position"]

    st.subheader("Results")

    # ── 30-Day Candlestick Chart ──────────────────────────────────────────────
    st.markdown('<div class="section-hd">30-Day Price History</div>',
                unsafe_allow_html=True)

    nse_map  = _fetch_nse_symbol_map()
    ticker   = _yf_ticker(res["symbol"], nse_map)
    ohlc     = _fetch_ohlc(ticker)
    if ohlc is not None and not ohlc.empty:
        candle = go.Figure(go.Candlestick(
            x=ohlc.index,
            open=ohlc["Open"].squeeze(),
            high=ohlc["High"].squeeze(),
            low=ohlc["Low"].squeeze(),
            close=ohlc["Close"].squeeze(),
            increasing_line_color="#3FB950",
            increasing_fillcolor="#3FB950",
            decreasing_line_color="#F85149",
            decreasing_fillcolor="#F85149",
            name=res["symbol"],
        ))
        candle.update_layout(
            **_base_layout(height=280),
            title=dict(text=f"{res['symbol']} ({ticker}) — last 30 days", font=dict(size=14)),
            xaxis=dict(showgrid=False, zeroline=False, rangeslider_visible=False),
            yaxis=dict(title="Price (₹)", showgrid=True,
                       gridcolor=GRID_COLOR, zeroline=False),
            xaxis_rangebreaks=[dict(bounds=["sat", "mon"])],
        )
        st.plotly_chart(candle, width="stretch", config={"displayModeBar": False})
    else:
        st.caption(f"Price history unavailable for {res['symbol']}.")

    # ── Position Setup ────────────────────────────────────────────────────────
    st.markdown('<div class="section-hd">Position Setup</div>', unsafe_allow_html=True)

    trade_type     = "Holdings" if pos["already_holds"] else "Buy-Write"
    approx_futures = res["cmp"] * (1 + 0.08 * res["days_to_expiry"] / 365)
    last_qty       = st.session_state.get("last_qty_held", 0)
    lot_size       = res["lot_size"]

    if pos["already_holds"] and last_qty > 0:
        net_capital = max(0, lot_size - last_qty) * res["cmp"]
    else:
        net_capital = pos["total_cost"]

    ps_rows = [
        ("Stock",                 "NSE F&O symbol",                                res["symbol"]),
        ("Current Market Price",  "Live last traded price",                        _fmt_inr(res["cmp"])),
        ("F&O Lot Size",          "Shares per contract lot",                       f"{lot_size:,}"),
        ("Trade Type",            "Buy-Write (new position) or Holdings (existing)", trade_type),
        ("Cost Basis / Share",    "Purchase price per share used for analysis",    _fmt_inr(pos["cost_basis_per_share"])),
        ("Purchase Cost (1 lot)", "Total capital at cost basis × lot size",        _fmt_inr(pos["total_cost"])),
        ("Days to Expiry",        "Calendar days remaining to selected expiry",    str(res["days_to_expiry"])),
        ("Approx. Futures Price", "CMP × (1 + 8% × DTE / 365) at 8% carry",       _fmt_inr(approx_futures)),
        ("Net Capital Required",  "Additional cash needed to complete the lot",    _fmt_inr(net_capital)),
    ]
    ps_df = pd.DataFrame(ps_rows, columns=["Field", "Description", "Value"])
    st.dataframe(ps_df, use_container_width=True, hide_index=True)

    if pos["already_holds"] and last_qty > 0:
        st.caption(
            f"You hold {last_qty:,} of {lot_size:,} shares — "
            f"need {max(0, lot_size - last_qty):,} more at CMP to complete the lot."
        )

    # ── Strike Analysis ───────────────────────────────────────────────────────
    st.markdown('<div class="section-hd">Strike Analysis</div>', unsafe_allow_html=True)

    rows = []
    for s in res["strikes"]:
        rows.append({
            "Strike type":       s["strike_type"],
            "Strike (₹)":        f"₹{s['strike']:,.0f}",
            "Premium (₹)":       f"₹{s['premium']:,.2f}",
            "Net premium":       _fmt_inr(s["net_premium_total"]),
            "Breakeven":         _fmt_inr(s["breakeven"]),
            "Max profit":        _fmt_inr(s["max_profit_total"]),
            "Yield %":           f"{s['premium_yield_pct']:.2f}%",
            "Ann. yield %":      (
                f"{s['annualised_yield_pct']:.1f}%"
                if s["annualised_yield_pct"] is not None else "-"
            ),
            "Downside protect.": f"{s['downside_protection_pct']:.2f}%",
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True, height=185)

    # ── P&L payoff chart ──────────────────────────────────────────────────────
    st.markdown('<div class="section-hd">P&L Payoff</div>', unsafe_allow_html=True)

    strikes      = res["strikes"]
    strike_types = [s["strike_type"] for s in strikes]
    payoff_opts  = ["All strikes"] + strike_types
    selected     = st.radio("View payoff for", payoff_opts, horizontal=True, key="payoff_strike_sel")

    line_fig = go.Figure()
    for s in strikes:
        if selected != "All strikes" and s["strike_type"] != selected:
            continue
        payoff = s["payoff"]
        xs = [p["price"] for p in payoff]
        ys = [p["pl"]    for p in payoff]
        line_fig.add_trace(go.Scatter(
            name=f"{s['strike_type']} ₹{s['strike']:,.0f}",
            x=xs, y=ys,
            mode="lines+markers",
            line=dict(color=STRIKE_COLORS.get(s["strike_type"], "#20A4A0"), width=2),
            marker=dict(size=5),
        ))

    line_fig.add_vline(
        x=res["cmp"], line_width=1, line_dash="dash", line_color="#8B949E",
        annotation_text=f"CMP ₹{res['cmp']:,.0f}",
        annotation_position="top right",
        annotation_font_size=11, annotation_font_color="#8B949E",
    )
    line_fig.add_hline(y=0, line_width=1, line_dash="dot", line_color="#8B949E")
    line_fig.update_layout(
        **_base_layout(height=260),
        title=dict(text="P&L at expiry", font=dict(size=14)),
        xaxis=dict(title="Stock price at expiry (₹)", showgrid=False, zeroline=False,
                   gridcolor=GRID_COLOR),
        yaxis=dict(title="P&L (₹)", showgrid=True, gridcolor=GRID_COLOR, zeroline=False),
    )
    st.plotly_chart(line_fig, width="stretch", config={"displayModeBar": False})


else:
    placeholder = pd.DataFrame([
        {"Strike type": t, "Strike (₹)": "-", "Net premium": "-",
         "Breakeven": "-", "Max profit": "-", "Ann. yield %": "-",
         "Downside protect.": "-"}
        for t in ("ITM", "ATM", "OTM+1", "OTM+2")
    ])
    st.dataframe(placeholder, use_container_width=True, hide_index=True, height=185)
