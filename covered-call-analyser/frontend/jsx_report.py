"""
jsx_report.py — JSX summary report generation for covered call analysis results.

Generates a self-contained React JSX component from one or more AnalyseResponse
dicts (as returned by POST /analyse or POST /analyse-watchlist).

Public API:
    generate_jsx(results, title) -> bytes

Usage:
    from jsx_report import generate_jsx

    jsx_bytes = generate_jsx([result_dict])
    st.download_button("Download JSX Report", data=jsx_bytes,
                       file_name="report.jsx", mime="text/plain")
"""

from __future__ import annotations

from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _inr(v) -> str:
    if v is None:
        return "-"
    return f"Rs.{v:,.2f}"


def _pct(v) -> str:
    if v is None:
        return "-"
    return f"{v:.2f}%"


def _esc(s: str) -> str:
    """Escape characters that would break a JSX string literal."""
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("{", "&#123;")
        .replace("}", "&#125;")
    )


# ---------------------------------------------------------------------------
# JSX builders
# ---------------------------------------------------------------------------

def _render_symbol_jsx(res: dict) -> str:
    symbol   = _esc(res.get("symbol", "-"))
    cmp      = res.get("cmp", 0)
    expiry   = _esc(res.get("expiry_date", "-"))
    dte      = res.get("days_to_expiry", 0)
    lot_size = res.get("lot_size", 0)
    pos      = res.get("position", {})
    strikes  = res.get("strikes", [])

    hold_type = "Already holds" if pos.get("already_holds") else "Buy-write"

    # Position row
    pos_row = (
        f'          <tr>\n'
        f'            <td className="td">{pos.get("lots", "-")}</td>\n'
        f'            <td className="td">{pos.get("shares", "-")}</td>\n'
        f'            <td className="td">{_esc(_inr(pos.get("cost_basis_per_share")))}</td>\n'
        f'            <td className="td">{_esc(_inr(pos.get("total_cost")))}</td>\n'
        f'            <td className="td">{_esc(hold_type)}</td>\n'
        f'          </tr>'
    )

    # Strike rows
    strike_rows = []
    for i, s in enumerate(strikes):
        bg = ' style={{backgroundColor:"#f0f4ff"}}' if i % 2 == 1 else ""
        strike_rows.append(
            f'          <tr{bg}>\n'
            f'            <td className="td">{_esc(s.get("strike_type", "-"))}</td>\n'
            f'            <td className="td">Rs.{s.get("strike", 0):,.0f}</td>\n'
            f'            <td className="td">{_esc(_inr(s.get("net_premium_total")))}</td>\n'
            f'            <td className="td">{_esc(_inr(s.get("breakeven")))}</td>\n'
            f'            <td className="td">{_esc(_inr(s.get("max_profit_total")))}</td>\n'
            f'            <td className="td">{_esc(_pct(s.get("premium_yield_pct")))}</td>\n'
            f'            <td className="td">{_esc(_pct(s.get("annualised_yield_pct")))}</td>\n'
            f'            <td className="td">{_esc(_pct(s.get("downside_protection_pct")))}</td>\n'
            f'          </tr>'
        )
    strike_rows_jsx = "\n".join(strike_rows)

    return f"""\
      {{/* ── {symbol} ── */}}
      <section style={{{{marginBottom:"2rem"}}}}>
        <h2 style={{{{color:"#1A56DB", marginBottom:"4px"}}}}>{symbol}</h2>
        <p style={{{{color:"#6B7280", fontSize:"13px", marginBottom:"12px"}}}}>
          CMP: {_esc(_inr(cmp))} &nbsp;|&nbsp; Expiry: {expiry} &nbsp;|&nbsp;
          DTE: {dte} days &nbsp;|&nbsp; Lot size: {lot_size}
        </p>

        <h3 className="section-heading">Position</h3>
        <div style={{{{overflowX:"auto"}}}}>
          <table className="table">
            <thead>
              <tr>
                <th className="th">Lots</th>
                <th className="th">Shares</th>
                <th className="th">Cost Basis/Share</th>
                <th className="th">Total Capital</th>
                <th className="th">Type</th>
              </tr>
            </thead>
            <tbody>
{pos_row}
            </tbody>
          </table>
        </div>

        <h3 className="section-heading" style={{{{marginTop:"16px"}}}}>Strike Analysis</h3>
        <div style={{{{overflowX:"auto"}}}}>
          <table className="table">
            <thead>
              <tr>
                <th className="th">Type</th>
                <th className="th">Strike</th>
                <th className="th">Net Premium</th>
                <th className="th">Breakeven</th>
                <th className="th">Max Profit</th>
                <th className="th">Yield %</th>
                <th className="th">Ann. Yield %</th>
                <th className="th">Downside Prot. %</th>
              </tr>
            </thead>
            <tbody>
{strike_rows_jsx}
            </tbody>
          </table>
        </div>
      </section>"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_jsx(
    results: list[dict],
    title: str = "Covered Call Analysis Report",
) -> bytes:
    """Generate a JSX summary report from one or more analyse_covered_call result dicts.

    Args:
        results: List of dicts as returned by POST /analyse or
                 POST /analyse-watchlist. Must contain at least one entry.
        title:   Report title shown in the component heading.

    Returns:
        UTF-8 encoded JSX bytes, suitable for st.download_button(data=...).

    Raises:
        ValueError: If results is empty.
    """
    if not results:
        raise ValueError("results must contain at least one analysis result.")

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    safe_title = _esc(title)

    symbol_sections = "\n".join(_render_symbol_jsx(r) for r in results)

    jsx = f"""\
import React from "react";

/*
 * Auto-generated by Breezy F&O
 * {ts}
 * Title: {title}
 */

const styles = `
  .report-wrap {{
    font-family: "Segoe UI", Inter, sans-serif;
    max-width: 960px;
    margin: 0 auto;
    padding: 24px;
    color: #1f2937;
  }}
  .report-header {{
    border-bottom: 2px solid #1A56DB;
    margin-bottom: 24px;
    padding-bottom: 12px;
  }}
  .report-title {{
    font-size: 26px;
    font-weight: 900;
    color: #1A56DB;
    margin: 0 0 4px;
  }}
  .report-meta {{
    font-size: 12px;
    color: #9CA3AF;
  }}
  .section-heading {{
    background: #1B3D8F;
    color: #fff;
    padding: 4px 10px;
    font-size: 13px;
    border-radius: 4px;
    margin: 0 0 8px;
  }}
  .table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
  }}
  .th {{
    background: #C5CBF5;
    color: #1A1A4E;
    font-weight: 700;
    padding: 6px 10px;
    border: 1px solid #d1d5db;
    text-align: center;
    white-space: nowrap;
  }}
  .td {{
    padding: 5px 10px;
    border: 1px solid #d1d5db;
    text-align: right;
    white-space: nowrap;
  }}
  .report-footer {{
    border-top: 1px solid #e5e7eb;
    margin-top: 32px;
    padding-top: 10px;
    font-size: 11px;
    color: #9CA3AF;
    text-align: center;
  }}
`;

export default function CoveredCallReport() {{
  return (
    <>
      <style>{{styles}}</style>
      <div className="report-wrap">
        <div className="report-header">
          <h1 className="report-title">{safe_title}</h1>
          <p className="report-meta">Generated by Breezy F&amp;O &middot; {ts}</p>
        </div>

{symbol_sections}

        <div className="report-footer">
          Breezy F&amp;O &middot; {ts}
        </div>
      </div>
    </>
  );
}}
"""
    return jsx.encode("utf-8")
