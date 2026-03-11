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
    "RELIANCE":    250,
    "TCS":         150,
    "INFY":        300,
    "HDFCBANK":    550,
    "ICICIBANK":   700,
    "SBIN":       1500,
    "BHARTIARTL":  950,
    "ITC":        3200,
    "KOTAKBANK":   400,
    "LT":          150,
    "HINDUNILVR":  300,
    "AXISBANK":   1200,
    "BAJFINANCE":  125,
    "WIPRO":      1500,
    "HCLTECH":     700,
    "M&M":         700,
    "TITAN":       375,
    "ULTRACEMCO":  100,
    "NESTLEIND":    50,
    "SUNPHARMA":   700,
    "POWERGRID":  4700,
    "ONGC":       3850,
    "NTPC":       3750,
    "ADANIENT":    625,
    "MARUTI":      100,
    "TATASTEEL":  5500,
    "TATAMOTORS": 1425,
    "JSWSTEEL":   1350,
    "COALINDIA":  4200,
    "DIVISLAB":    150,
    "DRREDDY":     125,
    "CIPLA":       650,
    "APOLLOHOSP":  125,
    "ASIANPAINT":  200,
    "GRASIM":      475,
    "TECHM":       600,
    "BAJAJFINSV":  500,
    "HINDALCO":   2150,
    "INDUSINDBK":  500,
    "SBILIFE":     750,
    "HDFCLIFE":   1100,
    "BPCL":       1800,
    "HEROMOTOCO":  300,
    "EICHERMOT":   175,
    "VEDL":       3100,
    "NIFTY":        25,
    "BANKNIFTY":    15,
    "FINNIFTY":     40,
}


# ---------------------------------------------------------------------------
# Phase 1 — Live equity quote
# ---------------------------------------------------------------------------

def get_cmp(symbol: str) -> float:
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


def get_option_chain(symbol: str, expiry_date: str) -> list[dict]:
    """Fetch the call option chain for a symbol and expiry date.

    Calls breeze.get_option_chain_quotes with right='call' to retrieve all
    available call strikes for covered call analysis.

    Args:
        symbol:      NSE F&O symbol, e.g. "RELIANCE".
        expiry_date: Expiry date in YYYY-MM-DD format, e.g. "2024-03-28".

    Returns:
        List of dicts, each representing one call option contract:
        [
            {
                "strike_price": 2900.0,
                "option_type": "CE",
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
    breeze = get_session()
    breeze_expiry = _to_breeze_iso(expiry_date)

    logger.info(f"Fetching option chain for {symbol} expiry={breeze_expiry}")

    try:
        response = breeze.get_option_chain_quotes(
            stock_code=symbol,
            exchange_code="NFO",
            product_type="options",
            expiry_date=breeze_expiry,
            right="call",
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

        contracts.append({
            "strike_price":   strike,
            "option_type":    "CE",
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
