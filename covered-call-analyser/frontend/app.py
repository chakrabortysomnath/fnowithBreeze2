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

from auth import check_auth
from nav import NAV_CSS, nav_bar

# ── Static equity metadata (sector / industry lookup) ─────────────────────────
import json as _json
import pathlib as _pathlib
_EQUITY_META_PATH = _pathlib.Path(__file__).parent / "equity_meta.json"
_EQUITY_META: dict = (
    _json.loads(_EQUITY_META_PATH.read_text()) if _EQUITY_META_PATH.exists() else {}
)

# ── Logging ───────────────────────────────────────────────────────────────────

import logging
logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────

BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000").rstrip("/")

# PING_URL — health-check URL polled periodically to show connection status.
# Defaults to BACKEND_URL/health.  Set to empty string "" to disable the ping banner.
PING_URL = os.environ.get("PING_URL", f"{BACKEND_URL}/health").strip()

# HEALTH_CHECK_TTL — seconds between health-check HTTP calls (Streamlit cache TTL).
# Increase to reduce network noise; decrease for faster Breeze-disconnect detection.
# Default: 30 s.  Set via HEALTH_CHECK_TTL env var in the Render dashboard.
_hc_ttl_raw = os.environ.get("HEALTH_CHECK_TTL", "30")
try:
    HEALTH_CHECK_TTL = max(5, int(_hc_ttl_raw))   # floor at 5 s to prevent hammering
except ValueError:
    HEALTH_CHECK_TTL = 30

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

check_auth()

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

@st.cache_data(ttl=HEALTH_CHECK_TTL)
def _ping_backend(url: str) -> dict:
    """Hit the /health endpoint and return the JSON response.

    Cached for HEALTH_CHECK_TTL seconds so repeated Streamlit reruns
    (widget interactions, etc.) do not hammer the backend.
    """
    return requests.get(url, timeout=5).json()

if PING_URL:
    try:
        h = _ping_backend(PING_URL)
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
    ("bypass_intel",  os.environ.get("CLAUDE_INTEL_BYPASS", "").lower() == "true"),
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


@st.cache_data(ttl=86_400)
def _fetch_ohlc(ticker: str) -> pd.DataFrame | None:
    """Fetch 1-year daily OHLC from yfinance. ticker is a resolved yfinance symbol.

    1-year data is used to compute 52-week H/L, beta, HV-20, ATR-14, support/resistance,
    and momentum — all derived in Python without a Claude API call.
    The candlestick chart slices the last 22 rows (~1 month) at render time.
    TTL set to 86 400s (24 h) — 52-week stats don't change intraday.
    """
    import time
    import yfinance as yf
    criteria = f"ticker={ticker} period=1y interval=1d"
    source   = "yfinance/download"
    for attempt in range(3):
        try:
            df = yf.download(ticker, period="1y", interval="1d",
                             progress=False, auto_adjust=True)
            if not df.empty:
                df.index = pd.to_datetime(df.index)
                return df
            # yfinance swallows rate-limit errors and returns empty DF — treat as retriable
            if attempt < 2:
                wait = 2 ** (attempt + 1)
                logger.warning(
                    f"Data Collect for {ticker} 1y rate-limit/empty (attempt {attempt+1}), "
                    f"retrying in {wait}s | SEARCHED WITH - {criteria}, SOURCE - {source}"
                )
                time.sleep(wait)
                continue
            logger.warning(
                f"Data Collect for {ticker} 1y failed (empty after {attempt+1} attempts), "
                f"SEARCHED WITH - {criteria}, SOURCE - {source}"
            )
            return None
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


@st.cache_data(ttl=86_400)   # 24 h — analyst targets and corporate dates change at most daily
def _fetch_intel_claude(symbol: str, nse_symbol: str, cmp: float, bypass_intel: bool = False) -> dict:
    """Fetch analyst targets and corporate calendar dates via Claude API.

    Scope deliberately limited to data that cannot be computed from OHLC:
      sector, industry (for stocks absent from equity_meta.json),
      analyst_target_low/mean/high, analyst_recommendation, analyst_count,
      earnings_date, ex_dividend_date, board_meeting_date, agm_date.

    Fields now derived purely in Python (NOT fetched here):
      fifty_two_week_high/low, beta, atr_14, hv_20_pct, sector_hv,
      key_support, key_resistance, momentum_outlook, rr_itm/atm/otm1/otm2.

    sector/industry are pre-populated from _EQUITY_META (equity_meta.json) when available,
    reducing the Claude schema further for the top-50 F&O stocks.

    Returns all-None dict on failure so callers need no error handling.
    Includes _source ("claude_api" | "mock" | "blank") and token/cost metadata.
    """
    import json
    import anthropic

    # Slim blank — only fields Claude is still responsible for
    blank = dict(
        sector=None, industry=None,
        analyst_target_low=None, analyst_target_mean=None, analyst_target_high=None,
        analyst_recommendation=None, analyst_count=None,
        earnings_date=None, ex_dividend_date=None,
        agm_date=None, board_meeting_date=None,
        _source="blank", _input_tokens=0, _output_tokens=0, _cost_usd=0.0,
    )

    # ── Bypass mode ───────────────────────────────────────────────────────────
    if bypass_intel or os.environ.get("CLAUDE_INTEL_BYPASS", "").lower() == "true":
        today_dt = datetime.date.today()
        logger.warning(
            f"Data Collect for {nse_symbol} - CLAUDE_INTEL_BYPASS=true, returning mock data"
        )
        # Sector/industry from static lookup when available, else mock values
        _meta = _EQUITY_META.get(symbol.upper(), {})
        return dict(
            sector=_meta.get("sector", "Consumer Staples"),
            industry=_meta.get("industry", "Household Products"),
            analyst_target_low=round(cmp * 0.92, 2),
            analyst_target_mean=round(cmp * 1.08, 2),
            analyst_target_high=round(cmp * 1.25, 2),
            analyst_recommendation="hold",
            analyst_count=22,
            earnings_date=(today_dt + datetime.timedelta(days=45)).strftime("%d %b %Y"),
            ex_dividend_date=(today_dt + datetime.timedelta(days=90)).strftime("%d %b %Y"),
            board_meeting_date=(today_dt + datetime.timedelta(days=42)).strftime("%d %b %Y"),
            agm_date=(today_dt + datetime.timedelta(days=120)).strftime("%d %b %Y"),
            _source="mock", _input_tokens=0, _output_tokens=0, _cost_usd=0.0,
        )

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        logger.warning(
            f"Data Collect for {nse_symbol} - ANTHROPIC_API_KEY not set, "
            f"skipping Claude intel fetch"
        )
        return blank

    # ── Static sector/industry from equity_meta.json ──────────────────────────
    _meta            = _EQUITY_META.get(symbol.upper(), {})
    _static_sector   = _meta.get("sector")
    _static_industry = _meta.get("industry")
    _has_static_meta = bool(_static_sector and _static_industry)

    # ── Build schema — conditionally include sector/industry ──────────────────
    # Anthropic caches the system block; cache_control is on the full string, so we
    # build the prompt string first, then pass it with cache_control in the API call.
    _schema_fields = "{\n"
    if not _has_static_meta:
        _schema_fields += (
            '  "sector": <string — one of: "Consumer Staples", "Consumer Discretionary", '
            '"Technology", "Financial Services", "Healthcare", "Energy", "Basic Materials", '
            '"Industrials", "Real Estate", "Communication Services", or null>,\n'
            '  "industry": <string — specific industry sub-classification>,\n'
        )
    _schema_fields += (
        '  "analyst_target_low": <number — lowest analyst 12-month price target in ₹>,\n'
        '  "analyst_target_mean": <number — consensus analyst 12-month price target in ₹>,\n'
        '  "analyst_target_high": <number — highest analyst 12-month price target in ₹>,\n'
        '  "analyst_recommendation": <string — one of: "strong_buy", "buy", "hold", "underperform", "sell">,\n'
        '  "analyst_count": <integer — approximate number of analysts covering the stock>,\n'
        '  "earnings_date": <string "DD Mon YYYY" — next quarterly/annual results date, or null>,\n'
        '  "ex_dividend_date": <string "DD Mon YYYY" — next ex-dividend date, or null>,\n'
        '  "board_meeting_date": <string "DD Mon YYYY" — next board meeting date, or null>,\n'
        '  "agm_date": <string "DD Mon YYYY" — next AGM date, or null>\n'
        "}\n"
    )
    _SYSTEM = (
        "You are a financial data assistant for Indian NSE equities.\n"
        "Return ONLY a valid JSON object with these exact keys "
        "(use null for unknown/uncertain values):\n"
        + _schema_fields
        + "Rules:\n"
        "- All date strings must be after TODAY (supplied in the user message). "
        "Use null for past/unknown dates.\n"
        "- Return ONLY the JSON object, no explanation or markdown."
    )

    today = datetime.date.today().strftime("%d %b %Y")
    user_msg = (
        f"Stock: {nse_symbol} (F&O code: {symbol}, NSE India)\n"
        f"CMP as of {today}: ₹{cmp:.2f}\n"
        f"Today's date: {today}"
    )

    import time
    client = anthropic.Anthropic(api_key=api_key)
    msg = None
    last_exc = None
    for attempt in range(4):          # up to 4 attempts: 0 s, 2 s, 4 s, 8 s
        if attempt:
            time.sleep(2 ** attempt)
        try:
            msg = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=400,                       # schema now ≤11 fields; output ≈120–160 tokens
                system=[{
                    "type": "text",
                    "text": _SYSTEM,
                    "cache_control": {"type": "ephemeral"},  # Anthropic caches this block across calls
                }],
                messages=[{"role": "user", "content": user_msg}],
            )
            break                     # success — exit retry loop
        except anthropic.APIStatusError as exc:
            last_exc = exc
            if exc.status_code in (429, 529):
                logger.warning(
                    f"Data Collect for {nse_symbol} Claude API attempt {attempt + 1} "
                    f"hit {exc.status_code}, retrying…"
                )
                continue
            # Non-retriable API error — log and return blank immediately
            logger.warning(
                f"Data Collect for {nse_symbol} Claude API intel failed | error: {exc}"
            )
            return blank
        except Exception as exc:
            logger.warning(
                f"Data Collect for {nse_symbol} Claude API intel failed | error: {exc}"
            )
            return blank

    if msg is None:
        logger.warning(
            f"Data Collect for {nse_symbol} Claude API intel failed after retries "
            f"| last error: {last_exc}"
        )
        return blank

    try:
        raw = msg.content[0].text.strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            parts = raw.split("```")
            raw = parts[1] if len(parts) > 1 else raw
            if raw.startswith("json"):
                raw = raw[4:]
        data = json.loads(raw.strip())
        result = dict(blank)
        for key, val in data.items():
            if val is not None:
                result[key] = val

        # Overlay static sector/industry — always wins over Claude estimate
        if _static_sector:
            result["sector"] = _static_sector
        if _static_industry:
            result["industry"] = _static_industry

        # Compute actual cost from token usage reported by the API
        in_tok  = msg.usage.input_tokens
        out_tok = msg.usage.output_tokens
        cost    = in_tok * 0.80 / 1_000_000 + out_tok * 4.00 / 1_000_000  # Haiku 4.5 pricing
        result["_source"]        = "claude_api"
        result["_input_tokens"]  = in_tok
        result["_output_tokens"] = out_tok
        result["_cost_usd"]      = cost

        _meta_note = " (sector/industry from static JSON)" if _has_static_meta else ""
        populated = sum(1 for k, v in result.items() if not k.startswith("_") and v is not None)
        logger.warning(
            f"Data Collect for {nse_symbol} - Claude API intel returned "
            f"{populated} populated fields{_meta_note} | {in_tok} in + {out_tok} out tokens "
            f"| cost ${cost:.4f} | SOURCE - Claude API / claude-haiku-4-5"
        )
        return result
    except Exception as exc:
        logger.warning(
            f"Data Collect for {nse_symbol} Claude API intel parse failed | error: {exc}"
        )
        return blank


def _fmt_inr(v) -> str:
    if v is None:
        return "-"
    return f"₹{v:,.2f}"


import math as _math

def _bs_call_price(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """Black-Scholes European call price."""
    if sigma <= 0 or T <= 0:
        return max(S - K * _math.exp(-r * T), 0.0)
    d1 = (_math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * _math.sqrt(T))
    d2 = d1 - sigma * _math.sqrt(T)
    N  = lambda x: 0.5 * (1.0 + _math.erf(x / _math.sqrt(2.0)))
    return S * N(d1) - K * _math.exp(-r * T) * N(d2)


def _bs_iv(S: float, K: float, T_days: float, C: float, r: float = 0.065) -> float | None:
    """Implied volatility (annualised %) via bisection. Returns None when unsolvable."""
    if T_days <= 0 or C <= 0 or S <= 0 or K <= 0:
        return None
    T = T_days / 365.0
    lo, hi = 0.001, 5.0          # 0.1% – 500%
    intrinsic = max(S - K * _math.exp(-r * T), 0.0)
    if C <= intrinsic:            # below intrinsic — no valid IV
        return None
    for _ in range(120):
        mid   = (lo + hi) / 2.0
        price = _bs_call_price(S, K, T, r, mid)
        if abs(price - C) < 0.01:
            return round(mid * 100, 1)
        if price < C:
            lo = mid
        else:
            hi = mid
    return round(((lo + hi) / 2.0) * 100, 1)


def _bs_greeks(
    S: float, K: float, T_days: float, sigma_pct: float,
    ltp_per_share: float, r: float = 0.065,
) -> dict | None:
    """Black-Scholes Greeks for a European call option (per share).

    Returns a dict with:
      delta        — N(d1): call option delta (probability of expiring ITM)
      gamma        — Γ: change in delta per ₹1 CMP move
      theta_per_day — daily time decay in ₹/share from SELLER perspective (positive = favourable)
      vega         — ₹ change per 1% decrease in IV (negative = seller loses if IV rises, shown as positive loss)
      rho          — ₹ change per 1% increase in risk-free rate
      implied_put  — theoretical put price from put-call parity: P = C + K·e^(−rT) − S
      intrinsic    — max(S − K, 0) per share (call intrinsic value)
      time_value   — LTP − intrinsic (time + volatility value component)
    """
    T = T_days / 365.0
    sigma = sigma_pct / 100.0
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return None
    try:
        d1 = (_math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * _math.sqrt(T))
        d2 = d1 - sigma * _math.sqrt(T)
        N  = lambda x: 0.5 * (1.0 + _math.erf(x / _math.sqrt(2.0)))
        Np = lambda x: _math.exp(-0.5 * x * x) / _math.sqrt(2.0 * _math.pi)
        KerT = K * _math.exp(-r * T)

        delta = N(d1)
        gamma = Np(d1) / (S * sigma * _math.sqrt(T))
        # Theta for long call per day (negative = cost for holder)
        theta_long = -(S * Np(d1) * sigma / (2.0 * _math.sqrt(T)) + r * KerT * N(d2)) / 365.0
        theta_seller = -theta_long          # seller gains from time decay (positive)
        vega  = S * Np(d1) * _math.sqrt(T) / 100.0   # per 1% IV change
        rho   = KerT * T * N(d2) / 100.0              # per 1% rate change

        implied_put = max(ltp_per_share + KerT - S, 0.0)
        intrinsic   = max(S - K, 0.0)
        time_value  = ltp_per_share - intrinsic

        return {
            "delta":         round(delta,         4),
            "gamma":         round(gamma,         6),
            "theta_per_day": round(theta_seller,  4),
            "vega":          round(vega,           4),
            "rho":           round(rho,            4),
            "implied_put":   round(implied_put,    2),
            "intrinsic":     round(intrinsic,      2),
            "time_value":    round(time_value,     2),
        }
    except Exception:
        return None


def _strike_options_table_html(
    strikes: list[dict], cmp: float, greeks_data: dict, dte: int,
) -> str:
    """HTML for the Strike & Options Analysis table.

    Rows = metrics (grouped by section), Columns = ITM / ATM / OTM+1 / OTM+2.
    Each column header has a tooltip with the strike-type explanation.
    """
    TIPS = {
        "ITM":   ("In The Money — strike below CMP. Highest premium, most downside protection, "
                  "upside capped immediately. Best when expecting flat or mildly bearish price action."),
        "ATM":   ("At The Money — strike nearest to CMP. Balanced premium vs upside participation. "
                  "Maximum option time value. Best for a neutral-to-slightly-bullish outlook."),
        "OTM+1": ("Out of The Money (+1 step) — one strike above CMP. Lower premium, lets you "
                  "participate in modest stock upside before the call caps gains."),
        "OTM+2": ("Out of The Money (+2 steps) — two strikes above CMP. Lowest premium, maximum "
                  "upside participation in the covered call. Best when mildly bullish."),
    }
    CLR = {"ITM": "#6A8FBF", "ATM": "#58A6FF", "OTM+1": "#20A4A0", "OTM+2": "#39D0C8"}

    s_map   = {s["strike_type"]: s for s in strikes}
    types   = [t for t in ("ITM", "ATM", "OTM+1", "OTM+2") if t in s_map]
    ncols   = len(types) + 1

    hd = ("padding:8px 10px;border-bottom:2px solid #30363D;"
          "color:#8B949E;font-size:11px;font-weight:600;white-space:nowrap;")
    td = ("padding:6px 10px;border-bottom:1px solid #21262D;"
          "color:#C9D1D9;font-size:12px;text-align:right;"
          "font-family:'Courier New',monospace;white-space:nowrap;")
    mtd = ("padding:6px 10px;border-bottom:1px solid #21262D;"
           "color:#E6EDF3;font-size:12px;text-align:left;")
    shd = ("padding:5px 10px;background:#161B22;"
           "color:#58A6FF;font-size:11px;font-weight:700;letter-spacing:0.5px;")

    def _v(stype: str, key: str, subkey: str | None = None):
        s = s_map.get(stype)
        if s is None:
            return None
        v = s.get(key)
        if subkey is not None:
            return v.get(subkey) if isinstance(v, dict) else None
        return v

    def _gv(stype: str, key: str):
        g = greeks_data.get(stype)
        return g.get(key) if g else None

    def _fmt(v, fmt: str) -> str:
        if v is None:
            return "—"
        try:
            if fmt == "inr":       return f"₹{v:,.2f}"
            if fmt == "inr0":      return f"₹{v:,.0f}"
            if fmt == "pct1":      return f"{v:.1f}%"
            if fmt == "pct2":      return f"{v:.2f}%"
            if fmt == "spct1":     return f"{v:+.1f}%"
            if fmt == "int":       return f"{v:,}"
            if fmt == "f4":        return f"{v:.4f}"
            if fmt == "f6":        return f"{v:.6f}"
            return str(v)
        except Exception:
            return "—"

    def sec(title: str) -> str:
        return f'<tr><td colspan="{ncols}" style="{shd}">{title}</td></tr>'

    def row(metric: str, tip: str, vals: dict, fmt: str) -> str:
        tip_a = f' title="{tip}"' if tip else ""
        icon  = (' <span style="color:#8B949E;font-size:10px;cursor:help;">ⓘ</span>'
                 if tip else "")
        r = f'<tr><td style="{mtd}"{tip_a}>{metric}{icon}</td>'
        for t in types:
            r += f'<td style="{td}">{_fmt(vals.get(t), fmt)}</td>'
        return r + "</tr>"

    out = [
        '<div style="overflow-x:auto;">',
        '<table style="width:100%;border-collapse:collapse;'
        'font-family:Inter,\'Segoe UI\',sans-serif;">',
        '<thead><tr>',
        f'<th style="{hd} text-align:left;min-width:170px;">Metric</th>',
    ]
    for t in types:
        s   = s_map[t]
        clr = CLR.get(t, "#8B949E")
        tip = TIPS.get(t, "")
        out.append(
            f'<th style="{hd} text-align:right;" title="{tip}">'
            f'<span style="color:{clr};font-weight:700;">{t}</span><br>'
            f'<span style="color:#E6EDF3;font-size:12px;">₹{s["strike"]:,.0f}</span>'
            f'</th>'
        )
    out.append('</tr></thead><tbody>')

    # ── STRIKES ──────────────────────────────────────────────────────────────
    out.append(sec("── STRIKES ──"))
    out.append(row("Moneyness %",
                   "(Strike − CMP) / CMP × 100. Negative = ITM, positive = OTM.",
                   {t: (_v(t, "strike") - cmp) / cmp * 100 for t in types}, "spct1"))
    out.append(row("Intrinsic Value (₹/share)",
                   "max(CMP − Strike, 0) — minimum value if expiry were today.",
                   {t: max(cmp - _v(t, "strike"), 0.0) for t in types}, "inr"))
    out.append(row("Time Value (₹/share)",
                   "Premium LTP − Intrinsic Value. Value from time remaining and volatility.",
                   {t: _gv(t, "time_value") for t in types}, "inr"))

    # ── PREMIUM & INCOME ─────────────────────────────────────────────────────
    out.append(sec("── PREMIUM & INCOME ──"))
    out.append(row("Gross Premium LTP (₹/share)",
                   "Option last traded price — gross premium per share before any charges.",
                   {t: _v(t, "premium") for t in types}, "inr"))
    out.append(row("Net Premium / Share (₹)",
                   "Gross premium minus all charges, per share.",
                   {t: _v(t, "net_premium_per_share") for t in types}, "inr"))
    out.append(row("Net Premium Total (₹)",
                   "Total net premium for the full lot after all charges.",
                   {t: _v(t, "net_premium_total") for t in types}, "inr"))
    out.append(row("Charges Total (₹)",
                   "Total transaction costs: STT + Brokerage + GST.",
                   {t: _v(t, "charges", "total") for t in types}, "inr"))
    out.append(row("  ↳ STT (₹)",
                   "Securities Transaction Tax on gross premium received (0.1%).",
                   {t: _v(t, "charges", "stt") for t in types}, "inr"))
    out.append(row("  ↳ Brokerage (₹)",
                   "Fixed brokerage per lot written.",
                   {t: _v(t, "charges", "brokerage") for t in types}, "inr"))
    out.append(row("  ↳ GST (₹)",
                   "Goods & Services Tax on brokerage (18%).",
                   {t: _v(t, "charges", "gst") for t in types}, "inr"))
    out.append(row("Charges %",
                   "Total charges as percentage of gross premium — cost drag.",
                   {t: (_v(t, "charges", "total") / _v(t, "gross_premium_total") * 100
                        if _v(t, "gross_premium_total") else None)
                    for t in types}, "pct1"))

    # ── MARKET DATA ──────────────────────────────────────────────────────────
    out.append(sec("── MARKET DATA ──"))
    out.append(row("Implied Volatility %",
                   "Market's expected future price movement. From Breeze live feed or "
                   "computed via Black-Scholes inversion from the LTP.",
                   {t: _v(t, "_iv_enriched") for t in types}, "pct1"))
    out.append(row("Open Interest",
                   "Total outstanding contracts at this strike — higher = more liquid.",
                   {t: _v(t, "open_interest") for t in types}, "int"))
    out.append(row("Volume",
                   "Number of contracts traded today — use as secondary liquidity signal.",
                   {t: _v(t, "volume") for t in types}, "int"))

    # ── PERFORMANCE ──────────────────────────────────────────────────────────
    out.append(sec("── PERFORMANCE ──"))
    out.append(row("Breakeven (₹)",
                   "Stock price at expiry where position P&L = 0: Cost Basis − Net Premium/Share.",
                   {t: _v(t, "breakeven") for t in types}, "inr0"))
    out.append(row("Downside Protection %",
                   "How far stock can fall from CMP before a loss: (CMP − Breakeven) / CMP.",
                   {t: _v(t, "downside_protection_pct") for t in types}, "pct2"))
    out.append(row("Premium Yield %",
                   "Net premium as % of total capital deployed (net_premium / total_cost).",
                   {t: _v(t, "premium_yield_pct") for t in types}, "pct2"))
    out.append(row("★ Annualised Yield %",
                   "Premium yield scaled to 365 days. Compare against FD or debt-fund returns.",
                   {t: _v(t, "annualised_yield_pct") for t in types}, "pct1"))
    out.append(row("Max Profit Total (₹)",
                   "Best-case P&L if stock is called away at strike: "
                   "(Strike − Cost Basis + Net Premium/Share) × Shares.",
                   {t: _v(t, "max_profit_total") for t in types}, "inr"))

    # ── GREEKS ───────────────────────────────────────────────────────────────
    out.append(sec("── GREEKS (Black-Scholes, r = 6.5%) ──"))
    out.append(
        f'<tr><td colspan="{ncols}" style="padding:3px 10px 5px;'
        f'color:#8B949E;font-size:11px;font-style:italic;">'
        f'Δ / Γ / Vega / ρ show call-option values. '
        f'Θ is from the seller\'s perspective (positive = time decay is favourable). '
        f'Vega shown as loss per +1% IV (seller is short vega).'
        f'</td></tr>'
    )
    out.append(row("Δ Delta",
                   "Call delta = N(d1): probability of expiring ITM and sensitivity to CMP. "
                   "Net position delta = 1.0 (long stock) − Δ (short call).",
                   {t: _gv(t, "delta") for t in types}, "f4"))
    out.append(row("Γ Gamma",
                   "Rate of change of delta per ₹1 move in CMP. "
                   "High gamma near ATM means delta changes rapidly.",
                   {t: _gv(t, "gamma") for t in types}, "f6"))
    out.append(row("Θ Theta / day (₹/share, seller)",
                   "Daily time decay benefit for the call seller — option loses this much value per calendar day.",
                   {t: _gv(t, "theta_per_day") for t in types}, "inr"))
    out.append(row("V Vega loss / +1% IV (₹/share)",
                   "₹ loss per share per +1% rise in implied volatility. "
                   "Short-call seller is short vega — rising IV increases the cost to close.",
                   {t: _gv(t, "vega") for t in types}, "inr"))
    out.append(row("ρ Rho / +1% rate (₹/share)",
                   "₹ change per 1% increase in the risk-free rate. "
                   "Positive for long call; minor effect for short-dated options.",
                   {t: _gv(t, "rho") for t in types}, "inr"))

    # ── PUT-CALL SUMMARY ────────────────────────────────────────────────────
    out.append(sec("── PUT-CALL SUMMARY ──"))
    out.append(
        f'<tr><td colspan="{ncols}" style="padding:3px 10px 5px;'
        f'color:#8B949E;font-size:11px;font-style:italic;">'
        f'Theoretical put prices derived from Put-Call Parity (P = C + K·e^(−rT) − S). '
        f'No put chain data fetched — use for quick cost comparison only.'
        f'</td></tr>'
    )
    out.append(row("Implied Put Price (₹/share)",
                   "Theoretical European put price from Put-Call Parity. "
                   "Actual traded put may differ due to early-exercise premium (American options).",
                   {t: _gv(t, "implied_put") for t in types}, "inr"))
    out.append(row("Put Delta (approx.)",
                   "Approximate put delta = Δ − 1 (from Put-Call parity). Negative for long put.",
                   {t: ((_gv(t, "delta") or 0) - 1.0) if _gv(t, "delta") is not None else None
                    for t in types}, "f4"))

    out.append('</tbody></table></div>')
    return "".join(out)


def _common_rr_card_html(
    pos: dict, res: dict, equity_data: dict, tech: dict,
) -> str:
    """HTML card for the common (non-strike-specific) Risk/Reward summary."""
    cmp   = res["cmp"]
    lot   = res["lot_size"]
    dte   = res["days_to_expiry"]
    sup   = equity_data.get("key_support")
    res_  = equity_data.get("key_resistance")
    hv    = tech.get("hv_20_pct") or equity_data.get("hv_20_pct")
    mom   = equity_data.get("momentum_outlook")

    trade_type = "Holdings (existing position)" if pos["already_holds"] else "Buy-Write (new position)"
    gross_cap  = lot * cmp

    data_rows = [
        ("Trade Type",   trade_type),
        ("Position",     f"{pos['lots']:,} lot × {lot:,} shares = {pos['shares']:,} shares"),
        ("Gross Capital",_fmt_inr(gross_cap)),
    ]
    if hv:
        monthly_sig = hv / _math.sqrt(12)
        data_rows.append(("HV 20-Day (ann.)",      f"{hv:.1f}%"))
        data_rows.append(("Expected ±1σ / month",  f"±{monthly_sig:.1f}%"))
    if sup or res_:
        data_rows.append(("Support / Resistance",  f"{_fmt_inr(sup)} / {_fmt_inr(res_)}"))
    if mom:
        icon = {"bullish": "▲", "neutral": "▶", "bearish": "▼"}.get(mom, "")
        data_rows.append(("Momentum", f"{icon} {mom.capitalize()}"))

    cell = "padding:5px 12px;border-bottom:1px solid #30363D;"
    rows_html = "".join(
        f'<tr>'
        f'<td style="{cell} width:48%;color:#8B949E;font-size:12px;">{n}</td>'
        f'<td style="{cell} width:52%;text-align:right;color:#E6EDF3;font-size:12px;'
        f'font-family:\'Courier New\',monospace;">{v}</td>'
        f'</tr>'
        for n, v in data_rows
    )

    # Commentary
    parts = [
        f"{res['symbol']} at ₹{cmp:,.0f} with {dte} days to {res['expiry_date']} expiry.",
    ]
    if pos["already_holds"]:
        parts.append(
            f"Writing calls against {lot:,}-share holding "
            f"(cost basis ₹{pos['cost_basis_per_share']:,.0f}/share)."
        )
    else:
        parts.append(f"Fresh buy-write — ₹{gross_cap:,.0f} total equity capital for 1 lot.")
    if hv:
        msig = hv / _math.sqrt(12)
        parts.append(f"HV {hv:.0f}% p.a. implies ±{msig:.1f}% expected monthly move.")
    if sup and res_ and sup < cmp:
        band = (res_ - sup) / cmp * 100 if cmp > 0 else 0
        parts.append(f"Technical range ₹{sup:,.0f}–₹{res_:,.0f} ({band:.1f}% band).")
    if mom:
        parts.append(f"Short-term momentum: {mom}.")
    parts.append("See per-strike cards below to compare risk/reward across ITM/ATM/OTM strikes.")

    commentary = " ".join(parts)

    return (
        f'<div style="background:rgba(88,166,255,0.06);border-left:3px solid #58A6FF;'
        f'border-radius:6px;margin-bottom:14px;overflow:hidden;">'
        f'<div style="padding:10px 14px 6px;">'
        f'<span style="color:#58A6FF;font-size:14px;font-weight:700;">'
        f'Position Summary</span>'
        f'</div>'
        f'<table style="width:100%;border-collapse:collapse;">{rows_html}</table>'
        f'<div style="padding:8px 14px 10px;background:rgba(88,166,255,0.03);'
        f'border-top:1px solid #30363D;">'
        f'<span style="color:#8B949E;font-size:12px;line-height:1.6;">{commentary}</span>'
        f'</div>'
        f'</div>'
    )



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


def _compute_technicals(
    ohlc: pd.DataFrame | None,
    symbol: str = "unknown",
    claude_estimates: dict | None = None,
) -> dict:
    """Compute ATR-14 and annualised HV-20 from a daily OHLC dataframe.

    Falls back to claude_estimates when OHLC is unavailable (e.g. yfinance rate-limited).
    """
    blank = dict(atr_14=None, hv_20_pct=None)
    rows  = len(ohlc) if ohlc is not None else 0
    if ohlc is None or ohlc.empty or rows < 3:
        if claude_estimates:
            fb = {
                "atr_14":    claude_estimates.get("atr_14"),
                "hv_20_pct": claude_estimates.get("hv_20_pct"),
            }
            if any(v is not None for v in fb.values()):
                logger.warning(
                    f"Data Collect for {symbol} [ATR-14, HV-20] using Claude estimates "
                    f"(ohlc rows={rows}), SOURCE - Claude API"
                )
                return fb
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


@st.cache_data(ttl=86_400)
def _fetch_nifty_ohlc() -> pd.DataFrame | None:
    """Fetch 1-year daily OHLC for Nifty 50 (^NSEI) — used to compute stock beta."""
    import yfinance as yf
    try:
        df = yf.download("^NSEI", period="1y", interval="1d",
                         progress=False, auto_adjust=True)
        if not df.empty:
            df.index = pd.to_datetime(df.index)
            return df
        logger.warning("Data Collect for ^NSEI [Nifty OHLC] blank — empty dataframe")
        return None
    except Exception as exc:
        logger.warning(f"Data Collect for ^NSEI [Nifty OHLC] failed | error: {exc}")
        return None


def _compute_fundamentals(
    ohlc: pd.DataFrame | None,
    nifty_ohlc: pd.DataFrame | None,
    cmp: float,
    symbol: str = "unknown",
) -> dict:
    """Compute 52w H/L, beta, support, resistance, and momentum from 1-year OHLC.

    All fields that were previously fetched from Claude are derived here in pure Python:
    - fifty_two_week_high / low  — max/min of 1-year close series
    - key_support                — lowest close of last 20 sessions (recent swing low)
    - key_resistance             — highest close of last 20 sessions (recent swing high)
    - momentum_outlook           — CMP vs 20-day SMA (±1% neutral band)
    - beta                       — log-return covariance with Nifty 50
    """
    out = dict(
        fifty_two_week_high=None,
        fifty_two_week_low=None,
        beta=None,
        key_support=None,
        key_resistance=None,
        momentum_outlook=None,
    )
    if ohlc is None or ohlc.empty or len(ohlc) < 5:
        logger.warning(
            f"Data Collect for {symbol} [fundamentals] blank — insufficient OHLC rows"
        )
        return out

    close = ohlc["Close"].squeeze().astype(float)

    # 52-week high / low
    out["fifty_two_week_high"] = round(float(close.max()), 2)
    out["fifty_two_week_low"]  = round(float(close.min()), 2)

    # Support = lowest close of last 20 sessions; resistance = highest of last 20
    window = min(20, len(close))
    out["key_support"]    = round(float(close.iloc[-window:].min()), 2)
    out["key_resistance"] = round(float(close.iloc[-window:].max()), 2)

    # Momentum: CMP vs 20-day SMA (±1% band → neutral)
    if len(close) >= 20:
        sma20 = float(close.rolling(20).mean().iloc[-1])
        if sma20 > 0:
            ratio = (cmp - sma20) / sma20 * 100
            out["momentum_outlook"] = (
                "bullish" if ratio > 1.0 else ("bearish" if ratio < -1.0 else "neutral")
            )

    # Beta vs Nifty 50 (log-return covariance method)
    if nifty_ohlc is not None and not nifty_ohlc.empty:
        try:
            nifty_close = nifty_ohlc["Close"].squeeze().astype(float)
            stock_ret   = np.log(close       / close.shift(1)).dropna()
            nifty_ret   = np.log(nifty_close / nifty_close.shift(1)).dropna()
            aligned     = pd.concat([stock_ret, nifty_ret], axis=1, join="inner").dropna()
            if len(aligned) >= 20:
                cov = float(aligned.iloc[:, 0].cov(aligned.iloc[:, 1]))
                var = float(aligned.iloc[:, 1].var())
                out["beta"] = round(cov / var, 2) if var > 0 else None
        except Exception as exc:
            logger.warning(
                f"Data Collect for {symbol} [beta] failed | error: {exc}"
            )

    logger.warning(
        f"Data Collect for {symbol} [fundamentals] computed: "
        f"52w={out['fifty_two_week_low']}–{out['fifty_two_week_high']}, "
        f"beta={out['beta']}, momentum={out['momentum_outlook']}, "
        f"support={out['key_support']}, resistance={out['key_resistance']}"
    )
    return out


def _gen_rr_commentary(stype: str, s: dict, cmp: float) -> str:
    """Generate a risk/reward commentary string from calculator output — no AI needed.

    Uses real numbers from the /analyse response: strike, breakeven, downside_protection_pct,
    max_profit_total, annualised_yield_pct.  Always returns a non-empty string.
    """
    strike     = s.get("strike") or 0
    breakeven  = s.get("breakeven") or 0
    dp_pct     = s.get("downside_protection_pct") or 0
    max_prof   = s.get("max_profit_total") or 0
    ann_yield  = s.get("annualised_yield_pct") or 0
    upside_pct = (strike / cmp - 1) * 100 if cmp > 0 else 0

    if stype == "ITM":
        return (
            f"Strike ₹{strike:,.0f} is below CMP — {dp_pct:.1f}% downside cushion "
            f"(breakeven ₹{breakeven:,.0f}). Upside capped; premium-focused trade. "
            f"Max return ₹{max_prof:,.0f} if stock stays above strike at expiry."
        )
    if stype == "ATM":
        return (
            f"ATM strike ₹{strike:,.0f} balances premium income ({ann_yield:.0f}% p.a.) "
            f"and upside participation. Profitable above ₹{breakeven:,.0f}; "
            f"max gain ₹{max_prof:,.0f} if stock closes at or above ₹{strike:,.0f}."
        )
    if stype == "OTM+1":
        return (
            f"OTM+1 strike ₹{strike:,.0f} requires +{upside_pct:.1f}% move for max profit. "
            f"Yield {ann_yield:.0f}% p.a.; breakeven at ₹{breakeven:,.0f}. "
            f"Lower cushion than ATM but participates in moderate upside."
        )
    # OTM+2
    return (
        f"OTM+2 strike ₹{strike:,.0f} needs +{upside_pct:.1f}% stock rise for max return "
        f"of ₹{max_prof:,.0f}. Least downside protection ({dp_pct:.1f}%); "
        f"best when mildly bullish and targeting maximum potential yield."
    )


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

    Column 1: field name with a ⓘ tooltip icon (title=desc on hover).
    Column 2: value (monospace, right-aligned).
    Descriptions are shown on hover only — matches the Bypass Claude AI ? tooltip pattern.
    """
    cell = "padding:6px 12px;border-bottom:1px solid #30363D;vertical-align:middle;"
    out  = [
        '<table style="width:100%;border-collapse:collapse;'
        'font-family:Inter,\'Segoe UI\',sans-serif;margin-bottom:4px;">'
    ]
    for name, desc, value in rows:
        _tip  = f' title="{desc}"' if desc else ""
        _icon = (
            ' <span style="color:#8B949E;font-size:11px;cursor:help;">ⓘ</span>'
            if desc else ""
        )
        out.append(
            f'<tr>'
            f'<td style="{cell} width:62%;"{_tip}>'
            f'<span style="color:#E6EDF3;font-size:13px;font-weight:500;">'
            f'{name}{_icon}</span>'
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

st.session_state.bypass_intel = st.checkbox(
    "Bypass Claude AI",
    value=st.session_state.bypass_intel,
    help=(
        "Use mock data instead of calling the Claude API. "
        "Skips the API call and shows placeholder equity data derived from CMP. "
        "Useful when ANTHROPIC_API_KEY is not set, or to avoid API costs during testing. "
        "Mock values are price-consistent but NOT real market data."
    ),
)

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

    # ── Common data fetches ───────────────────────────────────────────────────
    nse_map   = _fetch_nse_symbol_map()
    ticker    = _yf_ticker(res["symbol"], nse_map)
    nse_sym   = nse_map.get(res["symbol"].upper(), res["symbol"])
    ohlc         = _fetch_ohlc(ticker)
    nifty_ohlc   = _fetch_nifty_ohlc()
    intel        = _fetch_intel_claude(res["symbol"], nse_sym, res["cmp"], st.session_state.bypass_intel)
    tech         = _compute_technicals(ohlc, symbol=ticker, claude_estimates=intel)
    fundamentals = _compute_fundamentals(ohlc, nifty_ohlc, res["cmp"], symbol=ticker)
    equity_data  = {**intel, **fundamentals}

    sector_hv = _compute_technicals(
        _fetch_sector_ohlc(equity_data.get("sector")),
        symbol=f"sector:{equity_data.get('sector') or 'unknown'}",
    ).get("hv_20_pct")

    earn_date = intel.get("earnings_date")
    ex_div    = intel.get("ex_dividend_date")
    agm_date  = intel.get("agm_date")
    board_dt  = intel.get("board_meeting_date")

    _intel_source = intel.get("_source", "blank")
    _cmp  = res["cmp"]
    _lot  = res["lot_size"]
    _days = res.get("days_to_expiry") or 1
    _sup  = equity_data.get("key_support")
    _res  = equity_data.get("key_resistance")
    _mom  = equity_data.get("momentum_outlook")
    wk52_h = equity_data.get("fifty_two_week_high")
    wk52_l = equity_data.get("fifty_two_week_low")

    # ── 1. 30-Day Price History ───────────────────────────────────────────────
    st.markdown('<div class="section-hd">30-Day Price History</div>',
                unsafe_allow_html=True)

    ohlc_chart = ohlc.iloc[-22:] if ohlc is not None and len(ohlc) >= 22 else ohlc

    if ohlc_chart is not None and not ohlc_chart.empty:
        candle = go.Figure(go.Candlestick(
            x=ohlc_chart.index,
            open=ohlc_chart["Open"].squeeze(),
            high=ohlc_chart["High"].squeeze(),
            low=ohlc_chart["Low"].squeeze(),
            close=ohlc_chart["Close"].squeeze(),
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

    # ── 2. Position Overview (merged: position basics + equity + market intel) ──
    st.markdown('<div class="section-hd">Position Overview</div>', unsafe_allow_html=True)

    # Claude API source indicator
    if _intel_source == "blank":
        _api_key_set = bool(os.environ.get("ANTHROPIC_API_KEY"))
        if not _api_key_set:
            st.checkbox(
                "⚠️ Claude AI data unavailable — API key not configured",
                value=False, disabled=True,
                help=("Set `ANTHROPIC_API_KEY` in the Render dashboard "
                      "(Environment → Add Env Var) and redeploy, "
                      "or enable **Bypass Claude AI** above to use mock data."),
                key="err_no_key_indicator",
            )
        else:
            st.checkbox(
                "⚠️ Claude AI data unavailable — API error, retries exhausted",
                value=False, disabled=True,
                help=("The API returned an error (possibly overloaded or rate-limited). "
                      "Re-run the analysis in a moment, "
                      "or enable **Bypass Claude AI** above to use mock data."),
                key="err_api_error_indicator",
            )
    elif _intel_source == "mock":
        st.checkbox(
            "🔶 Bypass mode active — mock data only, not real market data",
            value=True, disabled=True,
            help=("Values are price-consistent placeholders derived from CMP. "
                  "Use the **Bypass Claude AI** toggle above to switch back to live data."),
            key="mock_mode_indicator",
        )

    # Earnings/ex-div event warnings (shown before the table for visibility)
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
            f"Low {_fmt_inr(lo)}"    if lo else None,
            f"Target {_fmt_inr(mn)}" if mn else None,
            f"High {_fmt_inr(hi)}"   if hi else None,
        ]))

    if wk52_h and wk52_l and wk52_h > wk52_l:
        pct_range = (res["cmp"] - wk52_l) / (wk52_h - wk52_l) * 100
        filled    = round(pct_range / 10)
        wk52_pos  = f"{'█' * filled}{'░' * (10 - filled)}  {pct_range:.0f}% of 52w range"
    else:
        wk52_pos  = "—"

    trade_type = "Holdings" if pos["already_holds"] else "Buy-Write"
    overview_rows = [
        ("Stock",            "NSE F&O symbol", res["symbol"]),
        ("Current Price",    "Live last traded price (LTP) in ₹", _fmt_inr(res["cmp"])),
        ("Trade Type",       "Buy-Write = new position; Holdings = writing against existing shares", trade_type),
        ("Expiry",           "Selected option expiry date", res["expiry_date"]),
        ("Days to Expiry",   "Calendar days remaining to selected expiry", str(res["days_to_expiry"])),
        ("Sector / Industry","Equity sector and industry classification",
         f"{equity_data.get('sector') or '—'} / {equity_data.get('industry') or '—'}"),
        ("52-Week High/Low", "52-week high and low closing prices (from 1-year OHLC)",
         f"{_fmt_inr(wk52_h)} / {_fmt_inr(wk52_l)}"),
        ("52-Week Position", "CMP within the 52-week high–low band (0%=52w low, 100%=52w high)", wk52_pos),
        ("Beta",             "Price sensitivity relative to Nifty 50 (from 1-year log-returns)",
         f"{equity_data['beta']:.2f}" if equity_data.get("beta") else "—"),
        ("HV 20-Day",        "Annualised 20-day historical volatility of the equity",
         f"{tech['hv_20_pct']:.1f}%" if tech.get("hv_20_pct") else "—"),
        ("ATR 14-Day",       "Average True Range over last 14 sessions — daily price noise",
         _fmt_inr(tech.get("atr_14"))),
        ("Sector HV 20-Day", "Annualised 20-day HV of the matching Nifty sector index",
         f"{sector_hv:.1f}%" if sector_hv else "—"),
    ]
    if intel.get("analyst_target_low") or intel.get("analyst_target_mean") or intel.get("analyst_target_high"):
        overview_rows.append(
            ("Analyst Targets", f"Consensus price targets from {n_analysts} analysts", _fmt_targets())
        )
    if intel.get("analyst_recommendation"):
        overview_rows.append(
            ("Recommendation", "Analyst consensus rating", (intel.get("analyst_recommendation") or "—").upper())
        )
    for label, tip, val in [
        ("Earnings Date",    "Next quarterly / annual results announcement", earn_date),
        ("Ex-Dividend Date", "Shares go ex-div — early assignment risk for ITM calls", ex_div),
        ("Board Meeting",    "Next scheduled board meeting", board_dt),
        ("AGM",              "Annual General Meeting date", agm_date),
    ]:
        if val:
            overview_rows.append((label, tip, val))

    st.markdown(_kv_table_html(overview_rows), unsafe_allow_html=True)
    if _intel_source == "claude_api":
        _in  = intel.get("_input_tokens", 0)
        _out = intel.get("_output_tokens", 0)
        _usd = intel.get("_cost_usd", 0.0)
        st.caption(
            f"⚡ Analyst targets & corporate dates from Claude AI (claude-haiku-4-5) · "
            f"{_in:,} in + {_out:,} out tokens · ~${_usd:.4f} · cached 24 h · "
            f"fundamentals & technicals computed from yfinance OHLC · verify before trading."
        )
    elif _intel_source == "mock":
        st.caption("🔶 Mock data (bypass mode) — not real market data.")

    # ── 3. Position Build Cost ────────────────────────────────────────────────
    st.markdown('<div class="section-hd">Position Build Cost</div>', unsafe_allow_html=True)

    lot_size       = res["lot_size"]
    approx_futures = res["cmp"] * (1 + 0.08 * res["days_to_expiry"] / 365)
    last_qty       = st.session_state.get("last_qty_held", 0)
    gross_capital  = lot_size * res["cmp"]

    if pos["already_holds"] and last_qty > 0:
        net_capital = max(0, lot_size - last_qty) * res["cmp"]
    else:
        net_capital = pos["total_cost"]

    build_rows = [
        ("F&O Lot Size",          "Shares per F&O contract lot",                          f"{lot_size:,}"),
        ("Cost Basis / Share",    "Purchase price per share used for this analysis",       _fmt_inr(pos["cost_basis_per_share"])),
        ("Purchase Cost (1 lot)", "Total capital at cost basis × lot size",                _fmt_inr(pos["total_cost"])),
        ("Gross Equity Capital",  "Lot size × CMP — capital to own one lot at market",    _fmt_inr(gross_capital)),
        ("Net Capital Required",  "Additional cash needed to complete the lot",            _fmt_inr(net_capital)),
        ("Approx. Futures Price", "CMP × (1 + 8% × DTE/365) — approximate fair futures", _fmt_inr(approx_futures)),
    ]
    if _sup:
        build_rows.append((
            "Downside to Support (₹)",
            f"Unrealised equity loss if stock falls to key support ₹{_sup:,.0f}: (CMP − support) × lot",
            _fmt_inr((_cmp - _sup) * _lot),
        ))
    if _sup or _res:
        build_rows.append((
            "Support / Resistance",
            "Nearest technical levels computed from 20-day rolling low/high of close prices",
            f"{_fmt_inr(_sup)} / {_fmt_inr(_res)}",
        ))
    if _mom:
        _mom_icon = {"bullish": "▲", "neutral": "▶", "bearish": "▼"}.get(_mom, "")
        build_rows.append((
            "Momentum (1 month)",
            "Short-term momentum: CMP vs 20-day SMA (>+1% bullish, <-1% bearish, ±1% neutral)",
            f"{_mom_icon} {_mom.capitalize()}",
        ))
    st.markdown(_kv_table_html(build_rows), unsafe_allow_html=True)
    if pos["already_holds"] and last_qty > 0:
        st.caption(
            f"You hold {last_qty:,} of {lot_size:,} shares — "
            f"need {max(0, lot_size - last_qty):,} more at CMP to complete the lot."
        )

    # ── 4. Strike & Options Analysis (transposed table with Greeks) ───────────
    st.markdown('<div class="section-hd">Strike &amp; Options Analysis</div>',
                unsafe_allow_html=True)

    # Enrich all strikes with live IV (Breeze quote → BS fallback)
    enriched_strikes: list[dict] = []
    for s in res["strikes"]:
        sc = dict(s)
        iv_e = s.get("iv")
        ltp  = s.get("premium")
        if iv_e is None and ltp and res.get("days_to_expiry"):
            q = _fetch_option_quote(res["symbol"], res["expiry_date"], s["strike"])
            iv_e = q.get("iv")
            if q.get("open_interest") is not None:
                sc["open_interest"] = q["open_interest"]
            if q.get("volume") is not None:
                sc["volume"] = q["volume"]
            if iv_e is None:
                iv_e = _bs_iv(res["cmp"], s["strike"], res["days_to_expiry"], ltp)
        sc["_iv_enriched"] = iv_e
        enriched_strikes.append(sc)

    # Compute Black-Scholes Greeks for every enriched strike
    greeks_data: dict[str, dict | None] = {}
    for s in enriched_strikes:
        iv_val = s.get("_iv_enriched")
        if iv_val is not None and res.get("days_to_expiry"):
            greeks_data[s["strike_type"]] = _bs_greeks(
                S=res["cmp"], K=s["strike"],
                T_days=res["days_to_expiry"], sigma_pct=iv_val,
                ltp_per_share=s["premium"],
            )
        else:
            greeks_data[s["strike_type"]] = None

    st.markdown(
        _strike_options_table_html(enriched_strikes, res["cmp"], greeks_data, res["days_to_expiry"]),
        unsafe_allow_html=True,
    )

    # ── 5. Risk / Reward Summary ──────────────────────────────────────────────
    st.markdown('<div class="section-hd">Risk / Reward Summary</div>', unsafe_allow_html=True)

    # 5a: Common position card with Python-generated commentary
    st.markdown(_common_rr_card_html(pos, res, equity_data, tech), unsafe_allow_html=True)

    # 5b: Per-strike cards (unchanged logic, uses enriched_strikes for OI/Vol)

    # ── Per-strike subsections: header + note + kv rows ───────────────────────
    _STRIKE_META = {
        "ITM": {
            "title":  "ITM — In The Money",
            "note":   (
                "The strike is below the current market price. "
                "You collect a larger premium and get the most downside protection, "
                "but your upside is capped immediately. "
                "Best suited when you expect the stock to stay flat or drift slightly lower."
            ),
            "bg":     "rgba(106, 143, 191, 0.10)",
            "border": "#6A8FBF",
        },
        "ATM": {
            "title":  "ATM — At The Money",
            "note":   (
                "The strike is at or nearest to the current market price. "
                "Offers a balanced mix of premium income and upside participation. "
                "Maximum profit is realised if the stock closes at or just above the strike at expiry."
            ),
            "bg":     "rgba(88, 166, 255, 0.10)",
            "border": "#58A6FF",
        },
        "OTM+1": {
            "title":  "OTM+1 — Out of The Money (1 step)",
            "note":   (
                "The strike is one increment above the current market price. "
                "Lower premium than ATM but lets you participate in modest upside. "
                "The call is profitable if the stock rises to the strike by expiry."
            ),
            "bg":     "rgba(32, 164, 160, 0.10)",
            "border": "#20A4A0",
        },
        "OTM+2": {
            "title":  "OTM+2 — Out of The Money (2 steps)",
            "note":   (
                "The strike is two increments above the current market price. "
                "Lowest premium and least downside cushion, but highest upside participation. "
                "Best when you are mildly bullish and want maximum potential gain from the covered call."
            ),
            "bg":     "rgba(57, 208, 200, 0.10)",
            "border": "#39D0C8",
        },
    }

    # Volatility data for cushion warnings
    _hv    = tech.get("hv_20_pct") or intel.get("hv_20_pct")
    _atr   = tech.get("atr_14")    or intel.get("atr_14")
    _gross_capital = _lot * _cmp
    _msig  = (_hv / _math.sqrt(12)) if _hv else None   # expected 1-month ±1σ move %

    def _warn_div(text: str, level: str) -> str:
        _clr, _bg = {
            "danger":  ("#F85149", "rgba(248,81,73,0.12)"),
            "caution": ("#D29922", "rgba(210,153,34,0.12)"),
            "ok":      ("#3FB950", "rgba(63,185,80,0.10)"),
            "info":    ("#8B949E", "rgba(139,148,158,0.10)"),
        }.get(level, ("#8B949E", "rgba(139,148,158,0.10)"))
        return (
            f'<div style="margin:4px 12px 4px 12px;padding:5px 10px;'
            f'background:{_bg};border-left:2px solid {_clr};border-radius:3px;'
            f'color:{_clr};font-size:12px;line-height:1.5;">{text}</div>'
        )

    for s in enriched_strikes:
        stype = s["strike_type"]
        meta  = _STRIKE_META.get(
            stype, {"title": stype, "note": "", "bg": "rgba(255,255,255,0.04)", "border": "#444"}
        )

        # ── All metric calculations in Python ─────────────────────────────────
        _net_prem   = s.get("net_premium_total") or 0
        _max_prof   = s.get("max_profit_total")  or 0
        _dp_pct     = s.get("downside_protection_pct") or 0   # (CMP-breakeven)/CMP %
        _breakeven  = s.get("breakeven")
        _oi         = s.get("open_interest")
        _vol_traded = s.get("volume")
        _note       = _gen_rr_commentary(stype, s, _cmp)  # Python template — always populated

        # Build-Up Cost: cash actually deployed after premium offsets equity purchase
        _build_cost = _gross_capital - _net_prem

        # Premium Yield on Build Cost = return if option expires worthless
        _yield_on_build     = (_net_prem / _build_cost * 100)     if _build_cost > 0 else 0
        _ann_yield_on_build = (_yield_on_build * 365 / _days)     if _days > 0       else 0

        # Total Return If Assigned = max P&L when stock is called away at strike
        _total_ret_pct = (_max_prof / _build_cost * 100) if _build_cost > 0 else 0

        # Loss to support
        _loss_sup = ((_cmp - _sup) * _lot - _net_prem) if _sup and _sup < _cmp else None

        # ── Volatility cushion assessment ─────────────────────────────────────
        _vol_warn = _vol_lvl = None
        if _msig is not None:
            _ratio = _dp_pct / _msig if _msig > 0 else 0
            if _ratio < 0.5:
                _vol_lvl  = "danger"
                _vol_warn = (
                    f"⚠ Very thin cushion: {_dp_pct:.1f}% protection is less than half the "
                    f"expected ±{_msig:.1f}% monthly move (HV {_hv:.0f}% p.a.). "
                    "High loss risk even on moderate pullbacks."
                )
            elif _ratio < 1.0:
                _vol_lvl  = "caution"
                _vol_warn = (
                    f"⚠ Thin cushion: {_dp_pct:.1f}% protection is below the "
                    f"expected ±{_msig:.1f}% monthly 1σ move (HV {_hv:.0f}% p.a.)."
                )
            else:
                _vol_lvl  = "ok"
                _vol_warn = (
                    f"✓ Cushion {_dp_pct:.1f}% covers the expected ±{_msig:.1f}% "
                    f"monthly move (HV {_hv:.0f}% p.a.)."
                )
        elif _atr and _lot > 0:
            _prem_share = _net_prem / _lot
            _atr_cover  = _prem_share / _atr if _atr > 0 else 0
            _vol_lvl    = "info"
            _vol_warn   = (
                f"ⓘ Premium covers ≈{_atr_cover:.1f}× the 14-day ATR "
                f"(₹{_atr:.0f} typical daily range). No annualised HV available."
            )

        # ── Liquidity assessment ───────────────────────────────────────────────
        _liq_warn = _liq_lvl = None
        if _oi is not None or _vol_traded is not None:
            _oi_v  = _oi          if _oi          is not None else 9_999
            _vol_v = _vol_traded  if _vol_traded  is not None else 9_999
            _parts = (
                ([f"OI {_oi:,}"]        if _oi          is not None else []) +
                ([f"Vol {_vol_traded:,}"] if _vol_traded is not None else [])
            )
            if _oi_v < 500 or _vol_v < 100:
                _liq_lvl  = "danger"
                _liq_warn = (
                    f"⚠ Very illiquid ({', '.join(_parts)}) — "
                    "wide bid-ask spreads likely. Use limit orders only."
                )
            elif _oi_v < 2_000 or _vol_v < 300:
                _liq_lvl  = "caution"
                _liq_warn = (
                    f"⚠ Low liquidity ({', '.join(_parts)}) — "
                    "verify live bid-ask before trading."
                )

        # ── kv rows ───────────────────────────────────────────────────────────
        kv_rows = [
            ("Net premium received",
             "Total net option premium received after all brokerage, STT, and other charges",
             _fmt_inr(_net_prem)),
            ("Build-Up Cost",
             "Cash actually deployed: lot × CMP minus net premium received. "
             "This is the true capital at risk for a fresh covered call.",
             _fmt_inr(_build_cost)),
            ("Yield on build cost",
             "Net premium ÷ build-up cost — your return if the option expires worthless. "
             "Higher than standard premium yield because the denominator is net capital, not gross.",
             f"{_yield_on_build:.2f}%  ({_ann_yield_on_build:.1f}% p.a.)"),
            ("Total return if assigned",
             "Best-case P&L if the stock is called away at the strike: "
             "(strike − CMP) × lot + net premium. Expressed as % of build-up cost.",
             f"{_fmt_inr(_max_prof)}  ({_total_ret_pct:.1f}% on build cost)"),
            ("Downside cushion",
             "How far the stock can fall from CMP before the position loses money: "
             "(CMP − breakeven) ÷ CMP. Equals the premium as a % of spot.",
             f"{_dp_pct:.2f}%  (breakeven {_fmt_inr(_breakeven)})"),
            ("Loss to support",
             (f"Net loss if stock falls to technical support ₹{_sup:,.0f}: "
              "equity loss partially offset by premium already received")
             if _sup else "Key support level unavailable",
             _fmt_inr(_loss_sup) if _loss_sup is not None else "—"),
        ]
        kv_rows.append((
            "R/R commentary",
            "Risk/reward summary computed from real strike, premium and breakeven figures",
            _note,
        ))

        # ── Assemble card HTML ─────────────────────────────────────────────────
        cell = "padding:6px 12px;border-bottom:1px solid #30363D;vertical-align:middle;"
        rows_html = []
        for name, desc, value in kv_rows:
            _tip  = f' title="{desc}"' if desc else ""
            _icon = (' <span style="color:#8B949E;font-size:11px;cursor:help;">ⓘ</span>'
                     if desc else "")
            rows_html.append(
                f'<tr>'
                f'<td style="{cell} width:52%;"{_tip}>'
                f'<span style="color:#E6EDF3;font-size:13px;font-weight:500;">{name}{_icon}</span>'
                f'</td>'
                f'<td style="{cell} width:48%;text-align:right;color:#C9D1D9;font-size:13px;'
                f'font-family:\'Courier New\',monospace;">{value}</td>'
                f'</tr>'
            )

        warn_html = ""
        if _vol_warn:
            warn_html += _warn_div(_vol_warn, _vol_lvl)
        if _liq_warn:
            warn_html += _warn_div(_liq_warn, _liq_lvl)

        card_html = (
            f'<div style="background:{meta["bg"]};border-left:3px solid {meta["border"]};'
            f'border-radius:6px;margin-bottom:12px;overflow:hidden;">'
            f'<div style="padding:10px 14px 6px 14px;">'
            f'<span style="color:{meta["border"]};font-size:14px;font-weight:700;">{meta["title"]}</span>'
            f'<br><span style="color:#8B949E;font-size:12px;line-height:1.5;">{meta["note"]}</span>'
            f'</div>'
            f'<table style="width:100%;border-collapse:collapse;'
            f'font-family:Inter,\'Segoe UI\',sans-serif;">'
            f'{"".join(rows_html)}'
            f'</table>'
            f'{warn_html}'
            f'</div>'
        )
        st.markdown(card_html, unsafe_allow_html=True)

    st.caption(
        "R/R commentary computed from live option data — support/resistance from 20-day OHLC. "
        "Analyst targets and corporate dates from Claude AI · verify before trading."
    )

    # ── 6. P&L Payoff Chart (shown last) ─────────────────────────────────────
    st.markdown('<div class="section-hd">P&amp;L Payoff at Expiry</div>',
                unsafe_allow_html=True)

    payoff_opts = ["All strikes"] + [s["strike_type"] for s in enriched_strikes]
    payoff_sel  = st.radio("View payoff for", payoff_opts, horizontal=True, key="payoff_strike_sel")

    line_fig = go.Figure()
    for s in enriched_strikes:
        if payoff_sel != "All strikes" and s["strike_type"] != payoff_sel:
            continue
        xs = [p["price"] for p in s["payoff"]]
        ys = [p["pl"]    for p in s["payoff"]]
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
