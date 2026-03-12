"""
test_phase4.py — Phase 4 tests: frontend helper functions + end-to-end
                 /analyse → UI rendering path.

These tests stay in the backend test suite because:
  1. They re-use the already-mocked Breeze fixtures from test_phase3.
  2. Full Streamlit AppTest would require the frontend process to be running —
     instead we test the two things that can break silently:
       a) The /analyse JSON contract (keys the frontend consumes).
       b) The chart/table helper logic, extracted and tested as pure functions.

Run:
    cd covered-call-analyser
    pytest backend/tests/test_phase4.py -v
"""

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient


ENV = {
    "BREEZE_API_KEY":      "k",
    "BREEZE_API_SECRET":   "s",
    "BREEZE_SESSION_TOKEN":"t",
}

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _mock_chain_raw():
    """Raw dicts as returned by the Breeze mock (string values)."""
    return [
        {"strike_price": "2800", "ltp": "120.0", "implied_volatility": "17.2",
         "open_interest": "100000", "volume": "5000"},
        {"strike_price": "2850", "ltp": "80.0",  "implied_volatility": "18.1",
         "open_interest": "90000",  "volume": "4000"},
        {"strike_price": "2900", "ltp": "55.0",  "implied_volatility": "19.3",
         "open_interest": "80000",  "volume": "3000"},
        {"strike_price": "2950", "ltp": "32.0",  "implied_volatility": "20.5",
         "open_interest": "60000",  "volume": "2000"},
    ]


def _get_result(already_holds=False, quantity_held=0, avg_price=0.0):
    """Call POST /analyse with Breeze fully mocked; return the JSON body."""
    mock_session = MagicMock()
    mock_session.get_quotes.return_value = {
        "Status": 200, "Error": None,
        "Success": [{"last_traded_price": "2865.00"}],
    }
    mock_session.get_option_chain_quotes.return_value = {
        "Status": 200, "Error": None, "Success": _mock_chain_raw(),
    }

    with patch.dict("os.environ", ENV):
        with patch("backend.data_fetcher.get_session", return_value=mock_session):
            from backend.main import app
            client = TestClient(app)
            resp = client.post("/analyse", json={
                "symbol":             "RELIANCE",
                "expiry_date":        "2026-04-29",
                "already_holds":      already_holds,
                "quantity_held":      quantity_held,
                "avg_purchase_price": avg_price,
            })
            assert resp.status_code == 200, resp.text
            return resp.json()


# ---------------------------------------------------------------------------
# Contract tests — every key the frontend reads must be present
# ---------------------------------------------------------------------------

REQUIRED_TOP_KEYS = {
    "symbol", "cmp", "expiry_date", "days_to_expiry",
    "lot_size", "position", "strikes", "timestamp",
}

REQUIRED_POSITION_KEYS = {
    "lots", "shares", "cost_basis_per_share", "total_cost", "already_holds",
}

REQUIRED_STRIKE_KEYS = {
    "strike", "strike_type", "premium",
    "net_premium_per_share", "net_premium_total", "gross_premium_total",
    "charges", "breakeven", "breakeven_pct_below_cmp",
    "max_profit_per_share", "max_profit_total",
    "premium_yield_pct", "annualised_yield_pct",
    "downside_protection_pct", "iv", "open_interest", "payoff",
}

REQUIRED_CHARGES_KEYS = {"stt", "brokerage", "gst", "total"}
REQUIRED_PAYOFF_KEYS  = {"price", "pl"}



def test_top_level_keys_present():
    """All top-level keys the frontend reads are in the response."""
    body = _get_result()
    assert REQUIRED_TOP_KEYS.issubset(body.keys()), (
        f"Missing: {REQUIRED_TOP_KEYS - body.keys()}"
    )


def test_position_keys_present():
    """All position keys the frontend reads are present."""
    pos = _get_result()["position"]
    assert REQUIRED_POSITION_KEYS.issubset(pos.keys()), (
        f"Missing: {REQUIRED_POSITION_KEYS - pos.keys()}"
    )


def test_strike_keys_present():
    """All per-strike keys the frontend reads are present in every strike."""
    strikes = _get_result()["strikes"]
    assert len(strikes) >= 2, "Expected at least 2 strikes"
    for s in strikes:
        missing = REQUIRED_STRIKE_KEYS - s.keys()
        assert not missing, f"Strike {s.get('strike')}: missing keys {missing}"


def test_charges_keys_present():
    """Charges breakdown contains all expected keys."""
    for s in _get_result()["strikes"]:
        missing = REQUIRED_CHARGES_KEYS - s["charges"].keys()
        assert not missing, f"Strike {s['strike']}: charges missing {missing}"


def test_payoff_keys_present():
    """Each payoff point has 'price' and 'pl' keys."""
    for s in _get_result()["strikes"]:
        assert len(s["payoff"]) == 7
        for pt in s["payoff"]:
            missing = REQUIRED_PAYOFF_KEYS - pt.keys()
            assert not missing, f"Payoff point missing keys: {missing}"


def test_strike_types_are_strings():
    """strike_type must be a non-empty string (used as x-axis label in chart)."""
    for s in _get_result()["strikes"]:
        assert isinstance(s["strike_type"], str) and len(s["strike_type"]) > 0


def test_numeric_fields_are_floats():
    """Key numeric fields are float/int, not strings (chart would break otherwise)."""
    body = _get_result()
    assert isinstance(body["cmp"], (int, float))
    assert isinstance(body["lot_size"], int)
    for s in body["strikes"]:
        for field in ("strike", "premium", "net_premium_total",
                      "breakeven", "max_profit_total",
                      "premium_yield_pct", "downside_protection_pct"):
            assert isinstance(s[field], (int, float)), (
                f"Strike {s['strike']}.{field} is {type(s[field])}, expected number"
            )


def test_payoff_prices_are_floats():
    """Payoff prices and P&L values are numeric (not strings)."""
    for s in _get_result()["strikes"]:
        for pt in s["payoff"]:
            assert isinstance(pt["price"], (int, float))
            assert isinstance(pt["pl"],    (int, float))


# ---------------------------------------------------------------------------
# UI table-row builder logic (extracted from app.py for testing)
# ---------------------------------------------------------------------------

def _build_table_rows(strikes: list[dict]) -> list[dict]:
    """Mirror the table-building logic in frontend/app.py."""
    rows = []
    for s in strikes:
        rows.append({
            "Strike type":       s["strike_type"],
            "Strike (₹)":        f"₹{s['strike']:,.0f}",
            "Net premium":       f"₹{s['net_premium_total']:,.2f}",
            "Breakeven":         f"₹{s['breakeven']:,.2f}",
            "Max profit":        f"₹{s['max_profit_total']:,.2f}",
            "Yield %":           f"{s['premium_yield_pct']:.2f}%",
            "Ann. yield %": (
                f"{s['annualised_yield_pct']:.1f}%"
                if s["annualised_yield_pct"] is not None else "—"
            ),
            "Downside protect.": f"{s['downside_protection_pct']:.2f}%",
        })
    return rows


def test_table_rows_count_matches_strikes():
    """One table row per strike returned by the API."""
    body = _get_result()
    rows = _build_table_rows(body["strikes"])
    assert len(rows) == len(body["strikes"])


def test_table_rows_strike_type_matches():
    """Strike type in table row matches API strike_type."""
    body = _get_result()
    rows = _build_table_rows(body["strikes"])
    for row, strike in zip(rows, body["strikes"]):
        assert row["Strike type"] == strike["strike_type"]


def test_table_row_inr_format():
    """Net premium, breakeven, max profit start with ₹."""
    body = _get_result()
    for row in _build_table_rows(body["strikes"]):
        assert row["Net premium"].startswith("₹")
        assert row["Breakeven"].startswith("₹")
        assert row["Max profit"].startswith("₹")


def test_table_row_yield_ends_with_pct():
    """Yield % and Ann. yield % end with % (or — for DTE=0)."""
    body = _get_result()
    for row in _build_table_rows(body["strikes"]):
        assert row["Yield %"].endswith("%")
        assert row["Ann. yield %"].endswith("%") or row["Ann. yield %"] == "—"


# ---------------------------------------------------------------------------
# Chart data extraction logic
# ---------------------------------------------------------------------------

def test_bar_chart_y_values_positive():
    """All annualised yield values fed to the bar chart are positive (DTE > 0)."""
    body = _get_result()
    for s in body["strikes"]:
        assert s["annualised_yield_pct"] is not None
        assert s["annualised_yield_pct"] > 0


def test_payoff_chart_has_sufficient_range():
    """Payoff chart spans at least 20% of stock price range per strike."""
    body = _get_result()
    cmp = body["cmp"]
    for s in body["strikes"]:
        prices = [p["price"] for p in s["payoff"]]
        spread_pct = (max(prices) - min(prices)) / cmp * 100
        assert spread_pct >= 20, (
            f"Strike {s['strike']}: payoff spread {spread_pct:.1f}% < 20%"
        )


def test_payoff_pl_capped_above_strike():
    """P&L values above the strike price are all equal (capped at max profit)."""
    body = _get_result()
    for s in body["strikes"]:
        above = [p["pl"] for p in s["payoff"] if p["price"] > s["strike"]]
        if len(above) > 1:
            assert len(set(above)) == 1, (
                f"Strike {s['strike']}: P&L above strike not uniformly capped: {above}"
            )


# ---------------------------------------------------------------------------
# already_holds path — verify position fields pass through to frontend contract
# ---------------------------------------------------------------------------

def test_already_holds_position_reflected():
    """When already_holds=True, response position reflects user's holding."""
    body = _get_result(already_holds=True, quantity_held=250, avg_price=2500.0)
    pos = body["position"]
    assert pos["already_holds"]            is True
    assert pos["cost_basis_per_share"]     == 2500.0
    assert pos["shares"]                   == 250


def test_buy_write_position_uses_cmp():
    """When already_holds=False, cost_basis_per_share equals live CMP."""
    body = _get_result(already_holds=False)
    assert body["position"]["cost_basis_per_share"] == body["cmp"]
