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
from .data_fetcher import get_cmp
from .models import HealthResponse, QuoteResponse
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
# Root redirect → docs
# ---------------------------------------------------------------------------

@app.get("/", include_in_schema=False)
def root():
    """Redirect root to API docs."""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/docs")
