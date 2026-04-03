"""
data_fetcher.py — Market data retrieval from ICICI Breeze API.

Phase 1 functions:
    get_cmp(symbol)                        — Fetch last traded price for an NSE equity

Phase 2 functions:
    get_lot_size(symbol)                   — Lookup F&O lot size from built-in table
    get_available_expiries(symbol)         — List available monthly expiry dates via Breeze
    get_option_chain(symbol, expiry_date)  — Fetch call option chain for a given expiry
"""

import logging
from calendar import monthrange
from datetime import date, datetime, timedelta
from typing import Optional

from breeze_connect import BreezeConnect

from .breeze_client import get_session

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Phase 2 — NSE F&O lot size table
#
# Source: NSE circular (revised periodically by SEBI).
# Last updated: March 2025.  If a symbol is missing, raise ValueError so
# the caller can surface a clear error rather than silently using a wrong lot.
# ---------------------------------------------------------------------------

_LOT_SIZES: dict[str, int] = {
    "RELIND":    250,
    "TCS":         150,
    "INFTEC":        300,
    "HDFBAN":    550,
    "ICICIB":   700,
    "STABAN":       1500,
    "BHAAIR":  950,
    "ITC":        3200,
    "KOTBAN":   400,
    "LT":          150,
    "HINUNI":  300,
    "INTAVI":  150,
    "AXIBAN":   1200,
    "BAJFIN":  125,
    "WIPRO":      1500,
    "HCLTEC":     700,
    "MAHM&M":         700,
    "TITCO":       375,
    "ULTCEM":  100,
    "NESIND":    50,
    "SUNPHA":   700,
    "POWGRID":  4700,
    "ONGC":       3850,
    "NTPC":       3750,
    "ADAENT":    625,
    "ADAPOR":      475,
    "MARSUZ":      100,
    "TATSTE":  5500,
    "TATMOT": 1425,
    "JSWSTE":   1350,
    "COALIN":  4200,
    "DIVLAB":    150,
    "DRREDD":     125,
    "CIPLA":       650,
    "APOHOS":  125,
    "ASIPAI":  200,
    "GRAIND":      475,
    "TECMAH":       600,
    "BAJFIN":  500,
    "HINDAL":   2150,
    "INDBAN":  500,
    "SBILIF":     750,
    "HDFCLIF":   1100,
    "BHAPET":       1800,
    "HERMOT":  300,
    "EICRMOT":   175,
    "VEDL":       3100,
    "NIFTY":        25,
    "BANKNIFTY":    15,
    "FINNIFTY":     40,
}


# ---------------------------------------------------------------------------
# F&O shortcode → NSE equity ticker mapping (used for price-history lookups)
# ---------------------------------------------------------------------------

_NSE_SYMBOLS: dict[str, str] = {
    "ADAENT":  "ADANIENT",
    "ADAPOR":  "ADANIPORTS",
    "APOHOS":  "APOLLOHOSP",
    "ASIPAI":  "ASIANPAINT",
    "AXIBAN":  "AXISBANK",
    "BAJAUT":  "BAJAJ-AUTO",
    "BAJFIN":  "BAJAJ-AUTO",
    "BHAAIR":  "BHARTIARTL",
    "BHAPET":  "BPCL",
    "CIPLA":   "CIPLA",
    "COALIN":  "COALINDIA",
    "DIVLAB":  "DIVISLAB",
    "DRREDD":  "DRREDDY",
    "EICRMOT": "EICHERMOT",
    "GRAIND":  "GRASIM",
    "HCLTEC":  "HCLTECH",
    "HDFBAN":  "HDFCBANK",
    "HDFCLIF": "HDFCLIFE",
    "HERMOT":  "HEROMOTOCO",
    "HINDAL":  "HINDALCO",
    "HINUNI":  "HINDUNILVR",
    "ICICIB":  "ICICIBANK",
    "INDBAN":  "INDUSINDBK",
    "INFTEC":  "INFY",
    "INTAVI":  "INDIGO",
    "ITC":     "ITC",
    "JSWSTE":  "JSWSTEEL",
    "KOTBAN":  "KOTAKBANK",
    "LT":      "LT",
    "MAHM&M":  "M&M",
    "MARSUZ":  "MARUTI",
    "MAXH":    "MAXHEALTH",
    "NESIND":  "NESTLEIND",
    "NTPC":    "NTPC",
    "ONGC":    "ONGC",
    "POWGRID": "POWERGRID",
    "RELIND":  "RELIANCE",
    "SBILIF":  "SBILIFE",
    "STABAN":  "SBIN",
    "SUNPHA":  "SUNPHARMA",
    "TATMOT":  "TMPV",
    "TATSTE":  "TATASTEEL",
    "TCS":     "TCS",
    "TECMAH":  "LTIM",
    "TITCO":   "TITAN",
    "ULTCEM":  "ULTRACEMCO",
    "VEDL":    "VEDL",
    "WIPRO":   "WIPRO",
}


def get_all_nse_symbols() -> dict[str, str]:
    """Return the F&O shortcode → NSE equity ticker mapping."""
    return dict(_NSE_SYMBOLS)


def get_all_lot_sizes() -> dict[str, int]:
    """Return a snapshot of all known lot sizes (symbol → lot size).

    Returns a copy so callers cannot mutate the internal table directly.
    """
    return dict(_LOT_SIZES)


def upsert_lot_size(symbol: str, lot_size: int) -> None:
    """Add or update a symbol's lot size in the in-memory table.

    Changes are in-memory only and are lost when the server restarts.
    For persistence, update _LOT_SIZES in this source file and redeploy.

    Args:
        symbol:   NSE F&O symbol (will be uppercased).
        lot_size: Positive integer lot size.

    Raises:
        ValueError: If lot_size is not a positive integer.
    """
    symbol = symbol.strip().upper()
    if lot_size <= 0:
        raise ValueError(f"lot_size must be a positive integer, got {lot_size}.")
    _LOT_SIZES[symbol] = lot_size
    logger.info(f"Lot size upserted: {symbol} = {lot_size}")


def delete_lot_size(symbol: str) -> bool:
    """Remove a symbol from the in-memory lot size table.

    Returns:
        True if the symbol existed and was removed, False if it was not found.
    """
    symbol = symbol.strip().upper()
    if symbol in _LOT_SIZES:
        del _LOT_SIZES[symbol]
        logger.info(f"Lot size deleted: {symbol}")
        return True
    return False


def upsert_nse_symbol(fo_code: str, nse_ticker: str) -> None:
    """Add or update an F&O shortcode → NSE ticker mapping (in-memory).

    Args:
        fo_code:    F&O trading shortcode (will be uppercased).
        nse_ticker: NSE equity ticker symbol.
    """
    fo_code = fo_code.strip().upper()
    nse_ticker = nse_ticker.strip().upper()
    if not fo_code or not nse_ticker:
        raise ValueError("fo_code and nse_ticker must not be empty.")
    _NSE_SYMBOLS[fo_code] = nse_ticker
    logger.info(f"NSE symbol upserted: {fo_code} → {nse_ticker}")


def delete_nse_symbol(fo_code: str) -> bool:
    """Remove an F&O shortcode from the NSE symbol mapping (in-memory).

    Returns:
        True if found and deleted, False if not found.
    """
    fo_code = fo_code.strip().upper()
    if fo_code in _NSE_SYMBOLS:
        del _NSE_SYMBOLS[fo_code]
        logger.info(f"NSE symbol deleted: {fo_code}")
        return True
    return False


# ---------------------------------------------------------------------------
# Phase 1 — Live equity quote
# ---------------------------------------------------------------------------

def get_cmp(symbol: str, breeze: Optional[BreezeConnect] = None) -> float:
    """Fetch the Last Traded Price (LTP) for an NSE equity symbol.

    Uses Breeze's get_quotes API with exchange_code='NSE' and
    product_type for cash equity (right='others', strike_price='0').

    Args:
        symbol: NSE trading symbol, e.g. "M&M", "RELIANCE", "INFY".
                Pass the symbol exactly as used on NSE (not the Breeze stock code).

    Returns:
        Last traded price as a float (in INR).

    Raises:
        ValueError: If the Breeze API returns no data or an error for this symbol.
        RuntimeError: If the Breeze session itself is unavailable.

    Example:
        >>> price = get_cmp("RELIANCE")
        >>> print(f"Reliance LTP: ₹{price:.2f}")
    """
    if breeze is None:
        breeze = get_session()

    logger.info(f"Fetching CMP for symbol: {symbol}")

    try:
        response = breeze.get_quotes(
            stock_code=symbol,
            exchange_code="NSE",
            expiry_date="",       # empty for equity (not F&O)
            right="others",       # 'others' = equity/cash, not Call/Put
            strike_price="0",     # 0 for equity
        )
    except Exception as exc:
        logger.error(f"Breeze get_quotes call failed for {symbol}: {exc}")
        raise RuntimeError(
            f"Failed to call Breeze get_quotes for '{symbol}': {exc}"
        ) from exc

    # Breeze returns: {"Success": [...], "Status": 200, "Error": None}
    status = response.get("Status")
    error = response.get("Error")
    success_data = response.get("Success")

    if status != 200:
        logger.error(f"Breeze returned non-200 status {status} for {symbol}: {error}")
        raise ValueError(
            f"Breeze API error for symbol '{symbol}' "
            f"(status={status}): {error or 'Unknown error'}"
        )

    if not success_data or len(success_data) == 0:
        logger.warning(f"Breeze returned empty data for symbol: {symbol}")
        raise ValueError(
            f"No quote data returned for symbol '{symbol}'. "
            "Check that the symbol is a valid NSE F&O ticker."
        )

    quote = success_data[0]

    # Breeze may return LTP in different field names depending on product type.
    # We try 'last_traded_price' first, then 'ltp' as fallback.
    ltp_raw = quote.get("last_traded_price") or quote.get("ltp")

    if ltp_raw is None:
        logger.error(f"LTP field missing in Breeze response for {symbol}: {quote}")
        raise ValueError(
            f"Could not extract LTP from Breeze response for '{symbol}'. "
            f"Available fields: {list(quote.keys())}"
        )

    try:
        ltp = float(ltp_raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"LTP value '{ltp_raw}' for '{symbol}' cannot be converted to float."
        ) from exc

    if ltp <= 0:
        raise ValueError(
            f"LTP for '{symbol}' is {ltp}, which is invalid. "
            "Market may be closed or the symbol may be delisted."
        )

    logger.info(f"CMP for {symbol}: ₹{ltp:.2f}")
    return ltp


# ---------------------------------------------------------------------------
# Phase 2 — Lot size, expiries, option chain
# ---------------------------------------------------------------------------

def get_lot_size(symbol: str) -> int:
    """Return the F&O lot size for a symbol from the built-in NSE lot size table.

    Args:
        symbol: NSE F&O symbol, e.g. "RELIANCE", "M&M", "NIFTY".

    Returns:
        Lot size as an integer (number of shares per lot).

    Raises:
        ValueError: If the symbol is not in the lot size table.
    """
    key = symbol.upper()
    size = _LOT_SIZES.get(key)
    if size is None:
        raise ValueError(
            f"Lot size not found for '{symbol}'. "
            f"Supported symbols: {sorted(_LOT_SIZES.keys())}"
        )
    logger.info(f"Lot size for {symbol}: {size}")
    return size


# Quarter-end dates that trigger the Monday exception rule
_QUARTER_ENDS: frozenset[tuple[int, int]] = frozenset({(3, 31), (6, 30), (9, 30), (12, 31)})


def _monthly_expiry(year: int, month: int) -> date:
    """Return the monthly F&O expiry date for the given month.

    Rule: last Tuesday of the month.
    Exception: if that Tuesday falls on a quarter-end date
    (Mar 31, Jun 30, Sep 30, Dec 31), the expiry moves to the
    preceding Monday.
    """
    _, days_in_month = monthrange(year, month)
    last_day = date(year, month, days_in_month)
    # weekday(): Mon=0, Tue=1, Wed=2, Thu=3, Fri=4, Sat=5, Sun=6
    days_back = (last_day.weekday() - 1) % 7  # roll back to Tuesday
    last_tue = last_day - timedelta(days=days_back)

    if (last_tue.month, last_tue.day) in _QUARTER_ENDS:
        return last_tue - timedelta(days=1)  # move to Monday

    return last_tue


def get_available_expiries(symbol: str) -> list[str]:
    """Return the next 3 monthly F&O expiry dates for a symbol.

    Expiry rule: last Tuesday of the month, except when that Tuesday is a
    quarter-end date (Mar 31, Jun 30, Sep 30, Dec 31) — in which case
    the expiry is the preceding Monday.

    Args:
        symbol: NSE F&O symbol (used only for logging; computation is generic).

    Returns:
        List of expiry dates in YYYY-MM-DD format, sorted ascending.
        Always returns exactly 3 dates covering the next 3 expiry months.
        Example: ["2024-03-26", "2024-04-30", "2024-05-28"]
    """
    logger.info(f"Computing expiry dates for {symbol}")
    today = date.today()
    results: list[str] = []
    year, month = today.year, today.month

    while len(results) < 3:
        expiry = _monthly_expiry(year, month)
        if expiry >= today:
            results.append(expiry.strftime("%Y-%m-%d"))
        month += 1
        if month > 12:
            month = 1
            year += 1

    logger.info(f"Expiries for {symbol}: {results}")
    return results


def _to_breeze_iso(date_str: str) -> str:
    """Convert 'YYYY-MM-DD' to the ISO format Breeze option chain API expects.

    Breeze get_option_chain_quotes requires: '2024-03-28T06:00:00.000Z'

    Example: '2024-03-28' → '2024-03-28T06:00:00.000Z'
    """
    return f"{date_str}T06:00:00.000Z"


def get_option_chain(symbol: str, expiry_date: str, right: str = "call", breeze: Optional[BreezeConnect] = None) -> list[dict]:
    """Fetch the option chain (calls or puts) for a symbol and expiry date.

    Calls breeze.get_option_chain_quotes to retrieve all available strikes
    for the specified right (call or put).

    Args:
        symbol:      NSE F&O symbol, e.g. "RELIANCE".
        expiry_date: Expiry date in YYYY-MM-DD format, e.g. "2024-03-28".
        right:       "call" (CE) or "put" (PE). Defaults to "call".

    Returns:
        List of dicts, each representing one option contract:
        [
            {
                "strike_price": 2900.0,
                "option_type": "CE" or "PE",
                "ltp": 45.50,
                "iv": 18.3,          # may be None if not returned by Breeze
                "open_interest": 125000,
                "volume": 34000,
            },
            ...
        ]
        Sorted by strike_price ascending.

    Raises:
        ValueError: If no option data is returned for this symbol/expiry.
        RuntimeError: If the Breeze API call itself fails.
    """
    if breeze is None:
        breeze = get_session()
    breeze_expiry = _to_breeze_iso(expiry_date)

    logger.info(f"Fetching option chain for {symbol} expiry={breeze_expiry}")

    try:
        response = breeze.get_option_chain_quotes(
            stock_code=symbol,
            exchange_code="NFO",
            product_type="options",
            expiry_date=breeze_expiry,
            right=right.lower(),
            strike_price="0",     # 0 = fetch all strikes
        )
    except Exception as exc:
        logger.error(f"Breeze get_option_chain_quotes failed for {symbol}: {exc}")
        raise RuntimeError(
            f"Failed to fetch option chain for '{symbol}' expiry {expiry_date}: {exc}"
        ) from exc

    status = response.get("Status")
    error = response.get("Error")
    success_data = response.get("Success")

    if status != 200:
        raise ValueError(
            f"Breeze API error for option chain '{symbol}' expiry {expiry_date} "
            f"(status={status}): {error or 'Unknown error'}"
        )

    if not success_data:
        raise ValueError(
            f"No option chain data for '{symbol}' expiry {expiry_date}. "
            "Confirm the expiry date is valid (use /expiries/{symbol} to list dates)."
        )

    contracts: list[dict] = []
    for raw in success_data:
        # Breeze field names vary slightly; try both known variants
        strike_raw = raw.get("strike_price") or raw.get("strikePrice")
        ltp_raw    = raw.get("ltp") or raw.get("last_traded_price")
        oi_raw     = raw.get("open_interest") or raw.get("openInterest")
        iv_raw     = raw.get("implied_volatility") or raw.get("iv")
        vol_raw    = raw.get("volume") or raw.get("total_quantity_traded")

        try:
            strike = float(strike_raw) if strike_raw is not None else None
            ltp    = float(ltp_raw)    if ltp_raw    is not None else None
        except (TypeError, ValueError):
            logger.warning(f"Skipping malformed option row for {symbol}: {raw}")
            continue

        if strike is None or ltp is None:
            logger.warning(f"Missing strike/ltp in option row for {symbol}: {raw}")
            continue

        option_type = "CE" if right.lower() == "call" else "PE"
        contracts.append({
            "strike_price":   strike,
            "option_type":    option_type,
            "ltp":            ltp,
            "iv":             float(iv_raw)  if iv_raw  is not None else None,
            "open_interest":  int(oi_raw)    if oi_raw  is not None else None,
            "volume":         int(vol_raw)   if vol_raw is not None else None,
        })

    if not contracts:
        raise ValueError(
            f"Option chain returned no parseable contracts for '{symbol}' "
            f"expiry {expiry_date}."
        )

    contracts.sort(key=lambda c: c["strike_price"])
    logger.info(f"Option chain for {symbol} {expiry_date}: {len(contracts)} strikes")
    return contracts


def get_option_quote(symbol: str, expiry_date: str, strike: float, breeze: Optional[BreezeConnect] = None) -> dict:
    """Fetch a detailed option quote for a *specific* strike from the Breeze API.

    Tries strike_price in multiple formats (integer string, then float string)
    because Breeze behaviour varies by broker configuration.  If Breeze returns
    empty data for all formats the function returns a partial result with
    ltp=0 and iv/open_interest/volume as None — it does NOT raise so callers
    can degrade gracefully rather than returning HTTP 404.

    Args:
        symbol:      NSE F&O symbol, e.g. "RELIANCE".
        expiry_date: Expiry date in YYYY-MM-DD format.
        strike:      Strike price as a float, e.g. 2900.0.

    Returns:
        Dict with keys: strike_price (float), ltp (float), iv, open_interest,
        volume (all Optional).  iv/open_interest/volume are None when Breeze
        returns no detail.

    Raises:
        RuntimeError: Breeze API call itself failed (network / session error).
    """
    if breeze is None:
        breeze = get_session()
    breeze_expiry = _to_breeze_iso(expiry_date)

    # Breeze may expect the strike as an integer ("2260") or a float ("2260.0").
    # Try both; stop as soon as we get a non-empty Success response.
    strike_formats = [str(int(strike)), f"{float(strike):.1f}"]

    data       = None
    last_error = None

    for strike_fmt in strike_formats:
        logger.info(
            f"Fetching option quote for {symbol} expiry={expiry_date} "
            f"strike_fmt={strike_fmt!r}"
        )
        try:
            response = breeze.get_option_chain_quotes(
                stock_code=symbol,
                exchange_code="NFO",
                product_type="options",
                expiry_date=breeze_expiry,
                right="call",
                strike_price=strike_fmt,
            )
        except Exception as exc:
            last_error = exc
            logger.error(
                f"Breeze get_option_chain_quotes failed for {symbol} "
                f"strike_fmt={strike_fmt!r}: {exc}"
            )
            continue  # try next format before giving up

        status = response.get("Status")
        error  = response.get("Error")
        rows   = response.get("Success")

        logger.info(
            f"Option quote response {symbol} strike_fmt={strike_fmt!r}: "
            f"status={status}, error={error!r}, rows={len(rows) if rows else 0}"
        )

        if status != 200:
            logger.warning(
                f"Breeze non-200 for {symbol} strike_fmt={strike_fmt!r}: "
                f"status={status} error={error!r}"
            )
            continue

        if rows:
            data = rows
            break
        else:
            logger.warning(
                f"Breeze returned empty Success for {symbol} "
                f"strike_fmt={strike_fmt!r} — trying next format"
            )

    # If every format yielded empty / an error, return partial result so the
    # frontend can fall back to option-chain data instead of getting a 404.
    if not data:
        if last_error and not any(True for _ in []):
            # All attempts threw exceptions — escalate
            raise RuntimeError(
                f"Failed to fetch option quote for '{symbol}' expiry {expiry_date} "
                f"strike {strike}: {last_error}"
            )
        logger.warning(
            f"No option quote data for {symbol} expiry={expiry_date} "
            f"strike={strike} after formats={strike_formats}. "
            f"Returning empty quote — frontend will fall back to chain data."
        )
        return {
            "strike_price":  strike,
            "ltp":           0.0,
            "iv":            None,
            "open_interest": None,
            "volume":        None,
        }

    raw     = data[0]
    ltp_raw = raw.get("ltp") or raw.get("last_traded_price")
    iv_raw  = raw.get("implied_volatility") or raw.get("iv")
    oi_raw  = raw.get("open_interest") or raw.get("openInterest")
    vol_raw = raw.get("volume") or raw.get("total_quantity_traded")

    # Diagnostic log when any key field is missing — reveals actual Breeze field names
    if iv_raw is None or oi_raw is None or vol_raw is None:
        logger.warning(
            f"get_option_quote {symbol} strike={strike} — some fields blank after parsing. "
            f"Raw keys: {list(raw.keys())} | "
            f"implied_volatility={raw.get('implied_volatility')!r} "
            f"iv={raw.get('iv')!r} "
            f"open_interest={raw.get('open_interest')!r} "
            f"openInterest={raw.get('openInterest')!r} "
            f"volume={raw.get('volume')!r} "
            f"total_quantity_traded={raw.get('total_quantity_traded')!r} "
            f"ltp={raw.get('ltp')!r}"
        )

    try:
        ltp = float(ltp_raw) if ltp_raw is not None else 0.0
    except (TypeError, ValueError):
        ltp = 0.0

    result = {
        "strike_price":  strike,
        "ltp":           ltp,
        "iv":            float(iv_raw) if iv_raw  is not None else None,
        "open_interest": int(oi_raw)   if oi_raw  is not None else None,
        "volume":        int(vol_raw)  if vol_raw is not None else None,
    }
    logger.info(
        f"Option quote {symbol} {expiry_date} ₹{strike}: "
        f"ltp={ltp}, IV={result['iv']}, OI={result['open_interest']}, "
        f"Vol={result['volume']}"
    )
    return result


# ---------------------------------------------------------------------------
# Holdings — equity and mutual fund portfolio
# ---------------------------------------------------------------------------

def _safe_float(v) -> float:
    """Coerce a Breeze field value to float, returning 0.0 on failure."""
    if v in (None, "", "NA", "N/A", "-"):
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def get_holdings(breeze: Optional[BreezeConnect] = None) -> dict:
    """Fetch portfolio holdings from Breeze.

    Makes exactly TWO Breeze API calls:
      1. get_demat_holdings()          — stock list + ISIN + quantity.
      2. get_portfolio_holdings(...)   — avg_cost / cmp / P&L enrichment.
         Requires a date range (year-to-date) — Breeze returns empty without it.
         Also yields mutual fund rows (product_type contains MF/MUTUAL/FUND).

    Equity rows come from demat (authoritative for long-term holdings),
    enriched with price/cost from portfolio holdings where available.
    MF rows come from portfolio holdings only (not held in DEMAT).

    Raises RuntimeError with "429" prefix on Breeze rate-limit.
    Returns {"equity": [...], "mutual_funds": [...]}
    """
    if breeze is None:
        breeze = get_session()
    logger.info("Fetching holdings from Breeze")

    def _check_rate_limit(resp: dict, label: str) -> None:
        status = resp.get("Status")
        error  = str(resp.get("Error") or "")
        if status == 429 or "429" in error or "too many" in error.lower():
            raise RuntimeError(
                f"429: Breeze rate limit reached ({label}). "
                "Please wait a minute before refreshing."
            )

    # ── Step 1: demat holdings — authoritative equity list ────────────────
    # Returns: stock_code, stock_ISIN, quantity, demat_total_bulk_quantity
    demat_by_code: dict[str, dict] = {}   # code -> {isin, qty}
    try:
        d_resp = breeze.get_demat_holdings()
        _check_rate_limit(d_resp, "get_demat_holdings")
        for d in (d_resp.get("Success") or []):
            code = (d.get("stock_code") or "").strip().upper()
            if code:
                demat_by_code[code] = {
                    "isin": (d.get("stock_ISIN") or "").strip(),
                    "qty":  _safe_float(
                        d.get("quantity") or d.get("demat_total_bulk_quantity")
                    ),
                }
        logger.info(f"Demat: {len(demat_by_code)} symbols")
    except RuntimeError:
        raise
    except Exception as exc:
        logger.error(f"get_demat_holdings failed: {exc}")
        raise RuntimeError(f"Failed to fetch demat holdings: {exc}") from exc

    # ── Step 2: portfolio holdings — price / cost / P&L + MF rows ─────────
    # Breeze requires a date range; empty strings return no data.
    # Use year-to-date to capture all CNC equity purchases and MF positions.
    portfolio_by_code: dict[str, dict] = {}   # equity code -> row
    mf_rows: list[dict] = []
    today   = datetime.now()
    from_dt = f"{today.year}-01-01T06:00:00.000Z"
    to_dt   = today.strftime("%Y-%m-%dT23:59:59.000Z")
    try:
        p_resp = breeze.get_portfolio_holdings(
            exchange_code="NSE",
            from_date=from_dt,
            to_date=to_dt,
        )
        _check_rate_limit(p_resp, "get_portfolio_holdings(NSE)")
        for h in (p_resp.get("Success") or []):
            code = (h.get("stock_code") or "").strip().upper()
            if code:
                portfolio_by_code[code] = h
        logger.info(f"Portfolio NSE: {len(portfolio_by_code)} equity rows")
    except RuntimeError:
        raise
    except Exception as exc:
        logger.warning(f"get_portfolio_holdings(NSE) failed (prices unavailable): {exc}")

    # Step 2b: MF holdings — try MFO then BSE (ICICI MFs may sit on either)
    _mf_found = False
    for _mf_exc in ("MFO", "BSE"):
        try:
            mf_resp = breeze.get_portfolio_holdings(
                exchange_code=_mf_exc,
                from_date=from_dt,
                to_date=to_dt,
            )
            _check_rate_limit(mf_resp, f"get_portfolio_holdings({_mf_exc})")
            status = mf_resp.get("Status")
            rows   = mf_resp.get("Success") or []
            if status != 200 or not rows:
                logger.info(f"Portfolio {_mf_exc}: no rows (status={status}), trying next")
                continue
            for h in rows:
                product = (h.get("product_type") or "").upper()
                exc_c   = (h.get("exchange_code") or _mf_exc).upper()
                # On BSE, filter to MF product types only (BSE also has equity)
                if _mf_exc == "BSE":
                    if not any(kw in product for kw in ("MF", "MUTUAL", "FUND")):
                        continue
                mf_rows.append(h)
            logger.info(f"Portfolio {_mf_exc}: {len(mf_rows)} MF rows")
            _mf_found = True
            break
        except RuntimeError:
            raise
        except Exception as exc:
            logger.warning(f"get_portfolio_holdings({_mf_exc}) failed: {exc}")

    # ── Step 3: build equity rows (demat is the master list) ─────────────
    equity: list[dict] = []
    for code, d in demat_by_code.items():
        h        = portfolio_by_code.get(code, {})
        qty      = d["qty"] or _safe_float(h.get("quantity"))
        avg_cost = _safe_float(h.get("average_price"))
        cmp_val  = _safe_float(h.get("current_market_price"))
        cur_val  = _safe_float(h.get("open_position_value"))
        if cur_val == 0.0 and qty and cmp_val:
            cur_val = qty * cmp_val
        pnl = _safe_float(
            h.get("unrealized_profit") or h.get("booked_profit_loss")
        )
        if pnl == 0.0 and avg_cost and qty:
            pnl = cur_val - avg_cost * qty
        pnl_pct = _safe_float(h.get("change_percentage"))
        if pnl_pct == 0.0 and avg_cost and qty:
            cost = avg_cost * qty
            pnl_pct = (pnl / cost * 100) if cost else 0.0
        equity.append({
            "name":      code,
            "symbol":    code,
            "isin":      d["isin"],
            "quantity":  qty,
            "avg_cost":  avg_cost,
            "cmp":       cmp_val,
            "cur_value": cur_val,
            "pnl":       pnl,
            "pnl_pct":   pnl_pct,
        })

    # ── Step 4: build MF rows ─────────────────────────────────────────────
    mf: list[dict] = []
    for h in mf_rows:
        code     = (h.get("stock_code") or "").strip().upper()
        qty      = _safe_float(h.get("quantity"))
        avg_cost = _safe_float(h.get("average_price"))
        cmp_val  = _safe_float(h.get("current_market_price"))
        cur_val  = _safe_float(h.get("open_position_value"))
        if cur_val == 0.0 and qty and cmp_val:
            cur_val = qty * cmp_val
        pnl = _safe_float(
            h.get("unrealized_profit") or h.get("booked_profit_loss")
        )
        if pnl == 0.0 and avg_cost and qty:
            pnl = cur_val - avg_cost * qty
        pnl_pct = _safe_float(h.get("change_percentage"))
        if pnl_pct == 0.0 and avg_cost and qty:
            cost = avg_cost * qty
            pnl_pct = (pnl / cost * 100) if cost else 0.0
        mf.append({
            "name":      code,
            "symbol":    code,
            "isin":      (h.get("isin_code") or "").strip(),
            "quantity":  qty,
            "avg_cost":  avg_cost,
            "cmp":       cmp_val,
            "cur_value": cur_val,
            "pnl":       pnl,
            "pnl_pct":   pnl_pct,
        })

    logger.info(f"Holdings final: {len(equity)} equity, {len(mf)} MF")
    return {"equity": equity, "mutual_funds": mf}
