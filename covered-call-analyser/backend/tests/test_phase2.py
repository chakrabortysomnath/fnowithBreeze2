"""
test_phase2.py — Phase 2 unit tests.

Tests lot size lookup, expiry date fetching, and option chain fetching.
All tests are offline — Breeze API calls are mocked.

Run:
    cd covered-call-analyser
    pytest backend/tests/test_phase2.py -v
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
# Lot size tests
# ---------------------------------------------------------------------------

def test_get_lot_size_known_symbol():
    """get_lot_size returns the correct lot size for a known symbol."""
    with patch.dict("os.environ", ENV):
        from backend.data_fetcher import get_lot_size
        assert get_lot_size("RELIANCE") == 250
        assert get_lot_size("reliance") == 250   # case-insensitive
        assert get_lot_size("M&M") == 700
        assert get_lot_size("NIFTY") == 25


def test_get_lot_size_unknown_symbol():
    """get_lot_size raises ValueError for an unknown symbol."""
    with patch.dict("os.environ", ENV):
        from backend.data_fetcher import get_lot_size
        with pytest.raises(ValueError, match="Lot size not found"):
            get_lot_size("NOTAREALSTOCK")


def test_lot_size_endpoint_known():
    """/lot-size/RELIANCE returns 200 with correct lot size."""
    with patch.dict("os.environ", ENV):
        with patch("backend.main.is_connected", return_value=True):
            from backend.main import app
            client = TestClient(app)
            resp = client.get("/lot-size/RELIANCE")

    assert resp.status_code == 200
    body = resp.json()
    assert body["symbol"] == "RELIANCE"
    assert body["lot_size"] == 250
    print(f"\n  /lot-size/RELIANCE: {body}")


def test_lot_size_endpoint_unknown():
    """/lot-size/UNKNOWNSYM returns 404."""
    with patch.dict("os.environ", ENV):
        with patch("backend.main.is_connected", return_value=True):
            from backend.main import app
            client = TestClient(app)
            resp = client.get("/lot-size/UNKNOWNSYM")

    assert resp.status_code == 404
    assert "detail" in resp.json()
    print(f"\n  /lot-size/UNKNOWNSYM correctly returned 404: {resp.json()['detail']}")


def test_lot_size_endpoint_url_encoded_ampersand():
    """/lot-size/M%26M correctly decodes to M&M and returns its lot size."""
    with patch.dict("os.environ", ENV):
        with patch("backend.main.is_connected", return_value=True):
            from backend.main import app
            client = TestClient(app)
            resp = client.get("/lot-size/M%26M")

    assert resp.status_code == 200
    body = resp.json()
    assert body["symbol"] == "M&M"
    assert body["lot_size"] == 700
    print(f"\n  /lot-size/M%26M: {body}")


# ---------------------------------------------------------------------------
# Expiry date tests
# ---------------------------------------------------------------------------

def test_get_available_expiries_returns_three_dates():
    """get_available_expiries returns exactly 3 future dates in YYYY-MM-DD format."""
    with patch.dict("os.environ", ENV):
        from backend.data_fetcher import get_available_expiries
        result = get_available_expiries("RELIANCE")

    assert len(result) == 3
    # Each must be a valid YYYY-MM-DD
    from datetime import date
    for d in result:
        parsed = date.fromisoformat(d)
        assert parsed >= date.today(), f"Expiry {d} is in the past"
    # Must be sorted ascending
    assert result == sorted(result)
    print(f"\n  get_available_expiries: {result}")


def test_get_available_expiries_are_tuesday_or_monday():
    """Each expiry is a Tuesday, or a Monday when the last Tuesday is a quarter-end."""
    with patch.dict("os.environ", ENV):
        from backend.data_fetcher import get_available_expiries
        result = get_available_expiries("RELIANCE")

    from datetime import date, timedelta
    from calendar import monthrange
    QUARTER_ENDS = {(3, 31), (6, 30), (9, 30), (12, 31)}
    for d in result:
        parsed = date.fromisoformat(d)
        # Find what the last Tuesday of this expiry's month actually is
        _, days = monthrange(parsed.year, parsed.month)
        last_day = date(parsed.year, parsed.month, days)
        days_back = (last_day.weekday() - 1) % 7
        last_tue = last_day - timedelta(days=days_back)
        if (last_tue.month, last_tue.day) in QUARTER_ENDS:
            # Exception: expiry should be the Monday before the last Tuesday
            expected = last_tue - timedelta(days=1)
            assert parsed == expected, f"{d}: expected Monday {expected} (quarter-end exception)"
            assert parsed.weekday() == 0, f"{d}: expected Monday, got weekday {parsed.weekday()}"
        else:
            assert parsed == last_tue, f"{d}: expected last Tuesday {last_tue}"
            assert parsed.weekday() == 1, f"{d}: expected Tuesday, got weekday {parsed.weekday()}"
    print(f"\n  All expiry dates pass Tuesday/Monday-on-quarter-end rule: {result}")


def test_monthly_expiry_quarter_end_exception():
    """_monthly_expiry moves to Monday when last Tuesday is a quarter-end."""
    with patch.dict("os.environ", ENV):
        from backend.data_fetcher import _monthly_expiry
        from datetime import date

        # Find a month where the last Tuesday IS a quarter-end to test the exception.
        # We'll test by brute-force checking years 2024-2030.
        QUARTER_ENDS = {(3, 31), (6, 30), (9, 30), (12, 31)}
        found = False
        for y in range(2024, 2031):
            for m in [3, 6, 9, 12]:
                result = _monthly_expiry(y, m)
                # The last Tuesday of this month:
                from calendar import monthrange
                from datetime import timedelta
                _, days = monthrange(y, m)
                last_day = date(y, m, days)
                days_back = (last_day.weekday() - 1) % 7
                last_tue = last_day - timedelta(days=days_back)
                if (last_tue.month, last_tue.day) in QUARTER_ENDS:
                    # Exception should apply: result must be Monday before last_tue
                    assert result == last_tue - timedelta(days=1), (
                        f"{y}-{m:02d}: expected Monday {last_tue - timedelta(days=1)}, got {result}"
                    )
                    assert result.weekday() == 0, f"Expected Monday, got weekday {result.weekday()}"
                    found = True
                    print(f"\n  Quarter-end exception verified: {y}-{m:02d} last_tue={last_tue} → expiry={result}")
        assert found, "No quarter-end Tuesday found in 2024-2030 — test data problem"


def test_monthly_expiry_normal_case():
    """_monthly_expiry returns last Tuesday when it is not a quarter-end."""
    with patch.dict("os.environ", ENV):
        from backend.data_fetcher import _monthly_expiry
        from datetime import date, timedelta
        from calendar import monthrange

        QUARTER_ENDS = {(3, 31), (6, 30), (9, 30), (12, 31)}
        # Check all months of 2025; for any where last Tuesday is NOT a quarter-end
        # the result must equal the last Tuesday
        for m in range(1, 13):
            result = _monthly_expiry(2025, m)
            _, days = monthrange(2025, m)
            last_day = date(2025, m, days)
            days_back = (last_day.weekday() - 1) % 7
            last_tue = last_day - timedelta(days=days_back)
            if (last_tue.month, last_tue.day) not in QUARTER_ENDS:
                assert result == last_tue, (
                    f"2025-{m:02d}: expected last Tuesday {last_tue}, got {result}"
                )
    print("\n  _monthly_expiry normal-case (non-quarter-end Tuesday): OK")


def test_expiries_endpoint():
    """/expiries/RELIANCE returns 200 with 3 sorted future dates."""
    with patch.dict("os.environ", ENV):
        with patch("backend.main.is_connected", return_value=True):
            from backend.main import app
            client = TestClient(app)
            resp = client.get("/expiries/RELIANCE")

    assert resp.status_code == 200
    body = resp.json()
    assert body["symbol"] == "RELIANCE"
    assert len(body["expiries"]) == 3
    assert body["expiries"] == sorted(body["expiries"])
    print(f"\n  /expiries/RELIANCE: {body['expiries']}")


# ---------------------------------------------------------------------------
# Option chain tests
# ---------------------------------------------------------------------------

def _mock_chain_response():
    return {
        "Status": 200,
        "Error": None,
        "Success": [
            {
                "strike_price": "2900",
                "ltp": "55.50",
                "open_interest": "125000",
                "implied_volatility": "18.5",
                "volume": "34000",
            },
            {
                "strike_price": "2950",
                "ltp": "32.75",
                "open_interest": "98000",
                "implied_volatility": "19.1",
                "volume": "21000",
            },
            {
                "strike_price": "3000",
                "ltp": "18.20",
                "open_interest": "210000",
                "implied_volatility": "20.3",
                "volume": "55000",
            },
        ],
    }


def test_get_option_chain_returns_sorted_contracts():
    """get_option_chain returns list of contracts sorted by strike_price ascending."""
    mock_session = MagicMock()
    mock_session.get_option_chain_quotes.return_value = _mock_chain_response()

    with patch.dict("os.environ", ENV):
        with patch("backend.data_fetcher.get_session", return_value=mock_session):
            from backend.data_fetcher import get_option_chain
            result = get_option_chain("RELIANCE", "2024-03-28")

    assert len(result) == 3
    assert result[0]["strike_price"] == 2900.0
    assert result[0]["ltp"] == 55.50
    assert result[0]["option_type"] == "CE"
    assert result[1]["strike_price"] == 2950.0
    assert result[2]["strike_price"] == 3000.0

    # Verify date format conversion: YYYY-MM-DD → ISO 8601 required by Breeze
    mock_session.get_option_chain_quotes.assert_called_once_with(
        stock_code="RELIANCE",
        exchange_code="NFO",
        product_type="options",
        expiry_date="2024-03-28T06:00:00.000Z",
        right="call",
        strike_price="0",
    )
    print(f"\n  get_option_chain: {len(result)} contracts, strikes={[c['strike_price'] for c in result]}")


def test_get_option_chain_empty_response():
    """get_option_chain raises ValueError when Breeze returns empty Success."""
    mock_session = MagicMock()
    mock_session.get_option_chain_quotes.return_value = {
        "Status": 200, "Error": None, "Success": []
    }

    with patch.dict("os.environ", ENV):
        with patch("backend.data_fetcher.get_session", return_value=mock_session):
            from backend.data_fetcher import get_option_chain
            with pytest.raises(ValueError, match="No option chain data"):
                get_option_chain("RELIANCE", "2024-03-28")


def test_option_chain_endpoint():
    """/option-chain/RELIANCE?expiry=2024-03-28 returns 200 with contracts."""
    mock_session = MagicMock()
    mock_session.get_option_chain_quotes.return_value = _mock_chain_response()

    with patch.dict("os.environ", ENV):
        with patch("backend.data_fetcher.get_session", return_value=mock_session):
            with patch("backend.breeze_client.get_session", return_value=mock_session):
                from backend.main import app
                client = TestClient(app)
                resp = client.get("/option-chain/RELIANCE?expiry=2024-03-28")

    assert resp.status_code == 200
    body = resp.json()
    assert body["symbol"] == "RELIANCE"
    assert body["expiry_date"] == "2024-03-28"
    assert len(body["options"]) == 3
    assert body["options"][0]["strike_price"] == 2900.0
    assert body["options"][0]["option_type"] == "CE"
    print(f"\n  /option-chain/RELIANCE: {len(body['options'])} contracts")


def test_option_chain_endpoint_invalid_expiry_format():
    """/option-chain/{symbol} returns 400 if expiry format is wrong."""
    with patch.dict("os.environ", ENV):
        with patch("backend.main.is_connected", return_value=True):
            from backend.main import app
            client = TestClient(app)
            resp = client.get("/option-chain/RELIANCE?expiry=28-Mar-2024")

    assert resp.status_code == 400
    assert "YYYY-MM-DD" in resp.json()["detail"]
    print(f"\n  Bad expiry format correctly returned 400: {resp.json()['detail']}")


def test_to_breeze_iso_conversion():
    """_to_breeze_iso converts YYYY-MM-DD to Breeze ISO format correctly."""
    with patch.dict("os.environ", ENV):
        from backend.data_fetcher import _to_breeze_iso
        assert _to_breeze_iso("2024-03-28") == "2024-03-28T06:00:00.000Z"
        assert _to_breeze_iso("2024-12-26") == "2024-12-26T06:00:00.000Z"
        assert _to_breeze_iso("2025-01-02") == "2025-01-02T06:00:00.000Z"
    print("\n  _to_breeze_iso conversion: OK")
