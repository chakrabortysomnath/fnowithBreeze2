"""
pages/glossary.py — Ready Reckoner: definitions of every key term in Breezy F&O.

Term data is stored in frontend/glossary_terms.json so it can be updated
without touching Python code.
"""

import json
import pathlib

import streamlit as st

from nav import NAV_CSS, brand_header, nav_bar

st.set_page_config(
    page_title="Ready Reckoner — Breezy F&O",
    page_icon="📖",
    layout="centered",
)

st.markdown(NAV_CSS, unsafe_allow_html=True)
nav_bar("glossary")
brand_header(
    "📖", "Ready Reckoner",
    subtitle=(
        "Plain-English definitions for every term, metric and abbreviation used in this app. "
        "Use the search box below or browse by section."
    ),
)

# ── Load terms from JSON ───────────────────────────────────────────────────────

_TERMS_PATH = pathlib.Path(__file__).parent.parent / "glossary_terms.json"

try:
    SECTIONS = json.loads(_TERMS_PATH.read_text(encoding="utf-8"))
except FileNotFoundError:
    st.error(f"glossary_terms.json not found at {_TERMS_PATH}.")
    st.stop()
except json.JSONDecodeError as exc:
    st.error(f"glossary_terms.json is malformed: {exc}")
    st.stop()

# ── Search ─────────────────────────────────────────────────────────────────────

query = st.text_input(
    "Search terms",
    placeholder="e.g. theta, breakeven, ITM…",
    label_visibility="collapsed",
    key="glossary_search",
).strip().lower()

# ── Term data ─────────────────────────────────────────────────────────────────
#
# Structure: list of (section_title, emoji, list of (term, definition))
#

SECTIONS = [
    (
        "Options Basics",
        "🎯",
        [
            (
                "CMP — Current Market Price",
                "The last traded price of the underlying equity share on the NSE. "
                "All strike selection and moneyness calculations are anchored to the CMP.",
            ),
            (
                "LTP — Last Traded Price",
                "The most recent transaction price for an option contract. "
                "Used as the option premium when no bid/ask mid is available.",
            ),
            (
                "Premium",
                "The price paid (buyer) or received (seller) for an options contract. "
                "In a covered-call strategy the seller *receives* the premium upfront, "
                "reducing the effective cost basis of the held shares.",
            ),
            (
                "Strike Price",
                "The fixed price at which the option buyer has the right to purchase "
                "(call) or sell (put) the underlying shares. Chosen by the strategy "
                "relative to the CMP — see ITM, ATM, OTM below.",
            ),
            (
                "ITM — In The Money",
                "A call option whose strike price is *below* the current CMP. "
                "It has intrinsic value. An ITM covered call collects a higher premium "
                "but caps upside sooner.",
            ),
            (
                "ATM — At The Money",
                "A call option whose strike price is approximately *equal* to the CMP. "
                "ATM options have the highest time value (extrinsic value) relative to "
                "premium and are the default comparison point in this app.",
            ),
            (
                "OTM — Out of The Money",
                "A call option whose strike price is *above* the current CMP. "
                "It has no intrinsic value, only time value. "
                "OTM+1 and OTM+2 refer to the first and second strike above ATM.",
            ),
            (
                "Intrinsic Value",
                "The immediate exercise value of an option: max(CMP − Strike, 0) for a call. "
                "OTM options have zero intrinsic value.",
            ),
            (
                "Time Value (Extrinsic Value)",
                "The portion of the option premium above intrinsic value. "
                "Reflects the probability the option moves further in-the-money before expiry. "
                "Decays to zero at expiry (see Theta).",
            ),
            (
                "Expiry / Expiry Date",
                "The date on which the F&O contract ceases to exist. "
                "NSE monthly contracts expire on the last Thursday of each month. "
                "After expiry, in-the-money calls are exercised and out-of-the-money "
                "calls expire worthless.",
            ),
            (
                "DTE — Days to Expiry",
                "Calendar days remaining until the contract's expiry date. "
                "Annualised yield calculations use DTE to scale premium income "
                "(formula: yield% × 365 / DTE).",
            ),
            (
                "IV — Implied Volatility",
                "The market's consensus forecast of how much the underlying will move, "
                "expressed as an annualised percentage standard deviation. "
                "Derived by reverse-solving the Black-Scholes formula from the option's "
                "market price. Higher IV → higher premiums.",
            ),
            (
                "OI — Open Interest",
                "The total number of outstanding option contracts that have not been "
                "settled or closed. High OI indicates a liquid, actively traded strike. "
                "Low OI can lead to wide bid-ask spreads.",
            ),
            (
                "Volume",
                "The number of option contracts traded on the current session. "
                "A useful liquidity signal alongside OI.",
            ),
            (
                "Moneyness %",
                "How far the strike is from the CMP, expressed as a percentage. "
                "Formula: (Strike − CMP) / CMP × 100. "
                "Negative = ITM; near zero = ATM; positive = OTM.",
            ),
        ],
    ),
    (
        "Covered Call Strategy",
        "📈",
        [
            (
                "Covered Call",
                "An options strategy where an investor who *holds* shares simultaneously "
                "*sells* (writes) call options on those shares. The premium received "
                "reduces cost basis and provides downside cushion. "
                "The risk: shares may be called away if CMP exceeds the strike at expiry.",
            ),
            (
                "Buy-Write",
                "A covered call where the shares and the short call are initiated "
                "simultaneously. The net cost is the share purchase price minus the "
                "premium received.",
            ),
            (
                "Holdings / Shares Held",
                "The number of shares already owned by the investor on which calls are "
                "written. Must be a multiple of the F&O lot size.",
            ),
            (
                "Lot Size",
                "The minimum number of shares in one F&O contract. Set by SEBI/NSE and "
                "revised periodically. For example, RELIANCE lot size = 250 means one "
                "call contract covers 250 shares.",
            ),
            (
                "Quantity Held (Lots)",
                "Number of F&O lots held. Determines the number of call contracts "
                "that can be written in a covered position.",
            ),
        ],
    ),
    (
        "Performance Metrics",
        "💰",
        [
            (
                "Gross Premium (₹/share)",
                "The option LTP multiplied by lot size, before deducting any charges. "
                "This is the raw premium income per lot.",
            ),
            (
                "Net Premium / Share",
                "Gross premium per share minus all charges (brokerage, STT, GST) "
                "allocated per share. This is the true income per share from writing the call.",
            ),
            (
                "Net Premium Total (₹)",
                "Net premium per share × total shares held across all lots. "
                "The actual cash received after all transaction costs.",
            ),
            (
                "Premium Yield %",
                "Net Premium Total ÷ Capital Deployed × 100. "
                "Measures income as a percentage of capital for the period to expiry.",
            ),
            (
                "Annualised Yield %",
                "Premium Yield % scaled to a 365-day year: Premium Yield% × 365 / DTE. "
                "Allows fair comparison of strategies with different expiry dates. "
                "The primary ranking metric in this app.",
            ),
            (
                "Breakeven (₹)",
                "The share price at which the position neither profits nor loses: "
                "CMP − Net Premium per share. If the share falls to this level, "
                "the premium exactly offsets the capital loss.",
            ),
            (
                "Downside Protection %",
                "How far the CMP must fall before the investor loses money: "
                "(CMP − Breakeven) / CMP × 100. "
                "Equivalent to the premium yield expressed as downside cushion.",
            ),
            (
                "Max Profit Total (₹)",
                "The maximum possible gain from the covered call at expiry, achieved "
                "when the share price is at or above the strike price at expiry: "
                "(Strike − Cost Basis + Net Premium) × Shares.",
            ),
            (
                "Total Return if Assigned",
                "The end-to-end percentage return if the shares are called away "
                "(assigned) at the strike price: "
                "(Strike − Average Purchase Price + Net Premium) / Average Purchase Price × 100.",
            ),
            (
                "Yield on Build Cost",
                "Net Premium Total ÷ Total Cost Basis of held shares × 100. "
                "Useful for investors who bought shares earlier at a different price.",
            ),
        ],
    ),
    (
        "Cost & Capital",
        "🏦",
        [
            (
                "Brokerage",
                "Fixed fee charged per options leg by the broker. "
                "Typical flat-rate brokers charge ₹20–₹40 per executed order. "
                "This app defaults to ₹40 per lot and deducts it from gross premium.",
            ),
            (
                "STT — Securities Transaction Tax",
                "A government tax on options premium. For selling options, STT is "
                "levied on the premium at 0.1% (as of FY2025). "
                "Deducted from gross premium in net premium calculation.",
            ),
            (
                "GST — Goods & Services Tax",
                "18% GST is levied on brokerage and exchange transaction charges. "
                "A modest but real cost included in total charges.",
            ),
            (
                "Charges Total (₹)",
                "Sum of brokerage + STT + GST for the option leg. "
                "Deducted from gross premium to arrive at net premium.",
            ),
            (
                "Charges %",
                "Charges Total as a percentage of Gross Premium. "
                "A high charges% indicates a low-premium strike where costs consume "
                "a significant portion of income.",
            ),
            (
                "Capital Deployed (₹)",
                "Total market value of shares held: CMP × Shares. "
                "The base against which yield percentages are calculated.",
            ),
            (
                "Cost Basis / Share",
                "The investor's actual average purchase price per share, entered manually. "
                "Used for total-return and build-cost-yield calculations. "
                "If not provided, CMP is used.",
            ),
            (
                "Build-Up Cost",
                "The effective net cost per share after receiving the option premium: "
                "CMP − Net Premium per share. Lowers the break-even price.",
            ),
            (
                "Purchase Cost (1 Lot)",
                "CMP × Lot Size — the capital required to buy one full lot of shares "
                "to support a single covered call contract.",
            ),
        ],
    ),
    (
        "Option Greeks",
        "🔢",
        [
            (
                "Δ Delta",
                "Rate of change of option price per ₹1 move in the underlying. "
                "For a call, Delta ranges from 0 (deep OTM) to 1 (deep ITM). "
                "ATM calls have Delta ≈ 0.5. As a covered-call seller, your net "
                "position Delta = 1 (shares) − Delta (short call).",
            ),
            (
                "Γ Gamma",
                "Rate of change of Delta per ₹1 move in the underlying. "
                "High Gamma near expiry means Delta changes rapidly. "
                "Short Gamma (as a call writer) means losses accelerate if the "
                "underlying makes a large upward move.",
            ),
            (
                "Θ Theta (₹/share/day)",
                "Daily time-value decay of the option premium. "
                "A call seller *benefits* from Theta — each day that passes without "
                "a large move in the underlying, the option loses value and the "
                "seller keeps more of the premium.",
            ),
            (
                "V Vega (₹/share per +1% IV)",
                "Sensitivity of option price to a 1% absolute change in implied "
                "volatility. A call seller is short Vega — a volatility spike after "
                "the call is sold increases the option's value and creates a "
                "mark-to-market loss.",
            ),
            (
                "ρ Rho (₹/share per +1% rate)",
                "Sensitivity of option price to a 1% change in the risk-free "
                "interest rate. Generally the smallest Greek in practice; "
                "more relevant for long-dated options.",
            ),
        ],
    ),
    (
        "Technical & Risk Indicators",
        "📊",
        [
            (
                "HV — Historical Volatility (20-Day)",
                "The realised annualised standard deviation of the stock's daily "
                "log-returns over the past 20 trading sessions. "
                "Comparing HV to IV shows whether options are expensive (IV > HV) "
                "or cheap (IV < HV) — a key signal for covered-call sellers."
                "----------------------------------------------------------"
                "IV > HV Options are expensive"
                "market fears more movement than history suggests "
                ">>>>>>> Great time to sell covered calls - collect fat premiums"
                "IV < HV Options are cheap" 
                "market underestimating historical moves " 
                ">>>>>> Thin premiums; covered calls less attractive"
                "IV ≈ HV Fair value pricing"
                "Neutral — evaluate on other merits",              
            ),
            (
                "Beta",
                "Measures how much the stock moves relative to the broader market "
                "(Nifty 50). Beta = 1.2 means the stock tends to move 1.2% for "
                "every 1% move in the index. High-Beta stocks carry more systematic risk.",
            ),
            (
                "ATR — Average True Range (14-Day)",
                "Average of the last 14 sessions' true range (max of: high-low, "
                "|high−prev close|, |low−prev close|). A practical measure of "
                "day-to-day price movement in rupee terms.",
            ),
            (
                "52-Week High / Low",
                "The highest and lowest closing price over the past 52 weeks. "
                "Used to contextualise the CMP and assess how extended or "
                "oversold a stock is.",
            ),
            (
                "52-Week Position %",
                "(CMP − 52W Low) / (52W High − 52W Low) × 100. "
                "0% = at the 52-week low; 100% = at the 52-week high.",
            ),
            (
                "Key Support",
                "A significant price level below CMP where buying interest has "
                "historically emerged and halted declines. "
                "Used to assess downside risk relative to the breakeven.",
            ),
            (
                "Key Resistance",
                "A significant price level above CMP where selling pressure has "
                "historically capped advances. "
                "A strike set at or near resistance is a common covered-call placement.",
            ),
            (
                "Momentum (1-Month)",
                "Percentage price change over the past 30 days. "
                "Positive momentum may suggest trend continuation; "
                "negative momentum may indicate a weakening underlying.",
            ),
            (
                "Expected ±1σ Move / Month",
                "The one-standard-deviation price range the stock is expected to "
                "trade within over one month, derived from IV: "
                "CMP × IV × √(30/365). Roughly 68% probability the stock stays "
                "within this band.",
            ),
        ],
    ),
    (
        "Put-Call Parity & Futures",
        "⚖️",
        [
            (
                "Put-Call Parity",
                "A no-arbitrage relationship between call price, put price, strike, "
                "spot price and time: C − P = S − K·e^(−rT). "
                "Implies that for any call option there is a theoretically equivalent "
                "put option at the same strike and expiry.",
            ),
            (
                "Implied Put Price",
                "The put price derived from the call price via put-call parity. "
                "Useful for assessing whether the market is pricing in asymmetric "
                "fear (put skew) relative to the theoretical no-arbitrage value.",
            ),
            (
                "Put Delta (approx.)",
                "Approximate delta of the equivalent put: Put Delta ≈ Call Delta − 1. "
                "A call with Delta 0.4 implies a put with Delta ≈ −0.6.",
            ),
            (
                "Approx. Futures Price",
                "Fair value of the near-month futures contract: "
                "Futures ≈ CMP × (1 + r × T), where r is the risk-free rate and "
                "T is time to expiry in years. Options are priced off futures, "
                "not the spot price, in the NSE F&O segment.",
            ),
        ],
    ),
    (
        "Data & Configuration",
        "⚙️",
        [
            (
                "F&O Code (Breeze Shortcode)",
                "The ticker symbol used by the ICICI Breeze API for F&O instruments. "
                "Often different from the NSE equity ticker — e.g., "
                "'RELIND' (Breeze) maps to 'RELIANCE' (NSE).",
            ),
            (
                "NSE Ticker",
                "The symbol used by NSE for the equity share and by yfinance for "
                "historical price data. Used in this app for chart history lookups.",
            ),
            (
                "Breeze Session Token",
                "A daily authentication token issued by ICICI Direct after login. "
                "Required by the Breeze API for all market data requests. "
                "Expires at midnight and must be refreshed each morning.",
            ),
            (
                "Sector / Industry",
                "GICS-style classification of the company. Used to provide context "
                "in the analysis output (e.g., 'Energy / Oil & Gas Integrated'). "
                "Stored in equity_meta.json and editable via the Config page.",
            ),
            (
                "equity_meta.json",
                "A JSON file in the frontend directory that stores sector and industry "
                "metadata for each F&O symbol. Read by both the frontend and backend. "
                "Editable via the Config → Equity Metadata tab.",
            ),
            (
                "lot_sizes.json",
                "Persistent store for F&O lot sizes, shared between frontend and "
                "backend. Updated via Config → Lot Sizes. Survives backend restarts.",
            ),
            (
                "nse_symbols.json",
                "Persistent store for F&O code → NSE ticker mappings. "
                "Updated via Config → NSE Symbol Mapping. Survives backend restarts.",
            ),
            (
                "BACKEND_URL",
                "Environment variable that tells the Streamlit frontend where to find "
                "the FastAPI backend. Defaults to http://localhost:8000 if not set.",
            ),
        ],
    ),
]

# ── Render ─────────────────────────────────────────────────────────────────────

total_shown = 0

for section in SECTIONS:
    section_title = section["section"]
    emoji         = section.get("emoji", "")
    terms         = section.get("terms", [])

    visible = [
        t for t in terms
        if not query
        or query in t["term"].lower()
        or query in t["definition"].lower()
    ]
    if not visible:
        continue

    st.markdown(
        f'<p class="section-hd">{emoji} {section_title}</p>',
        unsafe_allow_html=True,
    )

    for entry in visible:
        with st.expander(entry["term"]):
            st.markdown(entry["definition"])
        total_shown += 1

if total_shown == 0:
    st.info(f'No terms matched **"{query}"**. Try a shorter or different keyword.')
else:
    st.caption(f"Showing {total_shown} term{'s' if total_shown != 1 else ''}.")
