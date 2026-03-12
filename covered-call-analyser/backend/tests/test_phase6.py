"""
test_phase6.py — Phase 6 tests: watchlist endpoint + PDF report helper.

Tests cover:
  POST /analyse-watchlist:
    - single item success
    - multi-item success
    - partial failure (one good, one bad)
    - all items fail
    - empty list → 422
    - too many items (>20) → 422
    - invalid expiry per item collected as error (not 400)

  generate_pdf():
    - returns bytes
    - starts with the PDF magic number (%PDF)
    - non-empty output for a single result
    - multiple results produce a larger PDF than one
    - symbol name is encoded somewhere in the PDF bytes
    - empty list raises ValueError

Run:
    cd covered-call-analyser
    pytest backend/tests/test_phase6.py -v
"""

import sys
import os
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient


ENV = {
    "BREEZE_API_KEY":       "k",
    "BREEZE_API_SECRET":    "s",
    "BREEZE_SESSION_TOKEN": "t",
}

# ---------------------------------------------------------------------------
# Shared mock helpers
# ---------------------------------------------------------------------------

def _mock_chain_raw():
    """Minimal option chain as returned by Breeze (string values)."""
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


def _mock_session():
    """Return a MagicMock BreezeConnect session that returns valid data."""
    sess = MagicMock()
    sess.get_quotes.return_value = {
        "Status": 200, "Error": None,
        "Success": [{"last_traded_price": "2865.00"}],
    }
    sess.get_option_chain_quotes.return_value = {
        "Status": 200, "Error": None,
        "Success": _mock_chain_raw(),
    }
    return sess


def _client(mock_sess=None):
    """Build a TestClient with Breeze mocked."""
    if mock_sess is None:
        mock_sess = _mock_session()
    with patch.dict("os.environ", ENV):
        with patch("backend.data_fetcher.get_session", return_value=mock_sess):
            from backend.main import app
            return TestClient(app), mock_sess


def _watchlist_payload(items):
    return {"items": items}


def _item(symbol="RELIANCE", expiry="2026-04-29", already_holds=False):
    return {
        "symbol":        symbol,
        "expiry_date":   expiry,
        "already_holds": already_holds,
    }


# ---------------------------------------------------------------------------
# POST /analyse-watchlist
# ---------------------------------------------------------------------------

def test_watchlist_single_item_success():
    """A single valid item returns status=ok and a full AnalyseResponse."""
    mock_sess = _mock_session()
    with patch.dict("os.environ", ENV):
        with patch("backend.data_fetcher.get_session", return_value=mock_sess):
            from backend.main import app
            client = TestClient(app)
            resp = client.post(
                "/analyse-watchlist",
                json=_watchlist_payload([_item()]),
            )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"]     == 1
    assert body["succeeded"] == 1
    assert body["failed"]    == 0

    result = body["results"][0]
    assert result["status"] == "ok"
    assert result["symbol"] == "RELIANCE"
    assert "strikes"  in result["result"]
    assert "position" in result["result"]


def test_watchlist_multi_item_success():
    """Two valid items both succeed; total=2, succeeded=2."""
    mock_sess = _mock_session()
    with patch.dict("os.environ", ENV):
        with patch("backend.data_fetcher.get_session", return_value=mock_sess):
            from backend.main import app
            client = TestClient(app)
            resp = client.post(
                "/analyse-watchlist",
                json=_watchlist_payload([
                    _item("RELIANCE", "2026-04-29"),
                    _item("INFY",     "2026-04-29"),
                ]),
            )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"]     == 2
    assert body["succeeded"] == 2
    assert body["failed"]    == 0
    symbols = [r["symbol"] for r in body["results"]]
    assert "RELIANCE" in symbols
    assert "INFY"     in symbols


def test_watchlist_partial_failure():
    """One good symbol + one unknown symbol → succeeded=1, failed=1."""
    def _side_effect_get_session():
        return _mock_session()

    bad_sess = MagicMock()
    bad_sess.get_quotes.return_value = {
        "Status": 200, "Error": None, "Success": [],  # empty → ValueError
    }
    bad_sess.get_option_chain_quotes.return_value = {
        "Status": 200, "Error": None, "Success": _mock_chain_raw(),
    }

    call_count = {"n": 0}

    def _alt_session():
        call_count["n"] += 1
        # First call (RELIANCE) succeeds; second call (BADINC) returns empty quote
        if call_count["n"] == 1:
            return _mock_session()
        return bad_sess

    with patch.dict("os.environ", ENV):
        with patch("backend.data_fetcher.get_session", side_effect=_alt_session):
            from backend.main import app
            client = TestClient(app)
            resp = client.post(
                "/analyse-watchlist",
                json=_watchlist_payload([
                    _item("RELIANCE", "2026-04-29"),
                    _item("BADINC",   "2026-04-29"),
                ]),
            )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"]     == 2
    assert body["succeeded"] == 1
    assert body["failed"]    == 1

    statuses = {r["symbol"]: r["status"] for r in body["results"]}
    assert statuses["RELIANCE"] == "ok"
    assert statuses["BADINC"]   == "error"
    assert body["results"][1]["error"] is not None


def test_watchlist_all_fail():
    """All items fail → succeeded=0, failed=N, status=200 (not 500)."""
    bad_sess = MagicMock()
    bad_sess.get_quotes.return_value = {
        "Status": 200, "Error": None, "Success": [],
    }

    with patch.dict("os.environ", ENV):
        with patch("backend.data_fetcher.get_session", return_value=bad_sess):
            from backend.main import app
            client = TestClient(app)
            resp = client.post(
                "/analyse-watchlist",
                json=_watchlist_payload([
                    _item("BADINC1", "2026-04-29"),
                    _item("BADINC2", "2026-04-29"),
                ]),
            )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["succeeded"] == 0
    assert body["failed"]    == 2


def test_watchlist_empty_list_returns_422():
    """An empty items list fails Pydantic min_length validation → 422."""
    with patch.dict("os.environ", ENV):
        with patch("backend.breeze_client.BreezeConnect"):
            from backend.main import app
            client = TestClient(app)
            resp = client.post(
                "/analyse-watchlist",
                json=_watchlist_payload([]),
            )

    assert resp.status_code == 422


def test_watchlist_too_many_items_returns_422():
    """21 items exceeds max_length=20 → 422."""
    with patch.dict("os.environ", ENV):
        with patch("backend.breeze_client.BreezeConnect"):
            from backend.main import app
            client = TestClient(app)
            items = [_item(f"SYM{i}", "2026-04-29") for i in range(21)]
            resp = client.post(
                "/analyse-watchlist",
                json=_watchlist_payload(items),
            )

    assert resp.status_code == 422


def test_watchlist_invalid_expiry_per_item_collected_as_error():
    """An item with a bad expiry format is collected as status=error, not a 400."""
    mock_sess = _mock_session()
    with patch.dict("os.environ", ENV):
        with patch("backend.data_fetcher.get_session", return_value=mock_sess):
            from backend.main import app
            client = TestClient(app)
            resp = client.post(
                "/analyse-watchlist",
                json=_watchlist_payload([
                    {"symbol": "RELIANCE", "expiry_date": "29-04-2026",
                     "already_holds": False},
                ]),
            )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["failed"] == 1
    assert body["results"][0]["status"] == "error"


# ---------------------------------------------------------------------------
# generate_pdf() — pure unit tests, no HTTP
# ---------------------------------------------------------------------------

# Ensure frontend/ is on sys.path so we can import pdf_report directly
_FRONTEND_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "frontend"
)
if _FRONTEND_DIR not in sys.path:
    sys.path.insert(0, os.path.abspath(_FRONTEND_DIR))

from pdf_report import generate_pdf  # noqa: E402


def _sample_result(symbol="RELIANCE"):
    """Minimal AnalyseResponse-shaped dict for PDF generation tests."""
    return {
        "symbol":         symbol,
        "cmp":            2865.0,
        "expiry_date":    "2026-04-29",
        "days_to_expiry": 48,
        "lot_size":       250,
        "timestamp":      "2026-03-12T10:00:00Z",
        "position": {
            "lots":                1,
            "shares":              250,
            "cost_basis_per_share": 2865.0,
            "total_cost":          716250.0,
            "already_holds":       False,
        },
        "strikes": [
            {
                "strike_type":           "ATM",
                "strike":                2900.0,
                "premium":               55.0,
                "net_premium_per_share": 52.5,
                "net_premium_total":     13125.0,
                "gross_premium_total":   13750.0,
                "charges": {
                    "stt": 13.75, "brokerage": 40.0,
                    "gst": 7.2,   "total": 60.95,
                },
                "breakeven":              2812.5,
                "breakeven_pct_below_cmp": 1.83,
                "max_profit_per_share":    87.5,
                "max_profit_total":        21875.0,
                "premium_yield_pct":       1.83,
                "annualised_yield_pct":    13.9,
                "downside_protection_pct": 1.83,
                "iv": 19.3,
                "open_interest": 80000,
                "payoff": [
                    {"price": 2700.0, "pl": -3125.0},
                    {"price": 2865.0, "pl":  13125.0},
                    {"price": 3000.0, "pl":  21875.0},
                ],
            },
        ],
    }


def test_generate_pdf_returns_bytes():
    """generate_pdf() must return a bytes object."""
    output = generate_pdf([_sample_result()])
    assert isinstance(output, bytes)


def test_generate_pdf_starts_with_pdf_magic():
    """Output must start with the PDF magic number %PDF."""
    output = generate_pdf([_sample_result()])
    assert output[:4] == b"%PDF", f"Expected %PDF header, got {output[:8]!r}"


def test_generate_pdf_single_result_non_empty():
    """A single-result PDF must be non-trivially sized (>1 KB)."""
    output = generate_pdf([_sample_result()])
    assert len(output) > 1024, f"PDF too small: {len(output)} bytes"


def test_generate_pdf_multiple_results_larger_than_one():
    """Two results produce a larger PDF than one result."""
    one   = generate_pdf([_sample_result("RELIANCE")])
    two   = generate_pdf([_sample_result("RELIANCE"), _sample_result("INFY")])
    assert len(two) > len(one), (
        f"Expected two-symbol PDF ({len(two)} B) > one-symbol PDF ({len(one)} B)"
    )


def test_generate_pdf_symbol_in_output():
    """The symbol name must appear in the PDF metadata (title is stored uncompressed)."""
    symbol = "RELIANCE"
    title = f"{symbol} Covered Call Report"
    output = generate_pdf([_sample_result(symbol)], title=title)
    assert symbol.encode("latin-1") in output, (
        f"Symbol '{symbol}' not found in PDF metadata"
    )


def test_generate_pdf_empty_list_raises():
    """Passing an empty results list must raise ValueError."""
    with pytest.raises(ValueError, match="at least one"):
        generate_pdf([])
