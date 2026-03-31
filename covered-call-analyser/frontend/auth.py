"""
auth.py — Per-user Breeze credentials login gate.

Usage in every page (after st.set_page_config):
    from auth import check_credentials, get_auth_headers
    check_credentials()

Then on every requests call:
    r = requests.get(url, headers=get_auth_headers(), timeout=10)
"""

import os

import requests as _requests
import streamlit as st

from nav import NAV_CSS, brand_header

BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000").rstrip("/")


def get_auth_headers() -> dict[str, str]:
    """Return Breeze credential headers to attach to every backend request."""
    creds = st.session_state.get("breeze_creds") or {}
    return {
        "X-Breeze-Api-Key":       creds.get("api_key", ""),
        "X-Breeze-Api-Secret":    creds.get("api_secret", ""),
        "X-Breeze-Session-Token": creds.get("session_token", ""),
    }


def logout() -> None:
    """Clear credentials and cached data, return user to login screen."""
    st.session_state.pop("breeze_creds", None)
    st.cache_data.clear()
    st.rerun()


def check_credentials() -> None:
    """If no Breeze credentials in session, show the login form and stop the page.

    Call this immediately after st.set_page_config() on every page.
    Returns normally when credentials are already stored.
    """
    if st.session_state.get("breeze_creds"):
        return

    # ── render login screen ────────────────────────────────────────────────────
    st.markdown(NAV_CSS, unsafe_allow_html=True)
    brand_header()

    st.markdown(
        '<p style="color:#8B949E;font-size:14px;margin-bottom:24px;">'
        "Connect your ICICI Breeze account to get started.</p>",
        unsafe_allow_html=True,
    )

    with st.expander("How to get your daily session token"):
        st.markdown(
            """
            1. Open this URL in your browser (replace `YOUR_API_KEY`):
               ```
               https://api.icicidirect.com/apiuser/login?api_key=YOUR_API_KEY
               ```
            2. Log in with your ICICI Direct credentials + TOTP (Google Authenticator).
            3. After login you are redirected to a blank page — copy the `apisession=` value from the URL.
            4. Paste it in the **Session Token** field below.

            > The session token expires daily. Repeat this step each morning.
            """
        )

    with st.form("breeze_login_form"):
        api_key    = st.text_input("API Key",     placeholder="Your Breeze API key")
        api_secret = st.text_input("API Secret",  placeholder="Your Breeze API secret",  type="password")
        token      = st.text_input("Session Token", placeholder="Today's session token", type="password")
        submitted  = st.form_submit_button("Connect to Breeze", use_container_width=True)

    if submitted:
        api_key    = api_key.strip()
        api_secret = api_secret.strip()
        token      = token.strip()

        if not (api_key and api_secret and token):
            st.error("All three fields are required.")
        else:
            with st.spinner("Validating credentials with Breeze…"):
                try:
                    r = _requests.post(
                        f"{BACKEND_URL}/validate-session",
                        json={
                            "api_key":       api_key,
                            "api_secret":    api_secret,
                            "session_token": token,
                        },
                        timeout=20,
                    )
                    if r.status_code == 200:
                        st.session_state.breeze_creds = {
                            "api_key":       api_key,
                            "api_secret":    api_secret,
                            "session_token": token,
                        }
                        st.rerun()
                    else:
                        detail = r.json().get("detail", r.text) if r.content else r.reason
                        st.error(f"Authentication failed: {detail}")
                except _requests.exceptions.ConnectionError:
                    st.error("Cannot reach the backend. Check that the service is running.")
                except Exception as exc:
                    st.error(f"Login error: {exc}")

    st.stop()
