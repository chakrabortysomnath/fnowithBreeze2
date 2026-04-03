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


def calculate_strangle(
    symbol: str,
    cmp: float,
    lot_size: int,
    expiry_date: str,
    days_to_expiry: int,
    call_strike: float,
    call_premium: float,
    put_strike: float,
    put_premium: float,
    brokerage: float = 40.0,
    stt_rate: float = 0.001,
    gst_rate: float = 0.18,
) -> dict:
    """Compute P&L metrics for a short strangle position.

    A short strangle = sell OTM call + sell OTM put on the same stock/expiry.
    - Max profit: total net premium collected (if stock stays between strikes at expiry)
    - Unlimited loss if stock rallies above upper breakeven
    - Limited loss if stock crashes below lower breakeven

    Args:
        symbol:               F&O symbol (e.g., "BANKNIFTY")
        cmp:                  Current market price (INR)
        lot_size:             Shares per lot
        expiry_date:          Option expiry (YYYY-MM-DD format)
        days_to_expiry:       Calendar days from today to expiry
        call_strike:          Strike price of short call (INR)
        call_premium:         Premium of short call (what we receive, INR/share)
        put_strike:           Strike price of short put (INR)
        put_premium:          Premium of short put (what we receive, INR/share)
        brokerage:            Fixed brokerage per lot (INR)
        stt_rate:             STT rate as decimal (0.001 = 0.1%)
        gst_rate:             GST rate as decimal (0.18 = 18%)

    Returns:
        dict matching StrangleAnalyseResponse structure with all metrics.
    """
    shares = lot_size

    # Compute charges for each leg (call and put are separate)
    call_charges = _compute_charges(
        call_premium, shares, 1, brokerage, stt_rate, gst_rate
    )
    put_charges = _compute_charges(
        put_premium, shares, 1, brokerage, stt_rate, gst_rate
    )

    # Gross premiums
    call_premium_total = round(call_premium * shares, 2)
    put_premium_total = round(put_premium * shares, 2)

    # Net premiums (after charges)
    call_net_total = round(call_premium_total - call_charges["total"], 2)
    call_net_per_share = round(call_net_total / shares, 4)

    put_net_total = round(put_premium_total - put_charges["total"], 2)
    put_net_per_share = round(put_net_total / shares, 4)

    # Combined net premium (both legs, what we keep after charges)
    total_net_per_share = round(call_net_per_share + put_net_per_share, 4)
    total_net_total = round(call_net_total + put_net_total, 2)

    # Breakevens
    upper_breakeven = round(call_strike + total_net_per_share, 2)
    lower_breakeven = round(put_strike - total_net_per_share, 2)
    profit_zone_width = round(upper_breakeven - lower_breakeven, 2)

    # P&L bounds
    # Max profit: total net premium collected (if stock stays between strikes)
    max_profit = round(total_net_per_share * shares, 2)

    # Max loss upside: unlimited
    max_loss_upside = "Unlimited"

    # Max loss downside: (put_strike - net_premium) * shares
    # If stock goes to zero, we keep the net premium but lose the put strike value
    max_loss_downside = round((put_strike - total_net_per_share) * shares, 2)

    # Estimated margin (SPAN ~15% of notional of larger leg)
    larger_strike = max(call_strike, put_strike)
    larger_notional = round(larger_strike * shares, 2)
    estimated_margin = round(larger_notional * 0.15, 2)

    # ROI on margin
    roi_on_margin_pct = (
        round((total_net_per_share / (estimated_margin / shares)) * 100, 2)
        if estimated_margin > 0
        else 0
    )

    # Payoff curve: P&L at expiry for range of stock prices (CMP ± 15%)
    lo = round(cmp * 0.85, 2)
    hi = round(cmp * 1.15, 2)
    n_points = 50
    step = (hi - lo) / (n_points - 1) if n_points > 1 else 0
    payoff_points = []

    for i in range(n_points):
        price = round(lo + i * step, 2)

        # P&L from short call: if stock above call_strike, we lose
        # (stock_price - call_strike) * shares
        if price > call_strike:
            call_pl = round(-(price - call_strike) * shares, 2)
        else:
            call_pl = 0

        # P&L from short put: if stock below put_strike, we lose
        # (put_strike - stock_price) * shares
        if price < put_strike:
            put_pl = round(-(put_strike - price) * shares, 2)
        else:
            put_pl = 0

        # Total P&L = call_pl + put_pl + net premiums - charges
        total_pl = round(
            call_pl + put_pl + total_net_total,
            2
        )

        payoff_points.append({"price": price, "pl": total_pl})

    return {
        "symbol": symbol,
        "cmp": cmp,
        "lot_size": lot_size,
        "expiry_date": expiry_date,
        "days_to_expiry": days_to_expiry,
        "call_leg": {
            "strike": call_strike,
            "leg_type": "CE",
            "premium_per_share": call_premium,
            "premium_total": call_premium_total,
            "charges": call_charges,
            "net_premium_per_share": call_net_per_share,
            "net_premium_total": call_net_total,
        },
        "put_leg": {
            "strike": put_strike,
            "leg_type": "PE",
            "premium_per_share": put_premium,
            "premium_total": put_premium_total,
            "charges": put_charges,
            "net_premium_per_share": put_net_per_share,
            "net_premium_total": put_net_total,
        },
        "total_premium_collected": total_net_per_share,
        "total_premium_collected_total": total_net_total,
        "upper_breakeven": upper_breakeven,
        "lower_breakeven": lower_breakeven,
        "profit_zone_width": profit_zone_width,
        "max_profit": max_profit,
        "max_loss_upside": max_loss_upside,
        "max_loss_downside": max_loss_downside,
        "estimated_margin_required": estimated_margin,
        "roi_on_margin_pct": roi_on_margin_pct,
        "payoff": payoff_points,
    }
