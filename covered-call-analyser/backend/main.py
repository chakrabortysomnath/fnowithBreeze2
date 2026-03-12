"""
main.py — FastAPI application entry point.

Phase 1 endpoints:
    GET  /health          — Breeze connectivity check
    GET  /quote/{symbol}  — Live CMP from Breeze API

Phase 2 endpoints (added in Phase 2):
    GET  /lot-size/{symbol}
    GET  /expiries/{symbol}
    GET  /option-chain/{symbol}

Phase 3 endpoints (added in Phase 3):
    POST /analyse

Phase 5 endpoints (added in Phase 5):
    POST /refresh-session

Run locally:
    cd covered-call-analyser
    uvicorn backend.main:app --reload --port 8000
"""

import logging
import sys
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from .breeze_client import get_session, is_connected
from .calculator import analyse_covered_call
from .data_fetcher import get_cmp, get_lot_size, get_available_expiries, get_option_chain
from .models import (
    HealthResponse, QuoteResponse,
    LotSizeResponse, ExpiriesResponse, OptionChainResponse, OptionContract,
    AnalyseRequest, AnalyseResponse, PositionDetails, StrikeAnalysis,
    ChargesBreakdown, PayoffPoint,
)
from .config import settings

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Covered Call Analyser API",
    description=(
        "Backend for the Covered Call Strategy Analyser. "
        "Fetches live market data from ICICI Breeze API and runs covered call analytics."
    ),
    version="0.1.0",
    docs_url="/docs",       # Swagger UI at /docs
    redoc_url="/redoc",     # ReDoc at /redoc
)

# Allow the Streamlit frontend (any origin in dev; tighten in Phase 5)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Phase 1 Endpoints
# ---------------------------------------------------------------------------

@app.get(
    "/health",
    response_model=HealthResponse,
    summary="Health check",
    description="Returns server status and whether the Breeze API session is active.",
    tags=["Health"],
)
def health_check() -> HealthResponse:
    """Check server health and Breeze API connectivity.

    This endpoint is safe to call frequently — it does NOT make an external
    API call to Breeze; it only checks whether a session object exists.

    Returns:
        HealthResponse with status='ok' and breeze_connected=True/False.
    """
    connected = is_connected()
    message = None if connected else (
        "Breeze session is not available. Check credentials and session token."
    )
    logger.info(f"/health called — breeze_connected={connected}")
    return HealthResponse(
        status="ok",
        breeze_connected=connected,
        message=message,
    )


@app.get(
    "/quote/{symbol}",
    response_model=QuoteResponse,
    summary="Get live CMP for a stock",
    description=(
        "Fetches the Last Traded Price (LTP) for the given NSE symbol "
        "using the Breeze API. Use URL encoding for symbols with special "
        "characters (e.g. M%26M for M&M)."
    ),
    tags=["Market Data"],
)
def get_quote(symbol: str) -> QuoteResponse:
    """Return live Current Market Price for an NSE equity symbol.

    Args:
        symbol: NSE trading symbol. URL-encode special chars:
                M&M → M%26M, BAJAJ-AUTO → BAJAJ-AUTO (no encoding needed)

    Returns:
        QuoteResponse with symbol, cmp (INR), and UTC timestamp.

    Raises:
        404: Symbol not found or no data returned by Breeze.
        503: Breeze session unavailable.
    """
    # Decode common URL encodings that FastAPI path params don't auto-decode
    decoded_symbol = symbol.replace("%26", "&").upper()

    logger.info(f"GET /quote/{decoded_symbol}")

    try:
        cmp = get_cmp(decoded_symbol)
    except ValueError as exc:
        logger.warning(f"Quote not found for {decoded_symbol}: {exc}")
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        logger.error(f"Breeze session error for {decoded_symbol}: {exc}")
        raise HTTPException(
            status_code=503,
            detail=f"Breeze API unavailable: {exc}",
        )
    except Exception as exc:
        logger.exception(f"Unexpected error fetching quote for {decoded_symbol}")
        raise HTTPException(
            status_code=500,
            detail=f"Unexpected server error: {exc}",
        )

    timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return QuoteResponse(symbol=decoded_symbol, cmp=cmp, timestamp=timestamp)


# ---------------------------------------------------------------------------
# Phase 2 Endpoints
# ---------------------------------------------------------------------------

@app.get(
    "/lot-size/{symbol}",
    response_model=LotSizeResponse,
    summary="Get F&O lot size for a symbol",
    description=(
        "Returns the NSE F&O lot size for the given symbol from the built-in "
        "lot size table. Lot sizes are set by SEBI and change periodically."
    ),
    tags=["Market Data"],
)
def lot_size(symbol: str) -> LotSizeResponse:
    """Return F&O lot size for an NSE symbol.

    Args:
        symbol: NSE F&O symbol, e.g. RELIANCE, M%26M, NIFTY.

    Returns:
        LotSizeResponse with symbol and lot_size.

    Raises:
        404: Symbol not found in the lot size table.
    """
    decoded = symbol.replace("%26", "&").upper()
    logger.info(f"GET /lot-size/{decoded}")
    try:
        size = get_lot_size(decoded)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return LotSizeResponse(symbol=decoded, lot_size=size)


@app.get(
    "/expiries/{symbol}",
    response_model=ExpiriesResponse,
    summary="List available F&O expiry dates for a symbol",
    description=(
        "Fetches available monthly expiry dates from the Breeze API for the "
        "given NSE F&O symbol. Dates are returned in YYYY-MM-DD format, "
        "sorted ascending."
    ),
    tags=["Market Data"],
)
def expiries(symbol: str) -> ExpiriesResponse:
    """Return available option expiry dates for a symbol.

    Args:
        symbol: NSE F&O symbol, e.g. RELIANCE.

    Returns:
        ExpiriesResponse with symbol and list of expiry dates (YYYY-MM-DD).

    Raises:
        404: No expiry dates found for the symbol.
        503: Breeze session unavailable.
    """
    decoded = symbol.replace("%26", "&").upper()
    logger.info(f"GET /expiries/{decoded}")
    try:
        dates = get_available_expiries(decoded)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        logger.exception(f"Unexpected error fetching expiries for {decoded}")
        raise HTTPException(status_code=500, detail=f"Unexpected error: {exc}")
    return ExpiriesResponse(symbol=decoded, expiries=dates)


@app.get(
    "/option-chain/{symbol}",
    response_model=OptionChainResponse,
    summary="Get call option chain for a symbol and expiry",
    description=(
        "Fetches all available call (CE) option strikes for the given NSE F&O "
        "symbol and expiry date. Use /expiries/{symbol} to get valid expiry dates. "
        "expiry query parameter must be in YYYY-MM-DD format."
    ),
    tags=["Market Data"],
)
def option_chain(
    symbol: str,
    expiry: str = Query(
        ...,
        description="Expiry date in YYYY-MM-DD format. Use /expiries/{symbol} to list dates.",
        examples=["2024-03-28"],
    ),
) -> OptionChainResponse:
    """Return the call option chain for a symbol and expiry date.

    Args:
        symbol: NSE F&O symbol, e.g. RELIANCE.
        expiry: Expiry date in YYYY-MM-DD format.

    Returns:
        OptionChainResponse with symbol, expiry_date, and list of OptionContract.

    Raises:
        400: expiry date format is invalid.
        404: No option data found.
        503: Breeze session unavailable.
    """
    decoded = symbol.replace("%26", "&").upper()
    logger.info(f"GET /option-chain/{decoded}?expiry={expiry}")

    # Validate expiry format
    try:
        from datetime import datetime
        datetime.strptime(expiry, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid expiry date format '{expiry}'. Use YYYY-MM-DD.",
        )

    try:
        contracts_raw = get_option_chain(decoded, expiry)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        logger.exception(f"Unexpected error fetching option chain for {decoded}")
        raise HTTPException(status_code=500, detail=f"Unexpected error: {exc}")

    contracts = [OptionContract(**c) for c in contracts_raw]
    return OptionChainResponse(symbol=decoded, expiry_date=expiry, options=contracts)


# ---------------------------------------------------------------------------
# Phase 3 Endpoints
# ---------------------------------------------------------------------------

@app.post(
    "/analyse",
    response_model=AnalyseResponse,
    summary="Run covered call analysis for a symbol and expiry",
    description=(
        "Fetches live CMP, lot size, and the full call option chain for the "
        "given symbol and expiry, then runs the covered call calculator across "
        "ITM / ATM / OTM+1 / OTM+2 strikes. Returns per-strike metrics including "
        "net premium, breakeven, max profit, yield, and a P&L payoff curve."
    ),
    tags=["Analysis"],
)
def analyse(req: AnalyseRequest) -> AnalyseResponse:
    """Execute a covered call analysis.

    Orchestrates: get_cmp → get_lot_size → get_option_chain → analyse_covered_call.

    Raises:
        404: Symbol not found or no option data for this expiry.
        400: Invalid expiry date format.
        503: Breeze session unavailable.
    """
    symbol = req.symbol.strip().upper()
    logger.info(f"POST /analyse symbol={symbol} expiry={req.expiry_date}")

    # Validate expiry format
    try:
        datetime.strptime(req.expiry_date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid expiry_date '{req.expiry_date}'. Use YYYY-MM-DD.",
        )

    # --- Fetch market data ---
    try:
        cmp = get_cmp(symbol)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    try:
        lot_size = get_lot_size(symbol)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    try:
        chain = get_option_chain(symbol, req.expiry_date)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    # --- Run calculator ---
    from .calculator import _days_to_expiry
    dte = _days_to_expiry(req.expiry_date)

    try:
        result = analyse_covered_call(
            symbol=symbol,
            cmp=cmp,
            lot_size=lot_size,
            expiry_date=req.expiry_date,
            days_to_expiry=dte,
            option_chain=chain,
            already_holds=req.already_holds,
            quantity_held=req.quantity_held,
            avg_purchase_price=req.avg_purchase_price,
            brokerage=req.brokerage,
            stt_rate=req.stt_rate,
            gst_rate=req.gst_rate,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        logger.exception(f"Calculator error for {symbol}")
        raise HTTPException(status_code=500, detail=f"Calculation error: {exc}")

    # --- Build typed response ---
    timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    pos = result["position"]
    position = PositionDetails(
        lots=pos["lots"],
        shares=pos["shares"],
        cost_basis_per_share=pos["cost_basis_per_share"],
        total_cost=pos["total_cost"],
        already_holds=pos["already_holds"],
    )

    strikes = []
    for s in result["strikes"]:
        c = s["charges"]
        strikes.append(StrikeAnalysis(
            strike=s["strike"],
            strike_type=s["strike_type"],
            premium=s["premium"],
            net_premium_per_share=s["net_premium_per_share"],
            net_premium_total=s["net_premium_total"],
            gross_premium_total=s["gross_premium_total"],
            charges=ChargesBreakdown(**c),
            breakeven=s["breakeven"],
            breakeven_pct_below_cmp=s["breakeven_pct_below_cmp"],
            max_profit_per_share=s["max_profit_per_share"],
            max_profit_total=s["max_profit_total"],
            premium_yield_pct=s["premium_yield_pct"],
            annualised_yield_pct=s["annualised_yield_pct"],
            downside_protection_pct=s["downside_protection_pct"],
            iv=s.get("iv"),
            open_interest=s.get("open_interest"),
            payoff=[PayoffPoint(**p) for p in s["payoff"]],
        ))

    return AnalyseResponse(
        symbol=result["symbol"],
        cmp=result["cmp"],
        expiry_date=result["expiry_date"],
        days_to_expiry=result["days_to_expiry"],
        lot_size=result["lot_size"],
        position=position,
        strikes=strikes,
        timestamp=timestamp,
    )


# ---------------------------------------------------------------------------
# Root redirect → docs
# ---------------------------------------------------------------------------

@app.get("/", include_in_schema=False)
def root():
    """Redirect root to API docs."""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/docs")
