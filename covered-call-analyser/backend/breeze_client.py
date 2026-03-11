"""
breeze_client.py — ICICI Breeze API session management.

Provides a singleton authenticated BreezeConnect session.
The session is created once at startup and reused for all requests.

Session Token Note:
    Breeze session tokens expire daily. You must generate a fresh token
    each morning via the ICICI Direct login/TOTP flow and either:
      a) Restart the Render service with the new BREEZE_SESSION_TOKEN env var, OR
      b) Call POST /refresh-session (added in Phase 5) with the new token.
"""

import logging
import sys
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


def _initialise_session() -> BreezeConnect:
    """Create and authenticate a new BreezeConnect session.

    Uses credentials from config.py (read from environment variables).

    Returns:
        An authenticated BreezeConnect instance.

    Raises:
        RuntimeError: Wraps any exception raised during auth, with a helpful message.
    """
    logger.info("Initialising Breeze API session...")

    try:
        breeze = BreezeConnect(api_key=settings.BREEZE_API_KEY)

        # generate_session authenticates using the API secret and the daily
        # session token obtained from the ICICI Direct login flow.
        breeze.generate_session(
            api_secret=settings.BREEZE_API_SECRET,
            session_token=settings.BREEZE_SESSION_TOKEN,
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

    Called by the POST /refresh-session endpoint (Phase 5).
    Use this each morning after generating a new token via the ICICI Direct flow.

    Args:
        new_session_token: Fresh session token from today's ICICI Direct login.

    Returns:
        The new authenticated BreezeConnect session.
    """
    global _session

    logger.info("Refreshing Breeze session with new token...")

    # Temporarily override the setting in-memory (does not write to .env)
    settings.__dict__["BREEZE_SESSION_TOKEN"] = new_session_token

    _session = None  # force re-initialisation on next get_session() call
    return get_session()


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
