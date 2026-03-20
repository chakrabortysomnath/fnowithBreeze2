"""
auth.py — Breeze session login gate.

Every page calls check_auth() immediately after st.set_page_config().
If the user has not yet provided a valid Breeze session token for this
browser session, a full-screen login form is shown and st.stop() is called
so the rest of the page never renders.

How to get a daily session token:
    1. Visit https://api.icicidirect.com/apiuser/login?api_key=<YOUR_API_KEY>
    2. Log in with your ICICI Direct credentials + TOTP (Google Authenticator)
    3. Copy the `apisession=` value from the redirect URL
    4. Paste it into the login form below
"""

import os

import requests
import streamlit as st

BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000").rstrip("/")

_LOGIN_CSS = """
<style>
/* Centre the login card on the page */
.login-wrap {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: flex-start;
    padding-top: 8vh;
}
.login-card {
    background: #161B22;
    border: 1px solid #30363D;
    border-radius: 12px;
    padding: 40px 44px 36px;
    max-width: 480px;
    width: 100%;
}
.login-logo {
    font-size: 48px;
    text-align: center;
    margin-bottom: 8px;
}
.login-title {
    font-size: 26px;
    font-weight: 800;
    color: #58A6FF;
    text-align: center;
    letter-spacing: -0.5px;
    margin-bottom: 4px;
    font-family: 'Segoe UI', Inter, sans-serif;
}
.login-sub {
    font-size: 13px;
    color: #8B949E;
    text-align: center;
    margin-bottom: 28px;
}
</style>
"""


def check_auth() -> None:
    """Show login gate if Breeze session not yet established; otherwise return immediately."""
    if st.session_state.get("breeze_ok"):
        return

    # ── Full-screen login UI ────────────────────────────────────────────────
    st.markdown(_LOGIN_CSS, unsafe_allow_html=True)

    st.markdown("""
    <div class="login-wrap">
      <div class="login-card">
        <div class="login-logo">📈</div>
        <div class="login-title">Breezy F&amp;O</div>
        <div class="login-sub">Covered Call Strategy Analyser</div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("### Connect to Breeze")
    st.markdown(
        "Enter your **daily ICICI Breeze session token** to start the session. "
        "The token expires at midnight and must be refreshed each morning."
    )

    with st.expander("How to get your session token"):
        st.markdown("""
1. Open your ICICI Direct Breeze login URL in a browser:
   `https://api.icicidirect.com/apiuser/login?api_key=<YOUR_API_KEY>`
2. Log in with your ICICI Direct credentials and complete the TOTP step.
3. After successful login you are redirected to a URL that contains:
   `?apisession=<TOKEN>&...`
4. Copy the value of `apisession=` (everything between `=` and the next `&`)
   and paste it into the field below.
        """)

    with st.form("breeze_login_form", clear_on_submit=False):
        token = st.text_input(
            "Session Token",
            type="password",
            placeholder="Paste your apisession token here…",
            help="Obtained from the ICICI Direct Breeze redirect URL after login.",
        )
        submitted = st.form_submit_button("Connect to Breeze", use_container_width=True)

    if submitted:
        if not token.strip():
            st.error("Session token cannot be empty.")
        else:
            with st.spinner("Validating session with Breeze API…"):
                try:
                    resp = requests.post(
                        f"{BACKEND_URL}/refresh-session",
                        json={"session_token": token.strip()},
                        timeout=20,
                    )
                    if resp.status_code == 200:
                        st.session_state.breeze_ok = True
                        st.success("Connected! Redirecting…")
                        st.rerun()
                    else:
                        try:
                            detail = resp.json().get("detail", resp.text)
                        except Exception:
                            detail = resp.text
                        st.error(
                            f"**Breeze rejected the session token** (HTTP {resp.status_code}).\n\n"
                            f"{detail}\n\n"
                            "Please generate a fresh token and try again."
                        )
                except requests.exceptions.ConnectionError:
                    st.error(
                        "Cannot reach the backend service. "
                        "Check that the backend is running and `BACKEND_URL` is set correctly."
                    )
                except requests.exceptions.Timeout:
                    st.error(
                        "The backend did not respond in time. "
                        "The Breeze API may be slow — please try again."
                    )
                except Exception as exc:
                    st.error(f"Unexpected error during login: {exc}")

    st.stop()
