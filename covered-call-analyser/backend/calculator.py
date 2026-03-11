"""
calculator.py — Covered call strategy maths (pure functions, no API calls).

Phase 3 implements the full analyse_covered_call() function.
This file is a stub in Phase 1 — the structure is defined but the logic
will be filled in during Phase 3.
"""


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
    """Analyse a covered call position and return scenario metrics.

    (Full implementation in Phase 3.)

    Args:
        symbol:             NSE ticker.
        cmp:                Current market price (INR).
        lot_size:           F&O lot size for this symbol.
        expiry_date:        Option expiry date (YYYY-MM-DD).
        days_to_expiry:     Calendar days from today to expiry.
        option_chain:       List of call option dicts (from get_option_chain).
        already_holds:      True = user owns shares; False = buy-write.
        quantity_held:      Number of shares held (if already_holds=True).
        avg_purchase_price: Average cost of existing holding (INR/share).
        brokerage:          Fixed brokerage per option leg (INR).
        stt_rate:           STT rate on option premium (decimal).
        gst_rate:           GST rate on brokerage (decimal).

    Returns:
        A dict with keys: position_setup, scenarios (ITM/ATM/OTM),
        recommendation, risk_note.
    """
    raise NotImplementedError(
        "analyse_covered_call() will be implemented in Phase 3. "
        "This stub exists so imports work from Phase 1 onward."
    )
