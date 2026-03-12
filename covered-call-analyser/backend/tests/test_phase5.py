"""
test_phase5.py — Phase 5 unit tests: session refresh and proxy configuration.

Tests cover:
  - POST /refresh-session happy path
  - POST /refresh-session error paths (empty token, bad auth)
  - refresh_session() invalidates the old singleton and builds a new one
  - _configure_proxy() sets / clears HTTP_PROXY and HTTPS_PROXY env vars
  - is_connected() returns False when session initialisation fails

Run:
    cd covered-call-analyser
    pytest backend/tests/test_phase5.py -v
"""

import os
import pytest
from unittest.mock import patch, MagicMock, call
from fastapi.testclient import TestClient


ENV = {
    "BREEZE_API_KEY":      "test_key",
    "BREEZE_API_SECRET":   "test_secret",
    "BREEZE_SESSION_TOKEN":"test_token",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_breeze() -> MagicMock:
    """Return a MagicMock that looks like an authenticated BreezeConnect."""
    mock = MagicMock()
    mock.generate_session.return_value = None   # succeeds silently
    return mock


def _client_with_mock(mock_breeze: MagicMock) -> TestClient:
    """Return a TestClient with BreezeConnect fully mocked."""
    with patch.dict("os.environ", ENV):
        with patch("backend.breeze_client.BreezeConnect", return_value=mock_breeze):
            from backend.main import app
            return TestClient(app)


# ---------------------------------------------------------------------------
# _configure_proxy — unit tests (no HTTP calls)
# ---------------------------------------------------------------------------

def test_configure_proxy_sets_env_when_url_present():
    """_configure_proxy sets HTTP_PROXY and HTTPS_PROXY when QUOTAGUARDSTATIC_URL is set."""
    proxy_url = "http://user:pass@proxy.quotaguard.com:9293"
    with patch.dict("os.environ", {**ENV, "QUOTAGUARDSTATIC_URL": proxy_url}, clear=False):
        # Re-import settings with the new env var
        with patch("backend.breeze_client.settings") as mock_settings:
            mock_settings.QUOTAGUARDSTATIC_URL = proxy_url
            mock_settings.BREEZE_API_KEY      = "k"
            mock_settings.BREEZE_API_SECRET   = "s"
            mock_settings.BREEZE_SESSION_TOKEN = "t"

            from backend.breeze_client import _configure_proxy
            _configure_proxy()

            assert os.environ.get("HTTP_PROXY")  == proxy_url
            assert os.environ.get("HTTPS_PROXY") == proxy_url

    # Clean up so other tests aren't affected
    os.environ.pop("HTTP_PROXY",  None)
    os.environ.pop("HTTPS_PROXY", None)


def test_configure_proxy_clears_env_when_url_absent():
    """_configure_proxy removes proxy env vars when QUOTAGUARDSTATIC_URL is None."""
    os.environ["HTTP_PROXY"]  = "http://stale-proxy.example.com"
    os.environ["HTTPS_PROXY"] = "http://stale-proxy.example.com"

    with patch("backend.breeze_client.settings") as mock_settings:
        mock_settings.QUOTAGUARDSTATIC_URL = None
        mock_settings.BREEZE_API_KEY       = "k"
        mock_settings.BREEZE_API_SECRET    = "s"
        mock_settings.BREEZE_SESSION_TOKEN = "t"

        from backend.breeze_client import _configure_proxy
        _configure_proxy()

        assert "HTTP_PROXY"  not in os.environ
        assert "HTTPS_PROXY" not in os.environ


# ---------------------------------------------------------------------------
# refresh_session() — unit tests
# ---------------------------------------------------------------------------

def test_refresh_session_replaces_singleton():
    """refresh_session() creates a new session object (different from the old one)."""
    mock1 = _make_mock_breeze()
    mock2 = _make_mock_breeze()
    call_count = {"n": 0}

    def _side_effect(api_key):
        call_count["n"] += 1
        return mock1 if call_count["n"] == 1 else mock2

    with patch.dict("os.environ", ENV):
        with patch("backend.breeze_client.BreezeConnect", side_effect=_side_effect):
            import backend.breeze_client as bc
            bc._session = None   # reset singleton

            # First call — initialises with original token
            session1 = bc.get_session()

            # Refresh — should build a brand-new BreezeConnect
            session2 = bc.refresh_session("new_daily_token_xyz")

            assert session1 is not session2, "Expected a new session object after refresh"
            assert bc._session is session2


def test_refresh_session_passes_new_token():
    """refresh_session() passes the new token to generate_session, not the old one."""
    mock_breeze = _make_mock_breeze()

    with patch.dict("os.environ", ENV):
        with patch("backend.breeze_client.BreezeConnect", return_value=mock_breeze):
            import backend.breeze_client as bc
            bc._session = None

            bc.refresh_session("FRESH_TOKEN_2026")

            # generate_session must have been called with the new token
            calls = mock_breeze.generate_session.call_args_list
            last_call_kwargs = calls[-1].kwargs if calls[-1].kwargs else {}
            last_call_args   = calls[-1].args   if calls[-1].args   else ()
            token_used = last_call_kwargs.get("session_token") or (
                last_call_args[1] if len(last_call_args) > 1 else None
            )
            assert token_used == "FRESH_TOKEN_2026", (
                f"Expected token 'FRESH_TOKEN_2026', got {token_used!r}"
            )


def test_refresh_session_raises_on_empty_token():
    """refresh_session() raises ValueError for an empty token."""
    with patch.dict("os.environ", ENV):
        import backend.breeze_client as bc
        bc._session = None

        with pytest.raises(ValueError, match="empty"):
            bc.refresh_session("")

        with pytest.raises(ValueError, match="empty"):
            bc.refresh_session("   ")


def test_refresh_session_raises_runtime_on_bad_auth():
    """refresh_session() raises RuntimeError when BreezeConnect.generate_session fails."""
    mock_breeze = MagicMock()
    mock_breeze.generate_session.side_effect = Exception("Invalid session token")

    with patch.dict("os.environ", ENV):
        with patch("backend.breeze_client.BreezeConnect", return_value=mock_breeze):
            import backend.breeze_client as bc
            bc._session = None

            with pytest.raises(RuntimeError, match="Breeze session initialisation failed"):
                bc.refresh_session("BAD_TOKEN")


# ---------------------------------------------------------------------------
# POST /refresh-session endpoint
# ---------------------------------------------------------------------------

def test_refresh_session_endpoint_happy_path():
    """POST /refresh-session returns 200 with status=ok on valid token."""
    mock_breeze = _make_mock_breeze()

    with patch.dict("os.environ", ENV):
        with patch("backend.breeze_client.BreezeConnect", return_value=mock_breeze):
            import backend.breeze_client as bc
            bc._session = None
            from backend.main import app
            client = TestClient(app)

            resp = client.post(
                "/refresh-session",
                json={"session_token": "VALID_TOKEN_TODAY"},
            )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"]  == "ok"
    assert "refreshed"     in body["message"].lower()
    assert "timestamp"     in body
    # ISO 8601 UTC format
    assert body["timestamp"].endswith("Z")


def test_refresh_session_endpoint_empty_token_returns_400():
    """POST /refresh-session returns 400 when session_token is empty string."""
    with patch.dict("os.environ", ENV):
        with patch("backend.breeze_client.BreezeConnect"):
            import backend.breeze_client as bc
            bc._session = None
            from backend.main import app
            client = TestClient(app)

            resp = client.post(
                "/refresh-session",
                json={"session_token": ""},
            )

    assert resp.status_code == 400
    assert "empty" in resp.json()["detail"].lower()


def test_refresh_session_endpoint_bad_auth_returns_503():
    """POST /refresh-session returns 503 when Breeze rejects the token."""
    mock_breeze = MagicMock()
    mock_breeze.generate_session.side_effect = Exception("Token expired")

    with patch.dict("os.environ", ENV):
        with patch("backend.breeze_client.BreezeConnect", return_value=mock_breeze):
            import backend.breeze_client as bc
            bc._session = None
            from backend.main import app
            client = TestClient(app)

            resp = client.post(
                "/refresh-session",
                json={"session_token": "EXPIRED_TOKEN"},
            )

    assert resp.status_code == 503
    assert "token" in resp.json()["detail"].lower()


def test_refresh_session_endpoint_missing_body_returns_422():
    """POST /refresh-session returns 422 when session_token field is absent."""
    with patch.dict("os.environ", ENV):
        with patch("backend.breeze_client.BreezeConnect"):
            import backend.breeze_client as bc
            bc._session = None
            from backend.main import app
            client = TestClient(app)

            resp = client.post("/refresh-session", json={})

    assert resp.status_code == 422   # Pydantic validation error


# ---------------------------------------------------------------------------
# is_connected() after a failed refresh
# ---------------------------------------------------------------------------

def test_is_connected_false_after_failed_refresh():
    """is_connected() returns False if the session was cleared by a failed refresh."""
    mock_breeze = MagicMock()
    mock_breeze.generate_session.side_effect = Exception("auth failed")

    with patch.dict("os.environ", ENV):
        with patch("backend.breeze_client.BreezeConnect", return_value=mock_breeze):
            import backend.breeze_client as bc
            bc._session = None

            try:
                bc.refresh_session("BAD")
            except Exception:
                pass

            # After a failed refresh _session is None → is_connected must return False
            assert bc.is_connected() is False
