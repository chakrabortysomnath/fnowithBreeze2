"""
data_fetcher.py — Market data retrieval from ICICI Breeze API.

Phase 1 functions:
    get_cmp(symbol)         — Fetch last traded price for an NSE equity

Phase 2 functions (stubs, implemented in Phase 2):
    get_lot_size(symbol)    — Lookup F&O lot size
    get_option_chain(...)   — Fetch call option chain for a given expiry
    get_available_expiries(symbol) — List available monthly expiry dates
"""

import logging
from datetime import datetime
from typing import Optional

from .breeze_client import get_session

logger = logging.getLogger(__name__)


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
# Phase 2 stubs — implemented fully in data_fetcher.py during Phase 2
# ---------------------------------------------------------------------------

def get_lot_size(symbol: str) -> int:  # pragma: no cover
    """Return the F&O lot size for a symbol. (Implemented in Phase 2.)"""
    raise NotImplementedError("get_lot_size is implemented in Phase 2")


def get_option_chain(symbol: str, expiry_date: str) -> list[dict]:  # pragma: no cover
    """Return the call option chain for symbol + expiry. (Implemented in Phase 2.)"""
    raise NotImplementedError("get_option_chain is implemented in Phase 2")


def get_available_expiries(symbol: str) -> list[str]:  # pragma: no cover
    """Return available monthly expiry dates for a symbol. (Implemented in Phase 2.)"""
    raise NotImplementedError("get_available_expiries is implemented in Phase 2")
