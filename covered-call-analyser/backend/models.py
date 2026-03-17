"""
models.py — Pydantic request/response models for the FastAPI application.

Phase 1 models:
    HealthResponse  — /health endpoint
    QuoteResponse   — /quote/{symbol} endpoint

Phase 2 models:
    LotSizeResponse, ExpiriesResponse, OptionContract, OptionChainResponse

Phase 3 models:
    AnalyseRequest, ChargesBreakdown, PayoffPoint, StrikeAnalysis,
    PositionDetails, AnalyseResponse
"""

from pydantic import BaseModel, Field
from typing import Optional


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
# Phase 2 — Lot size, expiries, option chain
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
# Phase 3 — Covered call analysis
# ---------------------------------------------------------------------------

class LotSizeTableResponse(BaseModel):
    """Response model for GET /lot-sizes — full table."""

    lot_sizes: dict[str, int] = Field(
        description="Mapping of NSE F&O symbol → lot size."
    )
    nse_symbols: dict[str, str] = Field(
        default={},
        description="Mapping of F&O shortcode → NSE equity ticker for price-history lookups.",
    )
    count: int = Field(description="Number of symbols in the table.")


class UpsertLotSizeRequest(BaseModel):
    """Request body for POST /lot-sizes — add or update one entry."""

    symbol: str = Field(description="NSE F&O symbol, e.g. RELIANCE.")
    lot_size: int = Field(gt=0, description="F&O lot size (must be positive).")


class AnalyseRequest(BaseModel):
    """Request body for POST /analyse."""

    symbol: str = Field(description="NSE F&O symbol, e.g. RELIANCE.")
    expiry_date: str = Field(description="Option expiry in YYYY-MM-DD format.")
    already_holds: bool = Field(
        description=(
            "True if the user already holds this stock. "
            "False for a buy-write (buy stock + write call simultaneously)."
        )
    )
    quantity_held: int = Field(
        default=0, ge=0,
        description="Shares already held. Used only when already_holds=True.",
    )
    avg_purchase_price: float = Field(
        default=0.0, ge=0.0,
        description=(
            "Average cost per share of existing holding (INR). "
            "Used as cost basis when already_holds=True. "
            "Defaults to live CMP when 0 or already_holds=False."
        ),
    )
    brokerage: float = Field(
        default=40.0, gt=0,
        description="Fixed brokerage per option lot written (INR).",
    )
    stt_rate: float = Field(
        default=0.001, gt=0,
        description="STT rate on option premium as a decimal (0.001 = 0.1%).",
    )
    gst_rate: float = Field(
        default=0.18, gt=0,
        description="GST rate on brokerage as a decimal (0.18 = 18%).",
    )


class ChargesBreakdown(BaseModel):
    """Breakdown of charges for one covered call leg."""

    stt: float = Field(description="Securities Transaction Tax (INR).")
    brokerage: float = Field(description="Brokerage (INR).")
    gst: float = Field(description="GST on brokerage (INR).")
    total: float = Field(description="Total charges (INR).")


class PayoffPoint(BaseModel):
    """One point on the P&L-at-expiry payoff curve."""

    price: float = Field(description="Stock price at expiry (INR).")
    pl: float = Field(description="P&L at that stock price (INR).")


class StrikeAnalysis(BaseModel):
    """Full covered call analysis for a single strike price."""

    strike: float
    strike_type: str = Field(
        description="Strike classification: ITM, ATM, OTM+1, or OTM+2."
    )
    premium: float = Field(description="Option LTP (gross premium per share, INR).")
    net_premium_per_share: float = Field(
        description="Premium per share after charges (INR)."
    )
    net_premium_total: float = Field(
        description="Total net premium for all shares written (INR)."
    )
    gross_premium_total: float = Field(
        description="Gross premium before charges (INR)."
    )
    charges: ChargesBreakdown
    breakeven: float = Field(
        description="Stock price below which this position loses money (INR)."
    )
    breakeven_pct_below_cmp: float = Field(
        description="Breakeven as % below CMP — represents downside protection."
    )
    max_profit_per_share: float = Field(
        description="Maximum profit per share if stock is called away at strike (INR)."
    )
    max_profit_total: float = Field(
        description="Maximum total profit if called away (INR)."
    )
    premium_yield_pct: float = Field(
        description="Net premium as % of capital deployed."
    )
    annualised_yield_pct: Optional[float] = Field(
        default=None,
        description="Premium yield annualised to 365 days (%). None if DTE = 0.",
    )
    downside_protection_pct: float = Field(
        description="Net premium as % of cost basis — how far stock can fall before a loss."
    )
    iv: Optional[float] = Field(default=None, description="Implied volatility (%).")
    open_interest: Optional[int] = Field(default=None, description="Open interest (contracts).")
    volume: Optional[int] = Field(default=None, description="Volume traded today (contracts).")
    payoff: list[PayoffPoint] = Field(
        description="P&L at expiry across a range of stock prices."
    )


class PositionDetails(BaseModel):
    """Position sizing details."""

    lots: int = Field(description="Number of option lots written.")
    shares: int = Field(description="Total shares in position (lots × lot_size).")
    cost_basis_per_share: float = Field(description="Cost basis per share (INR).")
    total_cost: float = Field(description="Total capital deployed (INR).")
    already_holds: bool


class AnalyseResponse(BaseModel):
    """Response model for POST /analyse."""

    symbol: str
    cmp: float
    expiry_date: str
    days_to_expiry: int
    lot_size: int
    position: PositionDetails
    strikes: list[StrikeAnalysis]
    timestamp: str


# ---------------------------------------------------------------------------
# Phase 5 — Session refresh
# ---------------------------------------------------------------------------

class RefreshSessionRequest(BaseModel):
    """Request body for POST /refresh-session."""

    session_token: str = Field(
        description=(
            "Fresh daily session token obtained from the ICICI Direct login flow. "
            "Generate at: https://api.icicidirect.com/apiuser/login?api_key=YOUR_KEY"
        )
    )


class RefreshSessionResponse(BaseModel):
    """Response model for POST /refresh-session."""

    status: str = Field(
        description="'ok' if the session was refreshed successfully.",
        examples=["ok"],
    )
    message: str = Field(
        description="Human-readable confirmation message.",
        examples=["Breeze session refreshed successfully."],
    )
    timestamp: str = Field(
        description="UTC timestamp of the refresh (ISO 8601).",
    )


# ---------------------------------------------------------------------------
# Phase 6 — Watchlist
# ---------------------------------------------------------------------------

class WatchlistItem(BaseModel):
    """One symbol+expiry entry in a watchlist analysis request."""

    symbol: str = Field(description="NSE F&O symbol, e.g. RELIANCE.")
    expiry_date: str = Field(description="Option expiry in YYYY-MM-DD format.")
    already_holds: bool = Field(default=False)
    quantity_held: int = Field(default=0, ge=0)
    avg_purchase_price: float = Field(default=0.0, ge=0.0)
    brokerage: float = Field(default=40.0, gt=0)
    stt_rate: float = Field(default=0.001, gt=0)
    gst_rate: float = Field(default=0.18, gt=0)


class WatchlistRequest(BaseModel):
    """Request body for POST /analyse-watchlist."""

    items: list[WatchlistItem] = Field(
        min_length=1, max_length=20,
        description="1–20 watchlist items to analyse.",
    )


class WatchlistResultItem(BaseModel):
    """Analysis outcome for one symbol in a watchlist run."""

    symbol: str
    status: str = Field(description="'ok' if analysis succeeded, 'error' otherwise.")
    result: Optional[AnalyseResponse] = Field(
        default=None,
        description="Full analysis result (present only when status='ok').",
    )
    error: Optional[str] = Field(
        default=None,
        description="Error message (present only when status='error').",
    )


class WatchlistResponse(BaseModel):
    """Response model for POST /analyse-watchlist."""

    results: list[WatchlistResultItem]
    total: int = Field(description="Total number of items submitted.")
    succeeded: int = Field(description="Number of items that analysed successfully.")
    failed: int = Field(description="Number of items that failed.")
    timestamp: str
