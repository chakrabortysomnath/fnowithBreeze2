"""
models.py — Pydantic request/response models for the FastAPI application.

Phase 1 models:
    HealthResponse  — /health endpoint
    QuoteResponse   — /quote/{symbol} endpoint

Phase 2+ models (stubs, expanded in later phases):
    LotSizeResponse, OptionChainResponse, AnalyseRequest, AnalyseResponse
"""

from pydantic import BaseModel, Field
from typing import Optional, Any


# ---------------------------------------------------------------------------
# Phase 1 — Health & Quote
# ---------------------------------------------------------------------------

class HealthResponse(BaseModel):
    """Response model for GET /health."""

    status: str = Field(
        description="Always 'ok' if the server is running.",
        examples=["ok"],
    )
    breeze_connected: bool = Field(
        description="True if a Breeze session is active and authenticated.",
    )
    message: Optional[str] = Field(
        default=None,
        description="Optional diagnostic message (e.g. reason for failed connection).",
    )


class QuoteResponse(BaseModel):
    """Response model for GET /quote/{symbol}."""

    symbol: str = Field(
        description="NSE trading symbol as provided in the request.",
        examples=["M&M", "RELIANCE"],
    )
    cmp: float = Field(
        description="Current Market Price (Last Traded Price) in INR.",
        examples=[2104.50],
    )
    timestamp: str = Field(
        description="UTC timestamp of when the quote was fetched (ISO 8601).",
        examples=["2026-03-11T07:30:00Z"],
    )


# ---------------------------------------------------------------------------
# Phase 2 stubs — expanded in Phase 2
# ---------------------------------------------------------------------------

class LotSizeResponse(BaseModel):
    """Response model for GET /lot-size/{symbol}."""

    symbol: str
    lot_size: int


class ExpiriesResponse(BaseModel):
    """Response model for GET /expiries/{symbol}."""

    symbol: str
    expiries: list[str] = Field(
        description="List of available expiry dates in YYYY-MM-DD format.",
    )


class OptionContract(BaseModel):
    """A single call option contract from the option chain."""

    strike_price: float
    option_type: str = Field(default="CE", description="Always 'CE' (call).")
    ltp: float = Field(description="Last traded premium in INR.")
    iv: Optional[float] = Field(default=None, description="Implied volatility %.")
    open_interest: Optional[int] = Field(default=None)
    volume: Optional[int] = Field(default=None)


class OptionChainResponse(BaseModel):
    """Response model for GET /option-chain/{symbol}."""

    symbol: str
    expiry_date: str
    options: list[OptionContract]


# ---------------------------------------------------------------------------
# Phase 3 stubs — expanded in Phase 3
# ---------------------------------------------------------------------------

class AnalyseRequest(BaseModel):
    """Request body for POST /analyse."""

    symbol: str
    expiry_date: str = Field(description="Option expiry in YYYY-MM-DD format.")
    already_holds: bool = Field(
        description="True if the user already holds this stock."
    )
    quantity_held: int = Field(default=0, ge=0)
    avg_purchase_price: float = Field(default=0.0, ge=0.0)
    brokerage: float = Field(default=40.0, gt=0)
    stt_rate: float = Field(default=0.001, gt=0)
    gst_rate: float = Field(default=0.18, gt=0)


class AnalyseResponse(BaseModel):
    """Response model for POST /analyse (Phase 3)."""

    # Full structure defined in Phase 3
    data: Any = Field(description="Full analysis result dict.")
