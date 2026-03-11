"""
test_phase1.py — Phase 1 unit & integration tests.

Run all tests:
    cd covered-call-analyser
    pytest backend/tests/test_phase1.py -v

Run only offline tests (no Breeze connection required):
    pytest backend/tests/test_phase1.py -v -m "not live"

Tests:
    1. test_python_version          — Validates Python 3.10+
    2. test_settings_fields         — Validates config.py loads expected fields
    3. test_health_endpoint_offline — /health returns correct shape (mocked)
    4. test_quote_endpoint_offline  — /quote/{symbol} with mocked Breeze
    5. test_quote_endpoint_bad_symbol — /quote/{symbol} returns 404 for bad symbol
    6. test_get_cmp_invalid_response  — data_fetcher handles malformed response
"""

import sys
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Test 1 — Python version
# ---------------------------------------------------------------------------

def test_python_version():
    """Validate that Python 3.10+ is installed.

    The project requires:
      - Python 3.10+ for the `X | Y` union type syntax in type hints.
      - Python 3.10+ for `match` statements (used in Phase 3+).
    """
    major = sys.version_info.major
    minor = sys.version_info.minor
    version_str = f"{major}.{minor}.{sys.version_info.micro}"

    print(f"\n  Detected Python version: {version_str}")
    print(f"  Full version string: {sys.version}")

    assert major == 3, (
        f"Expected Python 3.x but found {version_str}. "
        "Please install Python 3.10 or higher."
    )
    assert minor >= 10, (
        f"Expected Python 3.10+ but found {version_str}. "
        "Please upgrade Python. On macOS: brew install python@3.11. "
        "On Ubuntu: sudo apt install python3.11."
    )
    print(f"  Python version check PASSED ({version_str} >= 3.10)")


# ---------------------------------------------------------------------------
# Test 2 — Config fields are accessible
# ---------------------------------------------------------------------------

def test_settings_fields():
    """Validate that config.py exposes the expected fields with correct types.

    This test uses dummy env vars so it doesn't require a real .env file.
    """
    with patch.dict("os.environ", {
        "BREEZE_API_KEY": "test_key",
        "BREEZE_API_SECRET": "test_secret",
        "BREEZE_SESSION_TOKEN": "test_token",
    }):
        # Re-import with patched environment
        from backend.config import Settings
        s = Settings()

        assert s.BREEZE_API_KEY == "test_key"
        assert s.BREEZE_API_SECRET == "test_secret"
        assert s.BREEZE_SESSION_TOKEN == "test_token"
        assert s.DEFAULT_BROKERAGE == 40.0
        assert s.DEFAULT_STT_RATE == 0.001
        assert s.DEFAULT_GST_RATE == 0.18
        assert s.QUOTAGUARDSTATIC_URL is None
        print("\n  Config fields: OK")


# ---------------------------------------------------------------------------
# Test 3 — /health endpoint (offline — no real Breeze call)
# ---------------------------------------------------------------------------

@pytest.mark.live  # NOT marked as live — always runs; Breeze is mocked
def test_health_endpoint_offline():
    """/health returns {"status": "ok", "breeze_connected": true/false}."""
    with patch.dict("os.environ", {
        "BREEZE_API_KEY": "k", "BREEZE_API_SECRET": "s", "BREEZE_SESSION_TOKEN": "t"
    }):
        # Mock is_connected so we don't need a real Breeze session
        with patch("backend.main.is_connected", return_value=True):
            from backend.main import app
            client = TestClient(app)
            resp = client.get("/health")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "breeze_connected" in body
    assert isinstance(body["breeze_connected"], bool)
    print(f"\n  /health response: {body}")


# ---------------------------------------------------------------------------
# Test 4 — /quote/{symbol} with a mocked Breeze response
# ---------------------------------------------------------------------------

def test_quote_endpoint_offline():
    """/quote/RELIANCE returns CMP when Breeze is mocked."""
    mock_breeze_response = {
        "Status": 200,
        "Error": None,
        "Success": [{"last_traded_price": "2850.75"}],
    }

    with patch.dict("os.environ", {
        "BREEZE_API_KEY": "k", "BREEZE_API_SECRET": "s", "BREEZE_SESSION_TOKEN": "t"
    }):
        mock_session = MagicMock()
        mock_session.get_quotes.return_value = mock_breeze_response

        with patch("backend.breeze_client.get_session", return_value=mock_session):
            with patch("backend.data_fetcher.get_session", return_value=mock_session):
                from backend.main import app
                client = TestClient(app)
                resp = client.get("/quote/RELIANCE")

    assert resp.status_code == 200
    body = resp.json()
    assert body["symbol"] == "RELIANCE"
    assert body["cmp"] == 2850.75
    assert "timestamp" in body
    print(f"\n  /quote/RELIANCE response: {body}")


# ---------------------------------------------------------------------------
# Test 5 — /quote/{symbol} returns 404 for a bad symbol
# ---------------------------------------------------------------------------

def test_quote_endpoint_bad_symbol():
    """/quote/{bad_symbol} returns HTTP 404 when Breeze returns empty Success."""
    mock_breeze_response = {
        "Status": 200,
        "Error": None,
        "Success": [],  # empty — symbol not found
    }

    with patch.dict("os.environ", {
        "BREEZE_API_KEY": "k", "BREEZE_API_SECRET": "s", "BREEZE_SESSION_TOKEN": "t"
    }):
        mock_session = MagicMock()
        mock_session.get_quotes.return_value = mock_breeze_response

        with patch("backend.breeze_client.get_session", return_value=mock_session):
            with patch("backend.data_fetcher.get_session", return_value=mock_session):
                from backend.main import app
                client = TestClient(app)
                resp = client.get("/quote/NOTAREALSTOCK")

    assert resp.status_code == 404
    body = resp.json()
    assert "detail" in body
    print(f"\n  /quote/NOTAREALSTOCK correctly returned 404: {body['detail']}")


# ---------------------------------------------------------------------------
# Test 6 — get_cmp raises ValueError on malformed Breeze response
# ---------------------------------------------------------------------------

def test_get_cmp_invalid_response():
    """get_cmp raises ValueError when Breeze returns a non-200 status."""
    mock_breeze_response = {
        "Status": 400,
        "Error": "Invalid stock code",
        "Success": None,
    }

    with patch.dict("os.environ", {
        "BREEZE_API_KEY": "k", "BREEZE_API_SECRET": "s", "BREEZE_SESSION_TOKEN": "t"
    }):
        mock_session = MagicMock()
        mock_session.get_quotes.return_value = mock_breeze_response

        with patch("backend.data_fetcher.get_session", return_value=mock_session):
            from backend.data_fetcher import get_cmp

            with pytest.raises(ValueError, match="Breeze API error"):
                get_cmp("BADSYMBOL")

    print("\n  get_cmp correctly raised ValueError for bad Breeze response")


# ---------------------------------------------------------------------------
# Optional: live integration test (skipped unless --live flag passed)
# ---------------------------------------------------------------------------

@pytest.mark.skip(reason="Live test — only run manually with real credentials")
def test_live_cmp_mnm():
    """LIVE: Fetch CMP for M&M from real Breeze API.

    Run manually:
        pytest backend/tests/test_phase1.py::test_live_cmp_mnm -v -s

    Requires real .env file with valid credentials.
    """
    from backend.data_fetcher import get_cmp
    price = get_cmp("M&M")
    assert price > 0, f"Expected positive price, got {price}"
    print(f"\n  LIVE M&M CMP: ₹{price:.2f}")
