"""
pages/strangle.py — Short Strangle Strategy Analysis (Implicit Covered Call).

Analyse short strangle positions: sell OTM call + OTM put on same stock/expiry.
- Auto-suggest 4% OTM strikes or allow manual override
- Display P&L metrics, breakevens, margin requirements
- Show charges breakdown and risk warnings
- Track multiple strangles in session state (no database persistence)
"""

import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import requests
import streamlit as st

from auth import check_credentials, get_auth_headers
from nav import NAV_CSS, brand_header, nav_bar

BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000").rstrip("/")

# ── Page setup ────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Strangle — Breezy F&O",
    page_icon="🪢",
    layout="wide",
)

st.markdown(NAV_CSS, unsafe_allow_html=True)
check_credentials()
nav_bar("strangle")
brand_header(
    "🪢", "Short Strangle",
    subtitle="Implicit Covered Call: Sell OTM call + OTM put, collect premium on both legs.",
)

# ── Session state ─────────────────────────────────────────────────────────────

for key, default in [
    ("strangle_symbol", ""),
    ("strangle_expiry", ""),
    ("strangle_call_strike", 0.0),
    ("strangle_put_strike", 0.0),
    ("strangle_result", None),
    ("strangle_tracker", None),
]:
    if key not in st.session_state:
        st.session_state[key] = default

# ── Helpers ───────────────────────────────────────────────────────────────────


def _fmt_inr(v) -> str:
    """Format as INR currency."""
    if v is None or v == "":
        return "—"
    try:
        return f"₹{float(v):,.2f}"
    except (ValueError, TypeError):
        return str(v)


def _fmt_pct(v, decimals=2) -> str:
    """Format as percentage."""
    if v is None:
        return "—"
    try:
        return f"{float(v):.{decimals}f}%"
    except (ValueError, TypeError):
        return str(v)


def _fmt_int(v) -> str:
    """Format as integer."""
    if v is None:
        return "—"
    try:
        return f"{int(v):,}"
    except (ValueError, TypeError):
        return str(v)


@st.cache_data(ttl=300)
def _fetch_symbols() -> list[str]:
    """Fetch available F&O symbols from backend."""
    try:
        r = requests.get(f"{BACKEND_URL}/lot-sizes", headers=get_auth_headers(), timeout=5)
        r.raise_for_status()
        return sorted(r.json()["lot_sizes"].keys())
    except Exception as exc:
        st.error(f"Failed to fetch symbols: {exc}")
        return []


@st.cache_data(ttl=300)
def _fetch_expiries(symbol: str) -> list[str]:
    """Fetch available expiry dates for a symbol."""
    try:
        r = requests.get(
            f"{BACKEND_URL}/strangle/expiries/{symbol}",
            headers=get_auth_headers(),
            timeout=5,
        )
        r.raise_for_status()
        return r.json()["expiries"]
    except Exception as exc:
        st.error(f"Failed to fetch expiries for {symbol}: {exc}")
        return []


@st.cache_data(ttl=300)
def _fetch_option_chain(symbol: str, expiry: str) -> dict:
    """Fetch call and put option chains for a symbol/expiry."""
    try:
        r = requests.get(
            f"{BACKEND_URL}/strangle/option-chain/{symbol}",
            params={"expiry": expiry},
            headers=get_auth_headers(),
            timeout=15,
        )
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        st.error(f"Failed to fetch option chain for {symbol} {expiry}: {exc}")
        return {"calls": [], "puts": []}


def _auto_suggest_strikes(calls: list[dict], puts: list[dict], cmp: float) -> tuple[float, float]:
    """Auto-suggest call strike (4%+ OTM above CMP) and put strike (4%+ OTM below CMP)."""
    call_strike = None
    put_strike = None

    # Find nearest call strike at least 4% above CMP
    target_call = cmp * 1.04
    for call in calls:
        if call["strike_price"] >= target_call:
            call_strike = call["strike_price"]
            break

    # Find nearest put strike at least 4% below CMP
    target_put = cmp * 0.96
    for put in reversed(puts):
        if put["strike_price"] <= target_put:
            put_strike = put["strike_price"]
            break

    # Fallback: use closest strikes if 4% OTM not found
    if call_strike is None and calls:
        call_strike = calls[len(calls) // 2]["strike_price"]
    if put_strike is None and puts:
        put_strike = puts[len(puts) // 2]["strike_price"]

    return (call_strike or 0, put_strike or 0)


# ── Main UI ───────────────────────────────────────────────────────────────────

left, right = st.columns([1, 1.2], gap="medium")

with left:
    st.markdown('<div class="section-hd">📊 Setup Strangle</div>', unsafe_allow_html=True)

    # Symbol selection
    symbols = _fetch_symbols()
    symbol = st.selectbox(
        "Stock Symbol",
        symbols,
        key="strangle_symbol",
        help="Select an F&O symbol (e.g., BANKNIFTY, NIFTY, FINNIFTY)",
    )

    if symbol and st.session_state.strangle_symbol == symbol:
        # Fetch expiries and option chain
        expiries = _fetch_expiries(symbol)
        option_chain = _fetch_option_chain(symbol, expiries[0]) if expiries else {"calls": [], "puts": []}

        # Get CMP from first call contract (they all have same underlying price)
        cmp = None
        if option_chain.get("calls"):
            # CMP is approximated from available strikes; ideally from a separate quote endpoint
            # For now, use middle call strike as proxy
            calls = option_chain["calls"]
            cmp = (calls[0]["strike_price"] + calls[-1]["strike_price"]) / 2

        # Get lot size
        lot_size = 1
        try:
            r = requests.get(f"{BACKEND_URL}/lot-sizes", headers=get_auth_headers(), timeout=5)
            r.raise_for_status()
            lot_sizes_map = r.json()["lot_sizes"]
            lot_size = lot_sizes_map.get(symbol, 1)
        except Exception:
            lot_size = 1

        # Expiry selection
        if expiries:
            expiry = st.radio(
                "Expiry Date",
                expiries,
                key="strangle_expiry",
                format_func=lambda x: f"{x} ({(date.fromisoformat(x) - date.today()).days}d)",
                horizontal=True,
            )

            # Re-fetch chain if expiry changed
            if st.session_state.strangle_expiry == expiry:
                option_chain = _fetch_option_chain(symbol, expiry)

            # Display CMP and lot size
            st.divider()
            col_cmp, col_lot = st.columns(2)
            with col_cmp:
                st.metric("CMP (approx)", _fmt_inr(cmp), help="Approximate from option chain midpoint")
            with col_lot:
                st.metric("Lot Size", f"{lot_size} shares")
            st.divider()

            # Auto-suggest strikes
            st.markdown('<div class="section-hd">📌 Strike Selection</div>', unsafe_allow_html=True)
            calls = option_chain.get("calls", [])
            puts = option_chain.get("puts", [])

            if calls and puts and cmp:
                suggested_call, suggested_put = _auto_suggest_strikes(calls, puts, cmp)

                col_call, col_put = st.columns(2)
                with col_call:
                    call_strike = st.number_input(
                        "Call Strike (Sell)",
                        value=st.session_state.strangle_call_strike or suggested_call,
                        step=1.0,
                        key="strangle_call_strike",
                        help=f"4% OTM suggested: ₹{suggested_call:,.0f}",
                    )

                with col_put:
                    put_strike = st.number_input(
                        "Put Strike (Sell)",
                        value=st.session_state.strangle_put_strike or suggested_put,
                        step=1.0,
                        key="strangle_put_strike",
                        help=f"4% OTM suggested: ₹{suggested_put:,.0f}",
                    )

                # Reset to auto-suggested button
                if st.button("🔄 Reset to Auto-Suggested", use_container_width=True):
                    st.session_state.strangle_call_strike = suggested_call
                    st.session_state.strangle_put_strike = suggested_put
                    st.rerun()

                st.divider()

                # Analyse button
                if st.button("📊 Analyse", use_container_width=True, type="primary"):
                    with st.spinner("Analysing strangle position…"):
                        try:
                            # Find premiums for selected strikes
                            call_premium = None
                            for call in calls:
                                if call["strike_price"] == call_strike:
                                    call_premium = call["ltp"]
                                    break

                            put_premium = None
                            for put in puts:
                                if put["strike_price"] == put_strike:
                                    put_premium = put["ltp"]
                                    break

                            if call_premium is None:
                                st.error(
                                    f"Call strike ₹{call_strike:,.0f} not found. "
                                    f"Available: ₹{calls[0]['strike_price']:,.0f}–₹{calls[-1]['strike_price']:,.0f}"
                                )
                            elif put_premium is None:
                                st.error(
                                    f"Put strike ₹{put_strike:,.0f} not found. "
                                    f"Available: ₹{puts[0]['strike_price']:,.0f}–₹{puts[-1]['strike_price']:,.0f}"
                                )
                            else:
                                # Call backend analysis
                                r = requests.post(
                                    f"{BACKEND_URL}/strangle/analyse",
                                    json={
                                        "symbol": symbol,
                                        "expiry_date": expiry,
                                        "call_strike": call_strike,
                                        "put_strike": put_strike,
                                    },
                                    headers=get_auth_headers(),
                                    timeout=30,
                                )
                                r.raise_for_status()
                                result = r.json()
                                st.session_state.strangle_result = result
                                st.rerun()

                        except requests.HTTPError as exc:
                            detail = exc.response.json().get("detail", "")
                            st.error(f"Analysis failed {exc.response.status_code}: {detail or str(exc)}")
                        except Exception as exc:
                            st.error(f"Analysis failed: {exc}")

# Right column: Results
with right:
    result = st.session_state.strangle_result

    if result:
        st.markdown('<div class="section-hd">📊 Analysis Results</div>', unsafe_allow_html=True)

        # Analysis table
        analysis_data = [
            ("Stock", result["symbol"]),
            ("Lot Size", f"{result['lot_size']} shares"),
            ("Expiry", result["expiry_date"]),
            ("Days to Expiry", result["days_to_expiry"]),
            ("", ""),  # Divider
            ("Call Strike (Sell)", _fmt_inr(result["call_leg"]["strike"])),
            ("Put Strike (Sell)", _fmt_inr(result["put_leg"]["strike"])),
            ("", ""),
            ("CE Premium/share", _fmt_inr(result["call_leg"]["net_premium_per_share"])),
            ("PE Premium/share", _fmt_inr(result["put_leg"]["net_premium_per_share"])),
            ("Total Premium/share", _fmt_inr(result["total_premium_collected"])),
            ("Total Premium (1 lot)", _fmt_inr(result["total_premium_collected_total"])),
            ("", ""),
            ("Upper Breakeven", _fmt_inr(result["upper_breakeven"])),
            ("Lower Breakeven", _fmt_inr(result["lower_breakeven"])),
            ("Profit Zone Width", _fmt_inr(result["profit_zone_width"])),
            ("", ""),
            ("Max Profit", _fmt_inr(result["max_profit"])),
            ("Max Loss (upside)", result["max_loss_upside"]),
            ("Max Loss (downside)", _fmt_inr(result["max_loss_downside"])),
            ("", ""),
            ("Est. Margin Required", _fmt_inr(result["estimated_margin_required"])),
            ("ROI on Margin", _fmt_pct(result["roi_on_margin_pct"])),
        ]

        df_analysis = []
        for label, value in analysis_data:
            if label == "":
                continue
            df_analysis.append({"Metric": label, "Value": value})

        st.dataframe(
            df_analysis,
            use_container_width=True,
            hide_index=True,
            column_config={"Metric": st.column_config.TextColumn(width="medium")},
        )

        # Charges breakdown
        st.divider()
        with st.expander("💰 Charges Breakdown", expanded=False):
            col_ce, col_pe = st.columns(2)

            with col_ce:
                st.write("**Call Leg (CE)**")
                charges_ce = result["call_leg"]["charges"]
                st.write(
                    f"Gross Premium: {_fmt_inr(result['call_leg']['premium_total'])}\n"
                    f"STT: {_fmt_inr(charges_ce['stt'])}\n"
                    f"Brokerage: {_fmt_inr(charges_ce['brokerage'])}\n"
                    f"GST: {_fmt_inr(charges_ce['gst'])}\n"
                    f"**Total Charges: {_fmt_inr(charges_ce['total'])}**\n"
                    f"Net Premium: {_fmt_inr(result['call_leg']['net_premium_total'])}"
                )

            with col_pe:
                st.write("**Put Leg (PE)**")
                charges_pe = result["put_leg"]["charges"]
                st.write(
                    f"Gross Premium: {_fmt_inr(result['put_leg']['premium_total'])}\n"
                    f"STT: {_fmt_inr(charges_pe['stt'])}\n"
                    f"Brokerage: {_fmt_inr(charges_pe['brokerage'])}\n"
                    f"GST: {_fmt_inr(charges_pe['gst'])}\n"
                    f"**Total Charges: {_fmt_inr(charges_pe['total'])}**\n"
                    f"Net Premium: {_fmt_inr(result['put_leg']['net_premium_total'])}"
                )

        # Risk warnings
        st.divider()
        st.warning(
            f"""
**⚠️ Risk Warnings — Read Carefully**

• **Max loss on UPSIDE is UNLIMITED** if {result['symbol']} rallies above **₹{result['upper_breakeven']:,.0f}** (upper breakeven).

• **Max loss on DOWNSIDE is ₹{result['max_loss_downside']:,.0f}** if {result['symbol']} crashes to zero (put strike ₹{result['put_leg']['strike']:,.0f} − net premium).

• **Estimated margin required: ₹{result['estimated_margin_required']:,.0f}** — verify with your broker's margin calculator before trading.

• Exit either leg immediately if its premium DOUBLES from your sold price.

• **DO NOT hold this position through earnings or RBI policy announcements.**

• This analysis is for educational purposes only — NOT investment advice.
            """
        )

        # Position tracker
        st.divider()
        st.markdown('<div class="section-hd">💾 My Open Strangles</div>', unsafe_allow_html=True)

        if st.button("💾 Save Current Position", use_container_width=True):
            st.session_state.strangle_tracker = {
                "symbol": result["symbol"],
                "expiry": result["expiry_date"],
                "call_strike": result["call_leg"]["strike"],
                "ce_premium": result["call_leg"]["net_premium_per_share"],
                "put_strike": result["put_leg"]["strike"],
                "pe_premium": result["put_leg"]["net_premium_per_share"],
                "total_premium": result["total_premium_collected"],
                "entry_date": str(date.today()),
                "status": "Open",
            }
            st.success("✓ Position saved to tracker!")

        if st.session_state.strangle_tracker:
            tracker = st.session_state.strangle_tracker
            tracker_df = [
                {
                    "Symbol": tracker["symbol"],
                    "Expiry": tracker["expiry"],
                    "Call Strike": _fmt_inr(tracker["call_strike"]),
                    "CE Premium": _fmt_inr(tracker["ce_premium"]),
                    "Put Strike": _fmt_inr(tracker["put_strike"]),
                    "PE Premium": _fmt_inr(tracker["pe_premium"]),
                    "Total Premium": _fmt_inr(tracker["total_premium"]),
                    "Entry Date": tracker["entry_date"],
                    "Status": tracker["status"],
                }
            ]

            st.dataframe(tracker_df, use_container_width=True, hide_index=True)

            col_clear = st.columns([1, 4])
            with col_clear[0]:
                if st.button("🗑️ Clear", use_container_width=True):
                    st.session_state.strangle_tracker = None
                    st.rerun()
        else:
            st.info("No positions saved yet. Run an analysis and click 'Save Current Position' to track it.")
    else:
        st.info("👈 Select a symbol, expiry, and strikes on the left, then click 'Analyse' to see results here.")
