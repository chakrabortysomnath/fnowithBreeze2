"""
calculator.py — Covered call strategy maths (pure functions, no API calls).

All functions here are side-effect-free and fully unit-testable without
any Breeze connection.

Phase 3 public API:
    analyse_covered_call(...)  — full analysis dict for a symbol/expiry
"""

from datetime import date, datetime


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _days_to_expiry(expiry_date: str) -> int:
    """Return calendar days from today to expiry_date (YYYY-MM-DD).

    Returns 0 if expiry is today or in the past.
    """
    expiry = datetime.strptime(expiry_date, "%Y-%m-%d").date()
    delta = (expiry - date.today()).days
    return max(delta, 0)


def _find_atm_index(strikes: list[float], cmp: float) -> int:
    """Return the index of the strike closest to CMP (ATM)."""
    return min(range(len(strikes)), key=lambda i: abs(strikes[i] - cmp))


def _compute_charges(
    premium_per_share: float,
    shares: int,
    lots: int,
    brokerage: float,
    stt_rate: float,
    gst_rate: float,
) -> dict:
    """Return a breakdown of option-writing charges.

    Charges applied when writing (selling) a covered call:
      STT       — Securities Transaction Tax on premium received (stt_rate × premium)
      Brokerage — Fixed amount per lot written
      GST       — GST on brokerage only (not on STT)
    """
    gross = premium_per_share * shares
    stt = round(stt_rate * gross, 2)
    brok = round(brokerage * lots, 2)
    gst = round(gst_rate * brok, 2)
    total = round(stt + brok + gst, 2)
    return {"stt": stt, "brokerage": brok, "gst": gst, "total": total}


def _payoff_points(
    cost_basis: float,
    strike: float,
    net_premium_per_share: float,
    shares: int,
    n: int = 7,
) -> list[dict]:
    """Generate P&L at expiry for n evenly-spaced stock price points.

    P&L formula:
      - If stock_price ≤ strike: P&L = (stock_price − cost_basis + net_prem) × shares
      - If stock_price > strike: P&L = (strike − cost_basis + net_prem) × shares  [capped]

    Price range: cost_basis × 0.85  …  strike × 1.10
    """
    lo = round(cost_basis * 0.85, 2)
    hi = round(strike * 1.10, 2)
    step = (hi - lo) / (n - 1)
    points = []
    for i in range(n):
        price = round(lo + i * step, 2)
        if price <= strike:
            pl = round((price - cost_basis + net_premium_per_share) * shares, 2)
        else:
            pl = round((strike - cost_basis + net_premium_per_share) * shares, 2)
        points.append({"price": price, "pl": pl})
    return points


def _analyse_strike(
    strike: float,
    strike_type: str,
    ltp: float,
    iv: float | None,
    open_interest: int | None,
    volume: int | None,
    cost_basis: float,
    shares: int,
    lots: int,
    total_cost: float,
    days_to_expiry: int,
    brokerage: float,
    stt_rate: float,
    gst_rate: float,
) -> dict:
    """Compute all metrics for a single covered call strike."""
    charges = _compute_charges(ltp, shares, lots, brokerage, stt_rate, gst_rate)
    gross_premium_total = round(ltp * shares, 2)
    net_premium_total = round(gross_premium_total - charges["total"], 2)
    net_premium_per_share = round(net_premium_total / shares, 4)

    breakeven = round(cost_basis - net_premium_per_share, 2)
    breakeven_pct = round((cost_basis - breakeven) / cost_basis * 100, 2)

    max_profit_per_share = round((strike - cost_basis) + net_premium_per_share, 2)
    max_profit_total = round(max_profit_per_share * shares, 2)

    # Yield = net premium as % of capital deployed
    premium_yield_pct = round(net_premium_total / total_cost * 100, 4)
    ann_yield_pct = (
        round(premium_yield_pct * 365 / days_to_expiry, 2)
        if days_to_expiry > 0
        else None
    )

    downside_protection_pct = round(net_premium_per_share / cost_basis * 100, 2)

    payoff = _payoff_points(cost_basis, strike, net_premium_per_share, shares)

    return {
        "strike": strike,
        "strike_type": strike_type,
        "premium": ltp,
        "net_premium_per_share": net_premium_per_share,
        "net_premium_total": net_premium_total,
        "gross_premium_total": gross_premium_total,
        "charges": charges,
        "breakeven": breakeven,
        "breakeven_pct_below_cmp": breakeven_pct,
        "max_profit_per_share": max_profit_per_share,
        "max_profit_total": max_profit_total,
        "premium_yield_pct": premium_yield_pct,
        "annualised_yield_pct": ann_yield_pct,
        "downside_protection_pct": downside_protection_pct,
        "iv": iv,
        "open_interest": open_interest,
        "volume": volume,
        "payoff": payoff,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyse_covered_call(
    symbol: str,
    cmp: float,
    lot_size: int,
    expiry_date: str,
    days_to_expiry: int,
    option_chain: list[dict],
    already_holds: bool,
    quantity_held: int = 0,
    avg_purchase_price: float = 0.0,
    brokerage: float = 40.0,
    stt_rate: float = 0.001,
    gst_rate: float = 0.18,
) -> dict:
    """Analyse a covered call position and return scenario metrics per strike.

    Selects up to 4 strikes from the option chain for analysis:
      ITM  — the strike one step below ATM (if available)
      ATM  — the strike closest to CMP
      OTM1 — one strike above ATM
      OTM2 — two strikes above ATM (if available)

    Args:
        symbol:             NSE ticker.
        cmp:                Current market price (INR).
        lot_size:           F&O lot size for this symbol.
        expiry_date:        Option expiry date (YYYY-MM-DD).
        days_to_expiry:     Calendar days from today to expiry.
        option_chain:       List of call option dicts from get_option_chain(),
                            each with keys: strike_price, ltp, iv, open_interest.
        already_holds:      True = user owns shares and will write against them.
                            False = buy-write (buy stock + write call simultaneously).
        quantity_held:      Shares already held (ignored when already_holds=False).
        avg_purchase_price: Average cost per share of existing holding (INR).
                            Ignored when already_holds=False (cost_basis = cmp).
        brokerage:          Fixed brokerage per option lot (INR).
        stt_rate:           STT on option premium as a decimal (0.001 = 0.1%).
        gst_rate:           GST on brokerage as a decimal (0.18 = 18%).

    Returns:
        Dict with keys:
          symbol, cmp, expiry_date, days_to_expiry, lot_size,
          position: {lots, shares, cost_basis_per_share, total_cost, already_holds},
          strikes: list of per-strike analysis dicts (see _analyse_strike).

    Raises:
        ValueError: If the option chain is empty or contains no valid strikes.
    """
    if not option_chain:
        raise ValueError(f"Option chain is empty for {symbol} expiry {expiry_date}.")

    # --- Position size ---
    if already_holds:
        lots = max(quantity_held // lot_size, 1)
        cost_basis = avg_purchase_price if avg_purchase_price > 0 else cmp
    else:
        lots = 1
        cost_basis = cmp

    shares = lots * lot_size
    total_cost = round(cost_basis * shares, 2)

    # --- Strike selection ---
    # option_chain is sorted ascending by strike_price (guaranteed by data_fetcher)
    strikes = [c["strike_price"] for c in option_chain]
    atm_idx = _find_atm_index(strikes, cmp)

    # Build {index: label} for the strikes we want to analyse
    target_indices: dict[int, str] = {}
    if atm_idx > 0:
        target_indices[atm_idx - 1] = "ITM"
    target_indices[atm_idx] = "ATM"
    if atm_idx + 1 < len(strikes):
        target_indices[atm_idx + 1] = "OTM+1"
    if atm_idx + 2 < len(strikes):
        target_indices[atm_idx + 2] = "OTM+2"

    # --- Per-strike analysis ---
    analysed_strikes = []
    for idx, label in sorted(target_indices.items()):
        contract = option_chain[idx]
        result = _analyse_strike(
            strike=contract["strike_price"],
            strike_type=label,
            ltp=contract["ltp"],
            iv=contract.get("iv"),
            open_interest=contract.get("open_interest"),
            volume=contract.get("volume"),
            cost_basis=cost_basis,
            shares=shares,
            lots=lots,
            total_cost=total_cost,
            days_to_expiry=days_to_expiry,
            brokerage=brokerage,
            stt_rate=stt_rate,
            gst_rate=gst_rate,
        )
        analysed_strikes.append(result)

    return {
        "symbol": symbol,
        "cmp": cmp,
        "expiry_date": expiry_date,
        "days_to_expiry": days_to_expiry,
        "lot_size": lot_size,
        "position": {
            "lots": lots,
            "shares": shares,
            "cost_basis_per_share": cost_basis,
            "total_cost": total_cost,
            "already_holds": already_holds,
        },
        "strikes": analysed_strikes,
    }
