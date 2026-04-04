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
import plotly.graph_objects as go

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
    ("strangle_symbol",      ""),
    ("strangle_expiry",      ""),
    ("strangle_result",      None),
    ("strangle_tracker",     None),
    # Chip-picker state
    ("selected_ce_strike",   None),
    ("selected_pe_strike",   None),
    ("ce_premium",           None),
    ("pe_premium",           None),
    ("ce_manual_override",   False),
    ("pe_manual_override",   False),
    # Change-detection sentinels
    ("_strangle_prev_sym",   ""),
    ("_strangle_prev_exp",   ""),
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


def _get_contract(chain: list[dict], strike: float) -> dict | None:
    """Return the option contract whose strike_price matches, or None."""
    for c in chain:
        if c["strike_price"] == strike:
            return c
    return None


def _get_ce_chips(calls: list[dict], cmp: float) -> tuple[list[float], float, float]:
    """Return (enabled_strikes, atm_strike, suggested_4pct_strike) for the CE chip row.

    Shows ATM + up to 7 strikes above, but only those strictly above CMP.
    suggested_4pct is the nearest strike >= 4% above CMP.
    """
    if not calls:
        return [], 0.0, 0.0

    # ATM = closest strike to CMP
    atm_idx = min(range(len(calls)), key=lambda i: abs(calls[i]["strike_price"] - cmp))
    atm_strike = calls[atm_idx]["strike_price"]

    # 8 strikes starting at ATM (ATM + 7 above)
    window = calls[atm_idx : atm_idx + 8]

    # Only enable strikes strictly above CMP
    enabled = [c["strike_price"] for c in window if c["strike_price"] > cmp]

    # Auto-suggest: first strike >= 4% above CMP
    target = cmp * 1.04
    suggested = next((s for s in enabled if s >= target), enabled[0] if enabled else 0.0)

    return enabled, atm_strike, suggested


def _get_pe_chips(puts: list[dict], cmp: float) -> tuple[list[float], float, float]:
    """Return (enabled_strikes, atm_strike, suggested_4pct_strike) for the PE chip row.

    Shows ATM + up to 7 strikes below (descending), only those strictly below CMP.
    suggested_4pct is the nearest strike <= 4% below CMP.
    """
    if not puts:
        return [], 0.0, 0.0

    # ATM = closest strike to CMP
    atm_idx = min(range(len(puts)), key=lambda i: abs(puts[i]["strike_price"] - cmp))
    atm_strike = puts[atm_idx]["strike_price"]

    # 8 strikes from ATM downward (inclusive of ATM)
    start = max(0, atm_idx - 7)
    window = puts[start : atm_idx + 1]

    # Only enable strikes strictly below CMP, displayed high→low
    enabled = [c["strike_price"] for c in reversed(window) if c["strike_price"] < cmp]

    # Auto-suggest: nearest strike <= 4% below CMP
    target = cmp * 0.96
    suggested = next((s for s in enabled if s <= target), enabled[0] if enabled else 0.0)

    return enabled, atm_strike, suggested


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

            calls = option_chain.get("calls", [])
            puts  = option_chain.get("puts",  [])

            # ── Change-detection: reset all strike state on new symbol/expiry ──
            if (st.session_state._strangle_prev_sym != symbol
                    or st.session_state._strangle_prev_exp != expiry):
                for _k in ("selected_ce_strike", "selected_pe_strike",
                           "ce_premium", "pe_premium", "strangle_result"):
                    st.session_state[_k] = None
                st.session_state.ce_manual_override = False
                st.session_state.pe_manual_override = False
                st.session_state._strangle_prev_sym = symbol
                st.session_state._strangle_prev_exp = expiry

            if calls and puts and cmp:
                ce_strikes, atm_call, suggested_ce = _get_ce_chips(calls, cmp)
                pe_strikes, atm_put,  suggested_pe = _get_pe_chips(puts,  cmp)

                # ── Auto-init on first load ──────────────────────────────────
                if st.session_state.selected_ce_strike not in ce_strikes:
                    st.session_state.selected_ce_strike = suggested_ce
                    st.session_state.ce_premium = (_get_contract(calls, suggested_ce) or {}).get("ltp")
                    st.session_state.ce_manual_override = False

                if st.session_state.selected_pe_strike not in pe_strikes:
                    st.session_state.selected_pe_strike = suggested_pe
                    st.session_state.pe_premium = (_get_contract(puts, suggested_pe) or {}).get("ltp")
                    st.session_state.pe_manual_override = False

                # ── CE chip row ──────────────────────────────────────────────
                st.markdown('<div class="section-hd">📌 Strike Selection</div>',
                            unsafe_allow_html=True)
                st.markdown("**🟢 CALL (CE) — strike to sell**")

                ce_default = (st.session_state.selected_ce_strike
                              if not st.session_state.ce_manual_override else None)
                ce_sel = st.pills(
                    "CE Strike",
                    ce_strikes,
                    default=ce_default,
                    format_func=lambda s: (
                        f"ATM · {s:,.0f}" if s == atm_call else f"{s:,.0f}"
                    ),
                    key="ce_pills_widget",
                    label_visibility="collapsed",
                )
                if ce_sel is not None and ce_sel != st.session_state.selected_ce_strike:
                    st.session_state.selected_ce_strike = ce_sel
                    st.session_state.ce_premium = (_get_contract(calls, ce_sel) or {}).get("ltp")
                    st.session_state.ce_manual_override = False
                    st.rerun()

                # CE summary card
                if st.session_state.selected_ce_strike:
                    _ce = st.session_state.selected_ce_strike
                    _ce_c = _get_contract(calls, _ce)
                    _dist_ce = (_ce - cmp) / cmp * 100
                    _sfx = " (manual)" if st.session_state.ce_manual_override else ""
                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric("CE Strike", f"₹{_ce:,.0f}{_sfx}")
                    c2.metric("LTP", _fmt_inr(_ce_c["ltp"]) if _ce_c else "—")
                    c3.metric("OI", _fmt_int(_ce_c.get("open_interest")) if _ce_c else "—")
                    c4.metric("From CMP", f"+{_dist_ce:.1f}%")

                # CE manual override
                with st.expander("✏️ Enter CE strike manually"):
                    _ce_man_val = float(st.session_state.selected_ce_strike or 0)
                    _ce_man = st.number_input(
                        "CE Strike (manual)", value=_ce_man_val, step=50.0,
                        key="ce_manual_input",
                    )
                    if _ce_man > 0:
                        if _ce_man <= cmp:
                            st.error(f"CE strike must be above CMP (₹{cmp:,.0f})")
                        else:
                            if not _get_contract(calls, _ce_man):
                                st.warning("Strike not in option chain snapshot — analysis will still proceed")
                            if st.button("Apply CE Strike", key="apply_ce"):
                                st.session_state.selected_ce_strike = _ce_man
                                _c = _get_contract(calls, _ce_man)
                                st.session_state.ce_premium = _c["ltp"] if _c else None
                                st.session_state.ce_manual_override = True
                                st.rerun()

                st.divider()

                # ── PE chip row ──────────────────────────────────────────────
                st.markdown("**🔴 PUT (PE) — strike to sell**")

                pe_default = (st.session_state.selected_pe_strike
                              if not st.session_state.pe_manual_override else None)
                pe_sel = st.pills(
                    "PE Strike",
                    pe_strikes,
                    default=pe_default,
                    format_func=lambda s: (
                        f"ATM · {s:,.0f}" if s == atm_put else f"{s:,.0f}"
                    ),
                    key="pe_pills_widget",
                    label_visibility="collapsed",
                )
                if pe_sel is not None and pe_sel != st.session_state.selected_pe_strike:
                    st.session_state.selected_pe_strike = pe_sel
                    st.session_state.pe_premium = (_get_contract(puts, pe_sel) or {}).get("ltp")
                    st.session_state.pe_manual_override = False
                    st.rerun()

                # PE summary card
                if st.session_state.selected_pe_strike:
                    _pe = st.session_state.selected_pe_strike
                    _pe_c = _get_contract(puts, _pe)
                    _dist_pe = (_pe - cmp) / cmp * 100
                    _sfx_pe = " (manual)" if st.session_state.pe_manual_override else ""
                    p1, p2, p3, p4 = st.columns(4)
                    p1.metric("PE Strike", f"₹{_pe:,.0f}{_sfx_pe}")
                    p2.metric("LTP", _fmt_inr(_pe_c["ltp"]) if _pe_c else "—")
                    p3.metric("OI", _fmt_int(_pe_c.get("open_interest")) if _pe_c else "—")
                    p4.metric("From CMP", f"{_dist_pe:.1f}%")

                # PE manual override
                with st.expander("✏️ Enter PE strike manually"):
                    _pe_man_val = float(st.session_state.selected_pe_strike or 0)
                    _pe_man = st.number_input(
                        "PE Strike (manual)", value=_pe_man_val, step=50.0,
                        key="pe_manual_input",
                    )
                    if _pe_man > 0:
                        if _pe_man >= cmp:
                            st.error(f"PE strike must be below CMP (₹{cmp:,.0f})")
                        else:
                            if not _get_contract(puts, _pe_man):
                                st.warning("Strike not in option chain snapshot — analysis will still proceed")
                            if st.button("Apply PE Strike", key="apply_pe"):
                                st.session_state.selected_pe_strike = _pe_man
                                _p = _get_contract(puts, _pe_man)
                                st.session_state.pe_premium = _p["ltp"] if _p else None
                                st.session_state.pe_manual_override = True
                                st.rerun()

                # ── Summary bar ──────────────────────────────────────────────
                _sce  = st.session_state.selected_ce_strike
                _spe  = st.session_state.selected_pe_strike
                _cprem = st.session_state.ce_premium or 0
                _pprem = st.session_state.pe_premium or 0
                _total = _cprem + _pprem

                if _sce and _spe:
                    st.divider()
                    st.markdown("**Position Summary**")
                    st.dataframe(
                        [
                            {"Leg": "Sell Put (PE)",  "Strike": f"₹{_spe:,.0f}",
                             "Premium/share": f"₹{_pprem:,.2f}"},
                            {"Leg": "Sell Call (CE)", "Strike": f"₹{_sce:,.0f}",
                             "Premium/share": f"₹{_cprem:,.2f}"},
                            {"Leg": "Combined",       "Strike": "—",
                             "Premium/share": f"₹{_total:,.2f}  ·  ₹{_total * lot_size:,.2f} / lot"},
                        ],
                        hide_index=True,
                        use_container_width=True,
                    )

                st.divider()

                # ── Analyse button ───────────────────────────────────────────
                _ready = bool(_sce and _spe)
                if st.button("📊 Analyse", use_container_width=True, type="primary",
                             disabled=not _ready):
                    with st.spinner("Analysing strangle position…"):
                        try:
                            r = requests.post(
                                f"{BACKEND_URL}/strangle/analyse",
                                json={
                                    "symbol":       symbol,
                                    "expiry_date":  expiry,
                                    "call_strike":  _sce,
                                    "put_strike":   _spe,
                                },
                                headers=get_auth_headers(),
                                timeout=30,
                            )
                            r.raise_for_status()
                            st.session_state.strangle_result = r.json()
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

        # Payoff chart
        st.divider()
        st.markdown('<div class="section-hd">📈 Payoff at Expiry</div>', unsafe_allow_html=True)

        payoff_data = result.get("payoff", [])
        if payoff_data:
            # Extract prices and P&L
            prices = [p["price"] for p in payoff_data]
            pls = [p["pl"] for p in payoff_data]

            # Create Plotly figure
            fig = go.Figure()

            # Add P&L line
            fig.add_trace(
                go.Scatter(
                    x=prices,
                    y=pls,
                    mode="lines",
                    name="P&L",
                    line=dict(color="#58A6FF", width=3),
                    fill="tozeroy",
                    fillcolor="rgba(88, 166, 255, 0.15)",
                    hovertemplate="<b>Stock Price:</b> ₹%{x:,.0f}<br><b>P&L:</b> ₹%{y:,.0f}<extra></extra>",
                )
            )

            # Add vertical lines for key price levels
            cmp = result.get("cmp")
            upper_be = result.get("upper_breakeven")
            lower_be = result.get("lower_breakeven")
            call_strike = result["call_leg"]["strike"]
            put_strike = result["put_leg"]["strike"]

            lines = [
                (cmp, "CMP", "#8B949E", "dash"),
                (call_strike, "Call Strike", "#D0883F", "dot"),
                (put_strike, "Put Strike", "#D0883F", "dot"),
                (upper_be, "Upper BE", "#E05252", "solid"),
                (lower_be, "Lower BE", "#E05252", "solid"),
            ]

            for price, label, color, dash_style in lines:
                if price is not None:
                    fig.add_vline(
                        x=price,
                        line_dash=dash_style,
                        line_color=color,
                        annotation_text=label,
                        annotation_position="top",
                        annotation_font_size=10,
                        annotation_font_color=color,
                    )

            # Update layout
            fig.update_layout(
                title=f"<b>Short Strangle Payoff — {result['symbol']} {result['expiry_date']}</b>",
                xaxis_title="Stock Price at Expiry (₹)",
                yaxis_title="Net P&L (₹)",
                hovermode="x unified",
                plot_bgcolor="#161B22",
                paper_bgcolor="#0D1117",
                font=dict(family="Inter, Segoe UI, sans-serif", size=12, color="#E6EDF3"),
                margin=dict(l=8, r=8, t=60, b=36),
                height=350,
                xaxis=dict(gridcolor="#30363D"),
                yaxis=dict(gridcolor="#30363D"),
                legend=dict(orientation="h", yanchor="bottom", y=1.05, xanchor="left", x=0),
            )

            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

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
