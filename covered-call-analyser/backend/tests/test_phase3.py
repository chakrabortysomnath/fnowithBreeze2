"""
test_phase3.py — Phase 3 unit tests for the covered call calculator.

All tests are pure maths — no Breeze connection or mocking required.
The calculator functions take plain Python values and return plain dicts.

Run:
    cd covered-call-analyser
    pytest backend/tests/test_phase3.py -v
"""

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient


ENV = {
    "BREEZE_API_KEY": "k",
    "BREEZE_API_SECRET": "s",
    "BREEZE_SESSION_TOKEN": "t",
}

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

def _chain(strikes, ltps, ivs=None):
    """Build a minimal option chain list for testing."""
    return [
        {
            "strike_price": s,
            "option_type": "CE",
            "ltp": l,
            "iv": (ivs[i] if ivs else None),
            "open_interest": 100000,
            "volume": 10000,
        }
        for i, (s, l) in enumerate(zip(strikes, ltps))
    ]


RELIANCE_CHAIN = _chain(
    strikes=[2800, 2850, 2900, 2950, 3000],
    ltps   =[120.0, 80.0, 55.0, 32.0, 18.0],
    ivs    =[17.2, 18.1, 19.3, 20.5, 22.0],
)

CMP = 2865.0
LOT_SIZE = 250


# ---------------------------------------------------------------------------
# Helper unit tests
# ---------------------------------------------------------------------------

def test_days_to_expiry_future():
    """_days_to_expiry returns a positive integer for a future date."""
    from backend.calculator import _days_to_expiry
    from datetime import date, timedelta
    future = (date.today() + timedelta(days=14)).strftime("%Y-%m-%d")
    assert _days_to_expiry(future) == 14


def test_days_to_expiry_past_returns_zero():
    """_days_to_expiry returns 0 for a past date."""
    from backend.calculator import _days_to_expiry
    assert _days_to_expiry("2020-01-01") == 0


def test_find_atm_index_exact_match():
    """_find_atm_index picks the strike that exactly equals CMP."""
    from backend.calculator import _find_atm_index
    strikes = [2800.0, 2850.0, 2900.0, 2950.0]
    assert _find_atm_index(strikes, 2850.0) == 1


def test_find_atm_index_between_strikes():
    """_find_atm_index picks the closer strike when CMP sits between two."""
    from backend.calculator import _find_atm_index
    strikes = [2800.0, 2850.0, 2900.0, 2950.0]
    # CMP 2870 is closer to 2850 (delta 20) than 2900 (delta 30)
    assert _find_atm_index(strikes, 2870.0) == 1
    # CMP 2880 is closer to 2900 (delta 20) than 2850 (delta 30)
    assert _find_atm_index(strikes, 2880.0) == 2


def test_compute_charges_values():
    """_compute_charges returns correctly rounded charge breakdown."""
    from backend.calculator import _compute_charges
    # premium=80, shares=250, lots=1, brokerage=40, stt=0.001, gst=0.18
    charges = _compute_charges(
        premium_per_share=80.0, shares=250, lots=1,
        brokerage=40.0, stt_rate=0.001, gst_rate=0.18,
    )
    assert charges["stt"]       == round(0.001 * 80.0 * 250, 2)   # 20.0
    assert charges["brokerage"] == 40.0
    assert charges["gst"]       == round(0.18 * 40.0, 2)          # 7.2
    assert charges["total"]     == round(20.0 + 40.0 + 7.2, 2)    # 67.2


def test_compute_charges_scales_with_lots():
    """Brokerage and GST scale with number of lots; STT scales with premium × shares."""
    from backend.calculator import _compute_charges
    c1 = _compute_charges(50.0, 250, 1, 40.0, 0.001, 0.18)
    c2 = _compute_charges(50.0, 500, 2, 40.0, 0.001, 0.18)
    assert c2["stt"]       == c1["stt"] * 2
    assert c2["brokerage"] == c1["brokerage"] * 2
    assert c2["gst"]       == round(c1["gst"] * 2, 2)


def test_payoff_points_count_and_range():
    """_payoff_points returns n points spanning cost_basis×0.85 to strike×1.10."""
    from backend.calculator import _payoff_points
    pts = _payoff_points(cost_basis=2850.0, strike=2900.0,
                         net_premium_per_share=50.0, shares=250, n=7)
    assert len(pts) == 7
    assert pts[0]["price"] == round(2850.0 * 0.85, 2)
    assert pts[-1]["price"] == round(2900.0 * 1.10, 2)


def test_payoff_capped_above_strike():
    """P&L is capped once stock price exceeds the strike."""
    from backend.calculator import _payoff_points
    pts = _payoff_points(cost_basis=2850.0, strike=2900.0,
                         net_premium_per_share=50.0, shares=250, n=7)
    # Any point above strike must equal the capped P&L
    capped_pl = round((2900.0 - 2850.0 + 50.0) * 250, 2)
    above = [p for p in pts if p["price"] > 2900.0]
    assert len(above) > 0, "Expected at least one point above strike"
    for p in above:
        assert p["pl"] == capped_pl, f"P&L not capped at price {p['price']}"


# ---------------------------------------------------------------------------
# analyse_covered_call — buy-write (already_holds=False)
# ---------------------------------------------------------------------------

def test_analyse_buy_write_structure():
    """analyse_covered_call returns all required top-level keys."""
    from backend.calculator import analyse_covered_call
    result = analyse_covered_call(
        symbol="RELIANCE", cmp=CMP, lot_size=LOT_SIZE,
        expiry_date="2026-04-29", days_to_expiry=14,
        option_chain=RELIANCE_CHAIN, already_holds=False,
    )
    for key in ("symbol", "cmp", "expiry_date", "days_to_expiry",
                "lot_size", "position", "strikes"):
        assert key in result, f"Missing key: {key}"


def test_analyse_buy_write_position():
    """Buy-write position uses CMP as cost basis, 1 lot."""
    from backend.calculator import analyse_covered_call
    result = analyse_covered_call(
        symbol="RELIANCE", cmp=CMP, lot_size=LOT_SIZE,
        expiry_date="2026-04-29", days_to_expiry=14,
        option_chain=RELIANCE_CHAIN, already_holds=False,
    )
    pos = result["position"]
    assert pos["already_holds"]       is False
    assert pos["lots"]                == 1
    assert pos["shares"]              == LOT_SIZE
    assert pos["cost_basis_per_share"] == CMP
    assert pos["total_cost"]          == round(CMP * LOT_SIZE, 2)


def test_analyse_returns_atm_otm_strikes():
    """Returns at least ATM and OTM+1 strikes; ITM if available."""
    from backend.calculator import analyse_covered_call
    result = analyse_covered_call(
        symbol="RELIANCE", cmp=CMP, lot_size=LOT_SIZE,
        expiry_date="2026-04-29", days_to_expiry=14,
        option_chain=RELIANCE_CHAIN, already_holds=False,
    )
    types = {s["strike_type"] for s in result["strikes"]}
    assert "ATM"   in types
    assert "OTM+1" in types


def test_analyse_atm_is_closest_to_cmp():
    """The ATM strike returned is the one closest to CMP."""
    from backend.calculator import analyse_covered_call
    result = analyse_covered_call(
        symbol="RELIANCE", cmp=CMP, lot_size=LOT_SIZE,
        expiry_date="2026-04-29", days_to_expiry=14,
        option_chain=RELIANCE_CHAIN, already_holds=False,
    )
    atm = next(s for s in result["strikes"] if s["strike_type"] == "ATM")
    # CMP=2865 → closest strike is 2850 (delta 15) vs 2900 (delta 35)
    assert atm["strike"] == 2850.0


def test_analyse_net_premium_less_than_gross():
    """Net premium total < gross premium total (charges are positive)."""
    from backend.calculator import analyse_covered_call
    result = analyse_covered_call(
        symbol="RELIANCE", cmp=CMP, lot_size=LOT_SIZE,
        expiry_date="2026-04-29", days_to_expiry=14,
        option_chain=RELIANCE_CHAIN, already_holds=False,
    )
    for s in result["strikes"]:
        assert s["net_premium_total"] < s["gross_premium_total"], (
            f"Strike {s['strike']}: net {s['net_premium_total']} >= gross {s['gross_premium_total']}"
        )


def test_analyse_breakeven_below_cost_basis():
    """Breakeven price is always below cost basis (premium provides protection)."""
    from backend.calculator import analyse_covered_call
    result = analyse_covered_call(
        symbol="RELIANCE", cmp=CMP, lot_size=LOT_SIZE,
        expiry_date="2026-04-29", days_to_expiry=14,
        option_chain=RELIANCE_CHAIN, already_holds=False,
    )
    cost_basis = result["position"]["cost_basis_per_share"]
    for s in result["strikes"]:
        assert s["breakeven"] < cost_basis, (
            f"Strike {s['strike']}: breakeven {s['breakeven']} >= cost_basis {cost_basis}"
        )


def test_analyse_max_profit_atm_positive():
    """Max profit for ATM strike (write call at ATM) should be positive."""
    from backend.calculator import analyse_covered_call
    result = analyse_covered_call(
        symbol="RELIANCE", cmp=CMP, lot_size=LOT_SIZE,
        expiry_date="2026-04-29", days_to_expiry=14,
        option_chain=RELIANCE_CHAIN, already_holds=False,
    )
    atm = next(s for s in result["strikes"] if s["strike_type"] == "ATM")
    assert atm["max_profit_total"] > 0


def test_analyse_annualised_yield_positive():
    """Annualised yield is positive when DTE > 0."""
    from backend.calculator import analyse_covered_call
    result = analyse_covered_call(
        symbol="RELIANCE", cmp=CMP, lot_size=LOT_SIZE,
        expiry_date="2026-04-29", days_to_expiry=14,
        option_chain=RELIANCE_CHAIN, already_holds=False,
    )
    for s in result["strikes"]:
        assert s["annualised_yield_pct"] is not None
        assert s["annualised_yield_pct"] > 0


def test_analyse_annualised_yield_none_when_dte_zero():
    """Annualised yield is None when DTE = 0 (avoids division by zero)."""
    from backend.calculator import analyse_covered_call
    result = analyse_covered_call(
        symbol="RELIANCE", cmp=CMP, lot_size=LOT_SIZE,
        expiry_date="2026-04-29", days_to_expiry=0,
        option_chain=RELIANCE_CHAIN, already_holds=False,
    )
    for s in result["strikes"]:
        assert s["annualised_yield_pct"] is None


def test_analyse_payoff_has_seven_points():
    """Each strike analysis includes 7 payoff points."""
    from backend.calculator import analyse_covered_call
    result = analyse_covered_call(
        symbol="RELIANCE", cmp=CMP, lot_size=LOT_SIZE,
        expiry_date="2026-04-29", days_to_expiry=14,
        option_chain=RELIANCE_CHAIN, already_holds=False,
    )
    for s in result["strikes"]:
        assert len(s["payoff"]) == 7, (
            f"Strike {s['strike']}: expected 7 payoff points, got {len(s['payoff'])}"
        )


# ---------------------------------------------------------------------------
# analyse_covered_call — already holds
# ---------------------------------------------------------------------------

def test_analyse_already_holds_uses_avg_price():
    """When already_holds=True, cost basis uses avg_purchase_price, not CMP."""
    from backend.calculator import analyse_covered_call
    avg_price = 2500.0
    result = analyse_covered_call(
        symbol="RELIANCE", cmp=CMP, lot_size=LOT_SIZE,
        expiry_date="2026-04-29", days_to_expiry=14,
        option_chain=RELIANCE_CHAIN,
        already_holds=True, quantity_held=250, avg_purchase_price=avg_price,
    )
    pos = result["position"]
    assert pos["cost_basis_per_share"] == avg_price
    assert pos["total_cost"]           == round(avg_price * LOT_SIZE, 2)


def test_analyse_already_holds_lots_from_quantity():
    """When already_holds=True, lots = quantity_held // lot_size."""
    from backend.calculator import analyse_covered_call
    result = analyse_covered_call(
        symbol="RELIANCE", cmp=CMP, lot_size=LOT_SIZE,
        expiry_date="2026-04-29", days_to_expiry=14,
        option_chain=RELIANCE_CHAIN,
        already_holds=True, quantity_held=500, avg_purchase_price=2800.0,
    )
    assert result["position"]["lots"]   == 2
    assert result["position"]["shares"] == 500


def test_analyse_already_holds_higher_max_profit():
    """Holding at avg_price < CMP gives higher max profit than buy-write at CMP."""
    from backend.calculator import analyse_covered_call

    def _atm_max(already_holds, avg_price):
        r = analyse_covered_call(
            symbol="RELIANCE", cmp=CMP, lot_size=LOT_SIZE,
            expiry_date="2026-04-29", days_to_expiry=14,
            option_chain=RELIANCE_CHAIN,
            already_holds=already_holds,
            quantity_held=LOT_SIZE,
            avg_purchase_price=avg_price,
        )
        return next(s for s in r["strikes"] if s["strike_type"] == "ATM")["max_profit_total"]

    # Lower cost basis → higher max profit at same strike
    assert _atm_max(True, 2500.0) > _atm_max(False, CMP)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_analyse_empty_chain_raises():
    """analyse_covered_call raises ValueError on empty option chain."""
    from backend.calculator import analyse_covered_call
    with pytest.raises(ValueError, match="empty"):
        analyse_covered_call(
            symbol="RELIANCE", cmp=CMP, lot_size=LOT_SIZE,
            expiry_date="2026-04-29", days_to_expiry=14,
            option_chain=[], already_holds=False,
        )


def test_analyse_single_strike_chain():
    """analyse_covered_call works with a single-strike chain (only ATM)."""
    from backend.calculator import analyse_covered_call
    single = _chain([2900], [55.0])
    result = analyse_covered_call(
        symbol="RELIANCE", cmp=2865.0, lot_size=LOT_SIZE,
        expiry_date="2026-04-29", days_to_expiry=14,
        option_chain=single, already_holds=False,
    )
    assert len(result["strikes"]) == 1
    assert result["strikes"][0]["strike_type"] == "ATM"


# ---------------------------------------------------------------------------
# /analyse endpoint (with mocked Breeze)
# ---------------------------------------------------------------------------

def _mock_chain():
    return [
        {"strike_price": 2800.0, "option_type": "CE", "ltp": 120.0,
         "iv": 17.2, "open_interest": 100000, "volume": 5000},
        {"strike_price": 2850.0, "option_type": "CE", "ltp": 80.0,
         "iv": 18.1, "open_interest": 90000,  "volume": 4000},
        {"strike_price": 2900.0, "option_type": "CE", "ltp": 55.0,
         "iv": 19.3, "open_interest": 80000,  "volume": 3000},
        {"strike_price": 2950.0, "option_type": "CE", "ltp": 32.0,
         "iv": 20.5, "open_interest": 60000,  "volume": 2000},
    ]


def test_analyse_endpoint_buy_write():
    """/analyse returns 200 with correct structure for a buy-write request."""
    mock_session = MagicMock()

    with patch.dict("os.environ", ENV):
        with patch("backend.data_fetcher.get_session", return_value=mock_session):
            mock_session.get_quotes.return_value = {
                "Status": 200, "Error": None,
                "Success": [{"last_traded_price": "2865.00"}],
            }
            mock_session.get_option_chain_quotes.return_value = {
                "Status": 200, "Error": None, "Success": [
                    {"strike_price": str(c["strike_price"]), "ltp": str(c["ltp"]),
                     "implied_volatility": str(c["iv"]),
                     "open_interest": str(c["open_interest"]),
                     "volume": str(c["volume"])}
                    for c in _mock_chain()
                ],
            }
            from backend.main import app
            client = TestClient(app)
            resp = client.post("/analyse", json={
                "symbol": "RELIANCE",
                "expiry_date": "2026-04-29",
                "already_holds": False,
            })

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["symbol"]       == "RELIANCE"
    assert body["cmp"]          == 2865.0
    assert body["lot_size"]     == 250
    assert len(body["strikes"]) >= 2
    assert "ATM" in {s["strike_type"] for s in body["strikes"]}

    # Verify all required per-strike keys are present
    for s in body["strikes"]:
        for key in ("strike", "strike_type", "premium", "net_premium_total",
                    "charges", "breakeven", "max_profit_total",
                    "premium_yield_pct", "annualised_yield_pct",
                    "downside_protection_pct", "payoff"):
            assert key in s, f"Missing key '{key}' in strike {s.get('strike')}"

    print(f"\n  /analyse response: {body['symbol']} CMP={body['cmp']} "
          f"strikes={[s['strike_type'] for s in body['strikes']]}")


def test_analyse_endpoint_bad_expiry_format():
    """/analyse returns 400 for an invalid expiry_date format."""
    with patch.dict("os.environ", ENV):
        with patch("backend.main.is_connected", return_value=True):
            from backend.main import app
            client = TestClient(app)
            resp = client.post("/analyse", json={
                "symbol": "RELIANCE",
                "expiry_date": "29-Apr-2026",
                "already_holds": False,
            })
    assert resp.status_code == 400
    assert "YYYY-MM-DD" in resp.json()["detail"]
