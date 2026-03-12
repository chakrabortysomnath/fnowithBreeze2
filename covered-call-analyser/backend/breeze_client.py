"""
breeze_client.py — ICICI Breeze API session management.

Provides a singleton authenticated BreezeConnect session.
The session is created once at startup and reused for all requests.

Session Token Note:
    Breeze session tokens expire daily. You must generate a fresh token
    each morning via the ICICI Direct login/TOTP flow and either:
      a) Restart the Render service with the new BREEZE_SESSION_TOKEN env var, OR
      b) Call POST /refresh-session (Phase 5) with the new token — no redeploy needed.

Static IP Proxy (Phase 5):
    ICICI Breeze may require a whitelisted outbound IP. Render's free tier uses
    dynamic IPs, so set QUOTAGUARDSTATIC_URL to a QuotaGuard Static proxy URL.
    All Breeze API calls will be routed through that proxy automatically.
"""

import logging
import os
from typing import Optional

from breeze_connect import BreezeConnect

from .config import settings

logger = logging.getLogger(__name__)

# Module-level singleton — one session shared across all requests
_session: Optional[BreezeConnect] = None


def get_session() -> BreezeConnect:
    """Return the active Breeze session, creating it if not yet initialised.

    Raises:
        RuntimeError: If the session cannot be created (bad credentials, network error, etc.)
    """
    global _session
    if _session is None:
        _session = _initialise_session()
    return _session


def _configure_proxy() -> None:
    """Set HTTP/HTTPS proxy environment variables from QUOTAGUARDSTATIC_URL.

    When QUOTAGUARDSTATIC_URL is configured, all outbound requests made by
    the breeze_connect library (which uses `requests` internally) are routed
    through that proxy. This provides a static outbound IP that can be
    whitelisted on the ICICI Breeze developer portal.

    Calling this repeatedly is safe — it simply overwrites the env vars.
    """
    proxy_url = settings.QUOTAGUARDSTATIC_URL
    if proxy_url:
        os.environ["HTTP_PROXY"]  = proxy_url
        os.environ["HTTPS_PROXY"] = proxy_url
        logger.info(
            "QuotaGuard Static proxy configured — outbound requests will use "
            f"{proxy_url[:proxy_url.index('@') + 1]}***"  # log host, mask credentials
            if "@" in proxy_url else f"proxy: {proxy_url}"
        )
    else:
        # Remove any stale proxy vars so a server restart without the setting
        # doesn't accidentally keep routing through an old proxy.
        os.environ.pop("HTTP_PROXY",  None)
        os.environ.pop("HTTPS_PROXY", None)


def _initialise_session(session_token_override: Optional[str] = None) -> BreezeConnect:
    """Create and authenticate a new BreezeConnect session.

    Args:
        session_token_override: If provided, use this token instead of the
            one stored in settings. Used by refresh_session() to hot-swap
            the token without restarting the server.

    Returns:
        An authenticated BreezeConnect instance.

    Raises:
        RuntimeError: Wraps any exception raised during auth, with a helpful message.
    """
    _configure_proxy()

    token = session_token_override or settings.BREEZE_SESSION_TOKEN
    logger.info("Initialising Breeze API session%s…",
                " (token override)" if session_token_override else "")

    try:
        breeze = BreezeConnect(api_key=settings.BREEZE_API_KEY)
        breeze.generate_session(
            api_secret=settings.BREEZE_API_SECRET,
            session_token=token,
        )
        logger.info("Breeze API session initialised successfully.")
        return breeze

    except Exception as exc:
        logger.error(
            "Failed to initialise Breeze session. "
            "Check that BREEZE_API_KEY, BREEZE_API_SECRET, and BREEZE_SESSION_TOKEN "
            "are set correctly and that the session token was generated today.\n"
            f"Error: {exc}"
        )
        raise RuntimeError(
            f"Breeze session initialisation failed: {exc}"
        ) from exc


def refresh_session(new_session_token: str) -> BreezeConnect:
    """Replace the current session with a new one using a fresh session token.

    Called by POST /refresh-session each morning after generating a new token
    via the ICICI Direct login/TOTP flow. Does not require a server restart.

    Args:
        new_session_token: Fresh session token from today's ICICI Direct login.

    Returns:
        The new authenticated BreezeConnect session.

    Raises:
        ValueError: If new_session_token is empty.
        RuntimeError: If the new session cannot be authenticated.
    """
    if not new_session_token or not new_session_token.strip():
        raise ValueError("new_session_token must not be empty.")

    global _session
    logger.info("Refreshing Breeze session with new token…")

    # Reset singleton so _initialise_session builds a fresh connection.
    # We do this before the new session is ready so that any concurrent
    # requests that call get_session() while we refresh will trigger a
    # new build rather than using the stale/expired session.
    _session = None
    new_session = _initialise_session(session_token_override=new_session_token.strip())
    _session = new_session
    logger.info("Breeze session refreshed successfully.")
    return _session


def is_connected() -> bool:
    """Return True if a Breeze session exists and appears healthy.

    This is a lightweight check — it does not make an API call.
    For a real connectivity check, call get_cmp() with a known symbol.
    """
    try:
        sess = get_session()
        return sess is not None
    except Exception:
        return False
