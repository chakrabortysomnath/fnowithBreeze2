"""
frontend/app.py — Breezy F&O covered call analyser UI.

Single-column layout with dark theme and top navigation.
"""

import datetime
import os

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

from nav import NAV_CSS, nav_bar

# ── Logging ───────────────────────────────────────────────────────────────────

import logging
logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────

BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000").rstrip("/")

# PING_URL — health-check URL polled on every page load to show connection status.
# Defaults to BACKEND_URL/health.  Set to empty string "" to disable the ping banner.
PING_URL = os.environ.get("PING_URL", f"{BACKEND_URL}/health").strip()

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

if PING_URL:
    try:
        h = requests.get(PING_URL, timeout=5).json()
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
    source = f"backend {BACKEND_URL}/lot-sizes"
    try:
        r = requests.get(f"{BACKEND_URL}/lot-sizes", timeout=5)
        r.raise_for_status()
        result = r.json().get("nse_symbols", {})
        if not result:
            logger.warning(
                f"Data Collect for NSE symbol map blank, "
                f"SEARCHED WITH - GET /lot-sizes, SOURCE - {source}"
            )
        else:
            logger.warning(
                f"Data Collect for NSE symbol map OK — "
                f"{len(result)} entries loaded, SOURCE - {source}"
            )
        return result
    except Exception as exc:
        logger.warning(
            f"Data Collect for NSE symbol map failed, "
            f"SEARCHED WITH - GET /lot-sizes, SOURCE - {source} | error: {exc}"
        )
        return {}


def _yf_ticker(symbol: str, nse_map: dict[str, str]) -> str:
    """Resolve an F&O shortcode to a yfinance-compatible ticker."""
    sym = symbol.upper()
    if sym in _INDEX_YF_TICKERS:
        ticker = _INDEX_YF_TICKERS[sym]
        logger.warning(
            f"Data Collect ticker resolution: {sym} → {ticker} (index), "
            f"SEARCHED WITH - _INDEX_YF_TICKERS, SOURCE - hardcoded index map"
        )
        return ticker
    nse    = nse_map.get(sym)
    ticker = f"{nse}.NS" if nse else f"{sym}.NS"
    logger.warning(
        f"Data Collect ticker resolution: {sym} → yf_ticker={ticker} "
        f"(nse_map entry: {nse!r}), "
        f"SEARCHED WITH - nse_map[{sym}], SOURCE - backend /lot-sizes nse_symbols"
    )
    return ticker


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


@st.cache_data(ttl=3600)
def _fetch_ohlc(ticker: str) -> pd.DataFrame | None:
    """Fetch 30-day daily OHLC from yfinance. ticker is a resolved yfinance symbol.

    Retries up to 3 times with exponential back-off on rate-limit errors.
    TTL set to 3600s to reduce Render shared-IP throttling.
    """
    import time
    import yfinance as yf
    criteria = f"ticker={ticker} period=1mo interval=1d"
    source   = "yfinance/download"
    for attempt in range(3):
        try:
            df = yf.download(ticker, period="1mo", interval="1d",
                             progress=False, auto_adjust=True)
            if df.empty:
                logger.warning(
                    f"Data Collect for {ticker} failed (empty, attempt {attempt+1}), "
                    f"SEARCHED WITH - {criteria}, SOURCE - {source}"
                )
                return None
            df.index = pd.to_datetime(df.index)
            return df
        except Exception as exc:
            exc_s = str(exc).lower()
            if ("rate" in exc_s or "too many" in exc_s) and attempt < 2:
                wait = 2 ** (attempt + 1)
                logger.warning(
                    f"Data Collect for {ticker} rate-limited (attempt {attempt+1}), "
                    f"retrying in {wait}s | SEARCHED WITH - {criteria}, SOURCE - {source} "
                    f"| error: {exc}"
                )
                time.sleep(wait)
            else:
                logger.warning(
                    f"Data Collect for {ticker} failed (attempt {attempt+1}), "
                    f"SEARCHED WITH - {criteria}, SOURCE - {source} | error: {exc}"
                )
                return None
    return None


@st.cache_data(ttl=60)
def _fetch_option_quote(symbol: str, expiry_date: str, strike: float) -> dict:
    """Fetch IV, OI, Volume for a specific strike from the backend /option-quote endpoint.

    Uses strike_price=<specific> rather than 0, so Breeze returns full detail.
    """
    criteria = f"symbol={symbol} expiry={expiry_date} strike={strike}"
    source   = f"backend /option-quote/{symbol}"
    blank    = {"iv": None, "open_interest": None, "volume": None, "ltp": None}
    try:
        r = requests.get(
            f"{BACKEND_URL}/option-quote/{_encode(symbol)}",
            params={"expiry": expiry_date, "strike": strike},
            timeout=15,
        )
        r.raise_for_status()
        data   = r.json()
        result = {
            "ltp":           data.get("ltp"),
            "iv":            data.get("iv"),
            "open_interest": data.get("open_interest"),
            "volume":        data.get("volume"),
        }
        for field, label in [("iv", "IV"), ("open_interest", "OI"), ("volume", "Volume")]:
            if result.get(field) is None:
                logger.warning(
                    f"Data Collect for {symbol} [{label}] blank, "
                    f"SEARCHED WITH - {criteria}, SOURCE - {source}"
                )
        return result
    except Exception as exc:
        logger.warning(
            f"Data Collect for {symbol} [option quote] failed, "
            f"SEARCHED WITH - {criteria}, SOURCE - {source} | error: {exc}"
        )
        return blank


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


# Nifty sector index yfinance tickers (keyed by yfinance .info "sector" string)
_SECTOR_INDEX: dict[str, str] = {
    "Energy":                    "^CNXENERGY",
    "Technology":                "^CNXIT",
    "Financial Services":        "^NSEBANK",
    "Consumer Staples":          "^CNXFMCG",
    "Consumer Discretionary":    "^CNXAUTO",
    "Healthcare":                "^CNXPHARMA",
    "Basic Materials":           "^CNXMETAL",
    "Industrials":               "^CNXINFRA",
    "Real Estate":               "^CNXREALTY",
    "Communication Services":    "^CNXMEDIA",
}


@st.cache_data(ttl=1800)
def _fetch_intel(ticker: str) -> dict:
    """Fetch equity fundamentals, analyst targets and event dates via yfinance.

    ticker: resolved yfinance ticker e.g. 'RELIANCE.NS' or '^NSEI'.
    Returns an all-None dict on any failure so callers need no error handling.
    """
    import yfinance as yf
    criteria = f"ticker={ticker}"
    source   = "yfinance/Ticker.info"
    blank = dict(
        fifty_two_week_high=None, fifty_two_week_low=None,
        beta=None, sector=None, industry=None,
        earnings_date=None, ex_dividend_date=None,
        analyst_target_low=None, analyst_target_mean=None,
        analyst_target_high=None,
        analyst_recommendation=None, analyst_count=None,
    )
    try:
        logger.warning(
            f"Data Collect for {ticker} - starting yfinance fetch, "
            f"SEARCHED WITH - {criteria}, SOURCE - {source}"
        )
        t_obj = yf.Ticker(ticker)
        info  = t_obj.info
        logger.warning(
            f"Data Collect for {ticker} - yfinance info returned {len(info)} fields, "
            f"SEARCHED WITH - {criteria}, SOURCE - {source} | "
            f"quoteType={info.get('quoteType')!r} "
            f"exchange={info.get('exchange')!r} "
            f"currency={info.get('currency')!r} | "
            f"key_fields: "
            f"fiftyTwoWeekHigh={info.get('fiftyTwoWeekHigh')!r} "
            f"fiftyTwoWeekLow={info.get('fiftyTwoWeekLow')!r} "
            f"beta={info.get('beta')!r} "
            f"sector={info.get('sector')!r} "
            f"regularMarketPrice={info.get('regularMarketPrice')!r}"
        )
        result = {
            "fifty_two_week_high":   info.get("fiftyTwoWeekHigh"),
            "fifty_two_week_low":    info.get("fiftyTwoWeekLow"),
            "beta":                  info.get("beta"),
            "sector":                info.get("sector"),
            "industry":              info.get("industry"),
            "analyst_target_low":    info.get("targetLowPrice"),
            "analyst_target_mean":   info.get("targetMeanPrice"),
            "analyst_target_high":   info.get("targetHighPrice"),
            "analyst_recommendation":info.get("recommendationKey"),
            "analyst_count":         info.get("numberOfAnalystOpinions"),
            "earnings_date":         None,
            "ex_dividend_date":      None,
        }
        ex_ts = info.get("exDividendDate")
        if ex_ts:
            result["ex_dividend_date"] = datetime.datetime.fromtimestamp(
                int(ex_ts)).strftime("%d %b %Y")
        try:
            cal = t_obj.calendar
            if cal and "Earnings Date" in cal:
                dates = cal["Earnings Date"]
                d = dates[0] if isinstance(dates, list) else dates
                result["earnings_date"] = pd.Timestamp(d).strftime("%d %b %Y")
        except Exception:
            pass

        # Warn for each blank critical field
        for field, label in [
            ("fifty_two_week_high", "52-week high"),
            ("fifty_two_week_low",  "52-week low"),
            ("beta",                "beta"),
            ("earnings_date",       "earnings date"),
            ("ex_dividend_date",    "ex-dividend date"),
            ("analyst_target_mean", "analyst target mean"),
        ]:
            if result.get(field) is None:
                logger.warning(
                    f"Data Collect for {ticker} [{label}] blank, "
                    f"SEARCHED WITH - {criteria}, SOURCE - {source}"
                )
        return result
    except Exception as exc:
        logger.warning(
            f"Data Collect for {ticker} failed, "
            f"SEARCHED WITH - {criteria}, SOURCE - {source} | error: {exc}"
        )
        return blank


@st.cache_data(ttl=3600)
def _fetch_nse_actions(nse_symbol: str) -> dict:
    """Fetch upcoming corporate actions from NSE (board meetings, AGM, dividends).

    Hits the NSE unofficial API with a cookie-warm-up session.
    Returns all-None dict gracefully on failure.
    """
    criteria = f"index=equities symbol={nse_symbol.upper()}"
    source   = "nseindia.com/api/corporates-corporateActions"
    blank = dict(earnings_date=None, ex_dividend_date=None,
                 agm_date=None, board_meeting_date=None)
    try:
        s = requests.Session()
        s.headers.update({
            "User-Agent":      ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                "AppleWebKit/537.36 Chrome/120.0.0 Safari/537.36"),
            "Referer":         "https://www.nseindia.com",
            "Accept-Language": "en-US,en;q=0.9",
        })
        s.get("https://www.nseindia.com", timeout=8)   # warm-up for cookies

        r = s.get(
            "https://www.nseindia.com/api/corporates-corporateActions",
            params={"index": "equities", "symbol": nse_symbol.upper()},
            timeout=8,
        )
        r.raise_for_status()
        actions = r.json()

        raw_count = len(actions) if isinstance(actions, list) else type(actions).__name__
        logger.warning(
            f"Data Collect for {nse_symbol} - NSE API returned {raw_count} raw actions, "
            f"SEARCHED WITH - {criteria}, SOURCE - {source}"
        )

        today  = datetime.date.today()
        result = dict(blank)

        def _parse(raw: str) -> datetime.date | None:
            if not raw or raw.strip() in ("-", ""):
                return None
            for fmt in ("%d-%b-%Y", "%Y-%m-%d", "%d-%B-%Y"):
                try:
                    return datetime.datetime.strptime(raw.strip(), fmt).date()
                except ValueError:
                    continue
            return None

        for action in sorted(actions, key=lambda a: a.get("exDate", "")):
            subj    = action.get("subject", "").lower()
            ex_raw  = action.get("exDate", "") or action.get("exdividendDate", "")
            rec_raw = action.get("recDate", "")
            d = _parse(ex_raw) or _parse(rec_raw)
            if not d or d < today:
                continue
            ds = d.strftime("%d %b %Y")
            if "dividend" in subj and not result["ex_dividend_date"]:
                result["ex_dividend_date"] = ds
            elif ("agm" in subj or "annual general" in subj) and not result["agm_date"]:
                result["agm_date"] = ds
            elif "board meeting" in subj and not result["board_meeting_date"]:
                result["board_meeting_date"] = ds
            elif any(k in subj for k in (
                "quarterly results", "financial results", "half yearly results"
            )) and not result["earnings_date"]:
                result["earnings_date"] = ds

        # Warn for each blank corporate event
        for field, label in [
            ("earnings_date",      "earnings date"),
            ("ex_dividend_date",   "ex-dividend date"),
            ("board_meeting_date", "board meeting date"),
            ("agm_date",           "AGM date"),
        ]:
            if not result.get(field):
                logger.warning(
                    f"Data Collect for {nse_symbol} [{label}] blank, "
                    f"SEARCHED WITH - {criteria}, SOURCE - {source}"
                )
        return result
    except Exception as exc:
        logger.warning(
            f"Data Collect for {nse_symbol} failed, "
            f"SEARCHED WITH - {criteria}, SOURCE - {source} | error: {exc}"
        )
        return blank


def _compute_technicals(ohlc: pd.DataFrame | None, symbol: str = "unknown") -> dict:
    """Compute ATR-14 and annualised HV-20 from a daily OHLC dataframe."""
    blank = dict(atr_14=None, hv_20_pct=None)
    rows  = len(ohlc) if ohlc is not None else 0
    if ohlc is None or ohlc.empty or rows < 3:
        logger.warning(
            f"Data Collect for {symbol} [ATR-14, HV-20] blank, "
            f"SEARCHED WITH - ohlc rows={rows} (need ≥3), "
            f"SOURCE - equity OHLC/yfinance"
        )
        return blank
    try:
        close = ohlc["Close"].squeeze().astype(float)
        high  = ohlc["High"].squeeze().astype(float)
        low   = ohlc["Low"].squeeze().astype(float)

        # Annualised HV (20-day log-return std × √252)
        log_ret = np.log(close / close.shift(1)).dropna()
        window  = min(20, len(log_ret))
        hv = float(log_ret.rolling(window).std().iloc[-1]) * (252 ** 0.5) * 100

        # ATR-14
        prev  = close.shift(1)
        tr    = pd.concat([high - low,
                           (high - prev).abs(),
                           (low  - prev).abs()], axis=1).max(axis=1).dropna()
        atr   = float(tr.rolling(min(14, len(tr))).mean().iloc[-1])

        result = dict(atr_14=round(atr, 2), hv_20_pct=round(hv, 1))
        for field, label in [("atr_14", "ATR-14"), ("hv_20_pct", "HV-20")]:
            if result.get(field) is None:
                logger.warning(
                    f"Data Collect for {symbol} [{label}] blank, "
                    f"SEARCHED WITH - ohlc rows={rows}, "
                    f"SOURCE - equity OHLC/yfinance"
                )
        return result
    except Exception as exc:
        logger.warning(
            f"Data Collect for {symbol} [ATR-14, HV-20] failed, "
            f"SEARCHED WITH - ohlc rows={rows}, "
            f"SOURCE - equity OHLC/yfinance | error: {exc}"
        )
        return blank


@st.cache_data(ttl=600)
def _fetch_sector_ohlc(sector: str | None) -> pd.DataFrame | None:
    """Fetch 3-month OHLC for the matching Nifty sector index."""
    if not sector:
        return None
    idx = _SECTOR_INDEX.get(sector)
    if not idx:
        logger.warning(
            f"Data Collect for {sector} [sector OHLC] blank, "
            f"SEARCHED WITH - sector={sector}, "
            f"SOURCE - _SECTOR_INDEX mapping (no matching Nifty index)"
        )
        return None
    import yfinance as yf
    criteria = f"ticker={idx} period=3mo interval=1d"
    source   = "yfinance/download"
    try:
        df = yf.download(idx, period="3mo", interval="1d",
                         progress=False, auto_adjust=True)
        if df.empty:
            logger.warning(
                f"Data Collect for {idx} [sector OHLC] blank, "
                f"SEARCHED WITH - {criteria}, SOURCE - {source}"
            )
            return None
        return df
    except Exception as exc:
        logger.warning(
            f"Data Collect for {idx} [sector OHLC] failed, "
            f"SEARCHED WITH - {criteria}, SOURCE - {source} | error: {exc}"
        )
        return None


def _kv_table_html(rows: list[tuple[str, str, str]]) -> str:
    """Return HTML for a 2-column KV table.

    Column 1: field name (bold, light) with description below in small gray text.
    Column 2: value (monospace, right-aligned).
    """
    cell = "padding:8px 12px;border-bottom:1px solid #30363D;vertical-align:top;"
    out  = [
        '<table style="width:100%;border-collapse:collapse;'
        'font-family:Inter,\'Segoe UI\',sans-serif;margin-bottom:4px;">'
    ]
    for name, desc, value in rows:
        out.append(
            f'<tr>'
            f'<td style="{cell} width:62%;">'
            f'<span style="color:#E6EDF3;font-size:13px;font-weight:500;">{name}</span>'
            f'<br><span style="color:#8B949E;font-size:11px;">{desc}</span>'
            f'</td>'
            f'<td style="{cell} width:38%;text-align:right;'
            f'color:#C9D1D9;font-size:13px;'
            f'font-family:\'Courier New\',monospace;">{value}</td>'
            f'</tr>'
        )
    out.append('</table>')
    return "".join(out)


def _options_api_table_html(strikes: list[dict], cmp: float) -> str:
    """Return HTML for the per-strike Options API data table."""
    TYPE_CLR = {
        "ITM":   "#6A8FBF",
        "ATM":   "#58A6FF",
        "OTM+1": "#20A4A0",
        "OTM+2": "#39D0C8",
    }
    hd = (
        "padding:7px 10px;border-bottom:2px solid #30363D;"
        "color:#8B949E;font-size:11px;font-weight:600;white-space:nowrap;"
    )
    td = (
        "padding:7px 10px;border-bottom:1px solid #21262D;"
        "color:#C9D1D9;font-size:13px;text-align:right;"
        "font-family:'Courier New',monospace;"
    )
    columns = [
        ("Strike (₹)",  "left"),
        ("Type",        "center"),
        ("IV %",        "right"),
        ("OI",          "right"),
        ("Volume",      "right"),
        ("Moneyness %", "right"),
        ("Charges %",   "right"),
    ]
    out = [
        '<table style="width:100%;border-collapse:collapse;'
        'font-family:Inter,\'Segoe UI\',sans-serif;">'
        '<thead><tr>'
    ]
    for label, align in columns:
        out.append(f'<th style="{hd} text-align:{align};">{label}</th>')
    out.append('</tr></thead><tbody>')

    for s in strikes:
        gross       = s.get("gross_premium_total") or 0
        moneyness   = (s["strike"] - cmp) / cmp * 100
        charges_pct = (s["charges"]["total"] / gross * 100) if gross > 0 else 0
        iv_s  = f"{s['iv']:.1f}%"        if s.get("iv")           is not None else "—"
        oi_s  = f"{s['open_interest']:,}" if s.get("open_interest") is not None else "—"
        vol_s = f"{s['volume']:,}"        if s.get("volume")        is not None else "—"
        clr   = TYPE_CLR.get(s["strike_type"], "#8B949E")
        out.append(
            f'<tr>'
            f'<td style="{td} text-align:left;font-weight:600;color:#E6EDF3;">'
            f'₹{s["strike"]:,.0f}</td>'
            f'<td style="{td} text-align:center;">'
            f'<span style="color:{clr};font-weight:700;">{s["strike_type"]}</span></td>'
            f'<td style="{td}">{iv_s}</td>'
            f'<td style="{td}">{oi_s}</td>'
            f'<td style="{td}">{vol_s}</td>'
            f'<td style="{td}">{moneyness:+.1f}%</td>'
            f'<td style="{td}">{charges_pct:.1f}%</td>'
            f'</tr>'
        )
    out.append('</tbody></table>')
    return "".join(out)


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

    nse_map    = _fetch_nse_symbol_map()
    ticker     = _yf_ticker(res["symbol"], nse_map)
    ohlc       = _fetch_ohlc(ticker)
    tech       = _compute_technicals(ohlc, symbol=ticker)
    intel      = _fetch_intel(ticker)
    nse_sym    = nse_map.get(res["symbol"].upper(), res["symbol"])
    nse_acts   = _fetch_nse_actions(nse_sym)
    sector_hv  = _compute_technicals(
        _fetch_sector_ohlc(intel.get("sector")),
        symbol=f"sector:{intel.get('sector') or 'unknown'}",
    ).get("hv_20_pct")

    # Prefer NSE corporate actions (more reliable for India); fall back to yfinance
    earn_date  = nse_acts.get("earnings_date")  or intel.get("earnings_date")
    ex_div     = nse_acts.get("ex_dividend_date") or intel.get("ex_dividend_date")
    agm_date   = nse_acts.get("agm_date")
    board_dt   = nse_acts.get("board_meeting_date")

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
        ("Stock",                 "NSE F&O symbol",                                  res["symbol"]),
        ("Current Market Price",  "Live last traded price",                          _fmt_inr(res["cmp"])),
        ("F&O Lot Size",          "Shares per contract lot",                         f"{lot_size:,}"),
        ("Trade Type",            "Buy-Write (new position) or Holdings (existing)", trade_type),
        ("Cost Basis / Share",    "Purchase price per share used for analysis",      _fmt_inr(pos["cost_basis_per_share"])),
        ("Purchase Cost (1 lot)", "Total capital at cost basis × lot size",          _fmt_inr(pos["total_cost"])),
        ("Days to Expiry",        "Calendar days remaining to selected expiry",      str(res["days_to_expiry"])),
        ("Approx. Futures Price", "CMP × (1 + 8% × DTE / 365) at 8% carry",         _fmt_inr(approx_futures)),
        ("Net Capital Required",  "Additional cash needed to complete the lot",      _fmt_inr(net_capital)),
    ]
    st.markdown(_kv_table_html(ps_rows), unsafe_allow_html=True)

    if pos["already_holds"] and last_qty > 0:
        st.caption(
            f"You hold {last_qty:,} of {lot_size:,} shares — "
            f"need {max(0, lot_size - last_qty):,} more at CMP to complete the lot."
        )

    # ── Equity Data ───────────────────────────────────────────────────────────
    st.markdown('<div class="section-hd">Equity Data</div>', unsafe_allow_html=True)
    st.caption(f"Fetched using yfinance ticker: `{ticker}`")

    wk52_h = intel.get("fifty_two_week_high")
    wk52_l = intel.get("fifty_two_week_low")

    ed_rows = [
        ("52-Week High",     "Highest closing price over the last 52 weeks",          _fmt_inr(wk52_h)),
        ("52-Week Low",      "Lowest closing price over the last 52 weeks",           _fmt_inr(wk52_l)),
        ("Beta",             "Price sensitivity relative to Nifty 50",               f"{intel['beta']:.2f}" if intel.get("beta") else "—"),
        ("Sector",           "Equity sector classification (from exchange data)",     intel.get("sector")   or "—"),
        ("Industry",         "Equity industry classification (from exchange data)",   intel.get("industry") or "—"),
        ("Sector HV 20-Day", "Annualised 20-day HV of the matching Nifty sector index",
         f"{sector_hv:.1f}%" if sector_hv else "—"),
    ]
    st.markdown(_kv_table_html(ed_rows), unsafe_allow_html=True)

    # ── Options API Data ──────────────────────────────────────────────────────
    st.markdown('<div class="section-hd">Options API Data</div>', unsafe_allow_html=True)

    # Strike selector — default to ATM
    strike_labels = [
        f"{s['strike_type']}  —  ₹{s['strike']:,.0f}"
        for s in res["strikes"]
    ]
    atm_default = next(
        (i for i, s in enumerate(res["strikes"]) if s["strike_type"] == "ATM"), 0
    )
    selected_label = st.selectbox(
        "Select strike to view options data",
        options=strike_labels,
        index=atm_default,
        key="opt_api_strike_sel",
        label_visibility="collapsed",
    )
    sel_idx = strike_labels.index(selected_label)
    sel_s   = res["strikes"][sel_idx]

    # Fetch live option data for the selected strike using specific strike_price
    # (strike_price=0 on the full chain doesn't return IV/OI/Volume from Breeze)
    opt_q = _fetch_option_quote(res["symbol"], res["expiry_date"], sel_s["strike"])

    # Fall back to chain data when the specific quote returns None
    iv_val  = opt_q.get("iv")            if opt_q.get("iv")            is not None else sel_s.get("iv")
    oi_val  = opt_q.get("open_interest") if opt_q.get("open_interest") is not None else sel_s.get("open_interest")
    vol_val = opt_q.get("volume")        if opt_q.get("volume")        is not None else sel_s.get("volume")
    ltp_val = opt_q.get("ltp")           if opt_q.get("ltp")           else           sel_s.get("premium")

    gross       = sel_s.get("gross_premium_total") or 0
    moneyness   = (sel_s["strike"] - res["cmp"]) / res["cmp"] * 100
    charges_pct = (sel_s["charges"]["total"] / gross * 100) if gross > 0 else 0

    opt_rows = [
        ("IV %",
         "Implied Volatility — the market's expectation of future price movement for this strike",
         f"{iv_val:.1f}%" if iv_val is not None else "—"),
        ("Open Interest",
         "Total outstanding contracts at this strike — proxy for liquidity",
         f"{oi_val:,}" if oi_val is not None else "—"),
        ("Volume",
         "Number of contracts traded today at this strike",
         f"{vol_val:,}" if vol_val is not None else "—"),
        ("LTP (premium)",
         "Last traded price of this call option (cross-check against analyse result)",
         _fmt_inr(ltp_val)),
        ("Moneyness %",
         "Strike distance from CMP — negative means ITM, positive means OTM",
         f"{moneyness:+.1f}%"),
        ("Charges %",
         "Total transaction costs as a percentage of gross premium",
         f"{charges_pct:.1f}%"),
    ]
    st.markdown(_kv_table_html(opt_rows), unsafe_allow_html=True)

    # Equity-level reference metrics that contextualise the option data
    st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)

    if wk52_h and wk52_l and wk52_h > wk52_l:
        pct_range = (res["cmp"] - wk52_l) / (wk52_h - wk52_l) * 100
        filled    = round(pct_range / 10)
        wk52_pos  = f"{'█' * filled}{'░' * (10 - filled)}  {pct_range:.0f}% of 52w range"
    else:
        wk52_pos  = "—"

    ref_rows = [
        ("52-Week Position",
         "CMP within the 52-week high–low band (0% = 52w low, 100% = 52w high)",
         wk52_pos),
        ("HV 20-Day",
         "Annualised 20-day historical volatility of the equity",
         f"{tech['hv_20_pct']:.1f}%" if tech.get("hv_20_pct") else "—"),
        ("ATR 14-Day",
         "Average True Range over the last 14 sessions — daily price noise in ₹",
         _fmt_inr(tech.get("atr_14"))),
    ]
    st.markdown(_kv_table_html(ref_rows), unsafe_allow_html=True)

    # ── Market Intelligence ───────────────────────────────────────────────────
    st.markdown('<div class="section-hd">Market Intelligence</div>', unsafe_allow_html=True)

    # Earnings warning banner
    if earn_date:
        try:
            earn_dt = datetime.datetime.strptime(earn_date, "%d %b %Y").date()
            exp_dt  = datetime.datetime.strptime(res["expiry_date"], "%Y-%m-%d").date()
            if earn_dt <= exp_dt:
                st.warning(
                    f"⚠ Earnings on **{earn_date}** falls within this expiry. "
                    "IV typically spikes into results — assignment and gap-down risk elevated."
                )
        except Exception:
            pass

    # Ex-dividend warning
    if ex_div:
        try:
            exd_dt = datetime.datetime.strptime(ex_div, "%d %b %Y").date()
            exp_dt = datetime.datetime.strptime(res["expiry_date"], "%Y-%m-%d").date()
            if exd_dt <= exp_dt:
                st.info(
                    f"ℹ Ex-dividend date **{ex_div}** is within this expiry. "
                    "Deep ITM calls carry early-assignment risk before dividend capture."
                )
        except Exception:
            pass

    n_analysts = intel.get("analyst_count") or 0

    def _fmt_targets() -> str:
        lo = intel.get("analyst_target_low")
        mn = intel.get("analyst_target_mean")
        hi = intel.get("analyst_target_high")
        if not any([lo, mn, hi]):
            return "—"
        return "  |  ".join(filter(None, [
            f"Low {_fmt_inr(lo)}"     if lo else None,
            f"Target {_fmt_inr(mn)}"  if mn else None,
            f"High {_fmt_inr(hi)}"    if hi else None,
        ]))

    mi_rows = [
        ("Earnings Date",    "Next quarterly / annual results announcement",           earn_date or "—"),
        ("Ex-Dividend Date", "Shares go ex-div (early assignment risk for ITM calls)", ex_div    or "—"),
        ("Board Meeting",    "Next board meeting date",                                board_dt  or "—"),
        ("AGM",              "Annual General Meeting date",                            agm_date  or "—"),
        ("Analyst Targets",  f"Consensus price targets from {n_analysts} analysts",   _fmt_targets()),
        ("Recommendation",   "Analyst consensus rating",
         (intel.get("analyst_recommendation") or "—").upper()),
    ]
    st.markdown(_kv_table_html(mi_rows), unsafe_allow_html=True)

    # ── Strike Analysis ───────────────────────────────────────────────────────
    st.markdown('<div class="section-hd">Strike Analysis</div>', unsafe_allow_html=True)

    rows = []
    for s in res["strikes"]:
        rows.append({
            "Type":           s["strike_type"],
            "Strike (₹)":     f"₹{s['strike']:,.0f}",
            "Premium (₹)":    f"₹{s['premium']:,.2f}",
            "Net premium":    _fmt_inr(s["net_premium_total"]),
            "Breakeven":      _fmt_inr(s["breakeven"]),
            "Max profit":     _fmt_inr(s["max_profit_total"]),
            "Yield %":        f"{s['premium_yield_pct']:.2f}%",
            "Ann. yield %":   (f"{s['annualised_yield_pct']:.1f}%"
                               if s["annualised_yield_pct"] is not None else "—"),
            "Downside prot.": f"{s['downside_protection_pct']:.2f}%",
        })
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True, height=185)

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
    st.dataframe(placeholder, width="stretch", hide_index=True, height=185)
