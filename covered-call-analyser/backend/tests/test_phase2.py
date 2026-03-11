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

def _mock_expiry_response():
    return {
        "Status": 200,
        "Error": None,
        "Success": [
            {"expiry_date": "2024-04-25T00:00:00.000Z"},
            {"expiry_date": "2024-03-28T00:00:00.000Z"},
            {"expiry_date": "2024-05-30T00:00:00.000Z"},
        ],
    }


def test_get_available_expiries_returns_sorted_dates():
    """get_available_expiries returns dates in YYYY-MM-DD format, sorted ascending."""
    mock_session = MagicMock()
    mock_session.get_expiry_date.return_value = _mock_expiry_response()

    with patch.dict("os.environ", ENV):
        with patch("backend.data_fetcher.get_session", return_value=mock_session):
            from backend.data_fetcher import get_available_expiries
            result = get_available_expiries("RELIANCE")

    assert result == ["2024-03-28", "2024-04-25", "2024-05-30"]
    mock_session.get_expiry_date.assert_called_once_with(
        stock_code="RELIANCE",
        exchange_code="NFO",
        product_type="options",
    )
    print(f"\n  get_available_expiries: {result}")


def test_get_available_expiries_empty_response():
    """get_available_expiries raises ValueError when Breeze returns empty Success."""
    mock_session = MagicMock()
    mock_session.get_expiry_date.return_value = {
        "Status": 200, "Error": None, "Success": []
    }

    with patch.dict("os.environ", ENV):
        with patch("backend.data_fetcher.get_session", return_value=mock_session):
            from backend.data_fetcher import get_available_expiries
            with pytest.raises(ValueError, match="No expiry dates"):
                get_available_expiries("RELIANCE")


def test_get_available_expiries_non_200():
    """get_available_expiries raises ValueError on non-200 Breeze status."""
    mock_session = MagicMock()
    mock_session.get_expiry_date.return_value = {
        "Status": 400, "Error": "Bad request", "Success": None
    }

    with patch.dict("os.environ", ENV):
        with patch("backend.data_fetcher.get_session", return_value=mock_session):
            from backend.data_fetcher import get_available_expiries
            with pytest.raises(ValueError, match="Breeze API error"):
                get_available_expiries("RELIANCE")


def test_expiries_endpoint():
    """/expiries/RELIANCE returns 200 with sorted date list."""
    mock_session = MagicMock()
    mock_session.get_expiry_date.return_value = _mock_expiry_response()

    with patch.dict("os.environ", ENV):
        with patch("backend.data_fetcher.get_session", return_value=mock_session):
            with patch("backend.breeze_client.get_session", return_value=mock_session):
                from backend.main import app
                client = TestClient(app)
                resp = client.get("/expiries/RELIANCE")

    assert resp.status_code == 200
    body = resp.json()
    assert body["symbol"] == "RELIANCE"
    assert body["expiries"] == ["2024-03-28", "2024-04-25", "2024-05-30"]
    print(f"\n  /expiries/RELIANCE: {body}")


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

    # Verify date format conversion: YYYY-MM-DD → DD-Mon-YYYY
    mock_session.get_option_chain_quotes.assert_called_once_with(
        stock_code="RELIANCE",
        exchange_code="NFO",
        product_type="options",
        expiry_date="28-Mar-2024",
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


def test_to_breeze_date_conversion():
    """_to_breeze_date converts YYYY-MM-DD to DD-Mon-YYYY correctly."""
    from backend.data_fetcher import _to_breeze_date
    assert _to_breeze_date("2024-03-28") == "28-Mar-2024"
    assert _to_breeze_date("2024-12-26") == "26-Dec-2024"
    assert _to_breeze_date("2025-01-02") == "02-Jan-2025"
    print("\n  _to_breeze_date conversion: OK")
