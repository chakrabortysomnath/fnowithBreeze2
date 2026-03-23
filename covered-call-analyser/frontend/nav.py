"""
nav.py — Shared top navigation bar and CSS overrides for Breezy F&O.

Usage in every page:
    from nav import NAV_CSS, nav_bar, brand_header
    st.markdown(NAV_CSS, unsafe_allow_html=True)
    nav_bar("analyse")              # or "compare" / "config" / "glossary"
    brand_header()                  # home page — logo only
    brand_header("⚙️", "Configuration", subtitle="Manage master data.")
"""

import streamlit as st

# Fine-grained overrides on top of .streamlit/config.toml dark base
NAV_CSS = """
<style>
  /* ── Chrome ── */
  #MainMenu, footer, header { visibility: hidden; }
  [data-testid="stSidebar"],
  [data-testid="collapsedControl"] { display: none !important; }

  /* ── Top nav bar ── */
  .topnav {
    display: flex;
    gap: 0;
    border-bottom: 1px solid #30363D;
    margin-bottom: 20px;
    margin-top: -10px;
  }
  .nav-item {
    padding: 10px 22px;
    font-size: 14px;
    font-weight: 600;
    text-decoration: none !important;
    color: #8B949E;
    border-bottom: 2px solid transparent;
    transition: color .15s, border-color .15s;
  }
  .nav-item:hover { color: #58A6FF !important; }
  .nav-item.active {
    color: #E6EDF3 !important;
    border-bottom: 2px solid #58A6FF;
  }

  /* ── Metric cards ── */
  [data-testid="metric-container"] {
    background: #161B22;
    border: 1px solid #30363D;
    border-radius: 8px;
    padding: 10px 14px;
  }

  /* ── Buttons ── */
  div[data-testid="stButton"] > button {
    background-color: #238636 !important;
    color: #fff !important;
    border: 1px solid #2EA043 !important;
    border-radius: 6px !important;
    font-weight: 600 !important;
    font-size: 14px !important;
    height: 40px !important;
  }
  div[data-testid="stButton"] > button:hover {
    background-color: #2EA043 !important;
  }

  /* ── Download button ── */
  div[data-testid="stDownloadButton"] > button {
    background-color: #161B22 !important;
    color: #58A6FF !important;
    border: 1px solid #30363D !important;
    border-radius: 6px !important;
    font-weight: 600 !important;
    width: 100% !important;
  }
  div[data-testid="stDownloadButton"] > button:hover {
    border-color: #58A6FF !important;
  }

  /* ── Section heading utility ── */
  .section-hd {
    font-size: 14px;
    font-weight: 700;
    color: #58A6FF;
    border-left: 3px solid #58A6FF;
    padding-left: 8px;
    margin: 18px 0 8px 0;
  }
</style>
"""


def brand_header(
    page_icon: str | None = None,
    page_title: str | None = None,
    subtitle: str = "",
) -> None:
    """Render the common 🤏 Breezy F&O brand logo.

    Optionally shows a page-specific icon + title beneath the main logo,
    and an optional subtitle paragraph.

    Call immediately after nav_bar() on every page.
    """
    html = (
        '<div style="display:flex;align-items:center;gap:12px;margin-bottom:4px;">'
        '<span style="font-size:44px;line-height:1;">🤏</span>'
        '<span style="font-size:36px;font-weight:900;color:#58A6FF;'
        "letter-spacing:-1px;font-family:'Segoe UI',Inter,sans-serif;"
        '">Breezy F&amp;O</span>'
        '</div>'
    )
    if page_icon and page_title:
        html += (
            '<div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;">'
            f'<span style="font-size:22px;line-height:1;">{page_icon}</span>'
            f'<span style="font-size:20px;font-weight:700;color:#8B949E;'
            "font-family:'Segoe UI',Inter,sans-serif;"
            f'">{page_title}</span>'
            '</div>'
        )
    if subtitle:
        html += (
            f'<p style="color:#8B949E;font-size:13px;margin-bottom:18px;">{subtitle}</p>'
        )
    st.markdown(html, unsafe_allow_html=True)


def nav_bar(active: str) -> None:
    """Render the top navigation bar.

    active: 'analyse' | 'compare' | 'config' | 'glossary'
    """
    pages = [
        ("🔍 Analyse",       "/",         "analyse"),
        ("⚖️ Compare",       "/compare",  "compare"),
        ("⚙️ Config",        "/config",   "config"),
        ("📖 Ready Reckoner", "/glossary", "glossary"),
    ]
    links = "\n".join(
        f'<a class="nav-item{" active" if key == active else ""}" href="{href}" target="_self">{label}</a>'
        for label, href, key in pages
    )
    st.markdown(f'<nav class="topnav">{links}</nav>', unsafe_allow_html=True)
