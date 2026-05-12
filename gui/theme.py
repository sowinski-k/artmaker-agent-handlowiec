"""Ecombinat — full theming for Streamlit.

Wszystkie style z ecombinat.html (landing) i ecombinat-dashboard.html
zaadaptowane do Streamlit DOM. Streamlit ma swoje constraints (sidebar to
<section data-testid="stSidebar">, główny content w .block-container) ale
przez agresywne CSS injection osiągamy ~90% wyglądu HTML.
"""
from __future__ import annotations


# ---- Palette ---------------------------------------------------------------

BG = "#FAFAF7"
PANEL = "#FFFFFF"
INK = "#111111"
MUTED = "#6B7280"
MUTED_2 = "#9CA3AF"
BORDER = "#E5E7EB"
BORDER_STRONG = "#D1D5DB"
RED = "#D4212C"
RED_DARK = "#8F1018"
RED_TINT = "#FDECED"
GRAPHITE = "#1C1C1C"
GRAPHITE_2 = "#2A2A2A"


# ---- Brand strings ---------------------------------------------------------

APP_NAME = "Ecombinat"
APP_TAGLINE = "Polski narzędziownik AI dla e-commerce"
ENV_LABEL = "v0.1"


def _build_css() -> str:
    return f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&family=Space+Grotesk:wght@500;600;700&display=swap');
@import url('https://cdn.jsdelivr.net/npm/@tabler/icons-webfont@3.5.0/dist/tabler-icons.min.css');

/* ─── Foundation ────────────────────────────────────────────────────────── */

* {{ box-sizing: border-box; }}

html, body, [class*="css"], .stApp {{
    font-family: 'Inter', -apple-system, system-ui, sans-serif !important;
    color: {INK};
    -webkit-font-smoothing: antialiased;
    font-size: 14px;
    line-height: 1.45;
}}

.stApp {{ background: {BG} !important; }}

.display, .ec-display {{
    font-family: 'Space Grotesk', sans-serif !important;
    letter-spacing: -0.02em;
}}

.mono, .ec-mono {{
    font-family: 'JetBrains Mono', monospace !important;
    font-feature-settings: "tnum";
}}

.tabular {{
    font-feature-settings: "tnum" !important;
    font-variant-numeric: tabular-nums !important;
}}

code, pre, kbd {{
    font-family: 'JetBrains Mono', monospace !important;
}}

/* Hide Streamlit chrome */
#MainMenu, footer, header[data-testid="stHeader"] {{
    visibility: hidden;
    height: 0;
}}

[data-testid="stStatusWidget"] {{ display: none; }}
[data-testid="stDecoration"] {{ display: none; }}
[data-testid="stToolbar"] {{ display: none; }}

/* Tighten content padding */
.main .block-container {{
    padding-top: 1rem !important;
    padding-left: 1.5rem !important;
    padding-right: 1.5rem !important;
    padding-bottom: 4rem !important;
    max-width: 100% !important;
}}

/* Remove default vertical gaps between Streamlit blocks - keeps cards visually
   contiguous in dashboards */
.element-container, [data-testid="element-container"] {{
    margin-bottom: 0 !important;
}}

[data-testid="stVerticalBlock"] {{
    gap: 0.5rem !important;
}}

[data-testid="stHorizontalBlock"] {{
    gap: 12px !important;
}}

[data-testid="column"] {{
    padding: 0 !important;
}}

/* Markdown blocks - no extra wrapping margin */
[data-testid="stMarkdown"], [data-testid="stMarkdownContainer"] {{
    margin: 0 !important;
}}

[data-testid="stMarkdown"] p {{ margin-bottom: 0 !important; }}

/* Default Streamlit headings */
h1 {{
    font-family: 'Inter', sans-serif !important;
    font-weight: 600 !important;
    font-size: 22px !important;
    letter-spacing: -0.4px !important;
    color: {INK} !important;
    margin: 0 0 4px 0 !important;
    line-height: 1.2 !important;
}}

h2 {{
    font-weight: 600 !important;
    font-size: 16px !important;
    letter-spacing: -0.2px !important;
    color: {INK} !important;
    margin-top: 8px !important;
}}

h3 {{
    font-weight: 600 !important;
    font-size: 14px !important;
    color: {INK} !important;
}}

p, label, .stMarkdown {{
    color: {INK};
    font-size: 14px;
}}

/* ═══════════ SIDEBAR — dark like aside.sidebar ═══════════ */

section[data-testid="stSidebar"] {{
    background: {GRAPHITE} !important;
    border-right: 1px solid rgba(255,255,255,0.06);
    width: 224px !important;
    min-width: 224px !important;
}}

section[data-testid="stSidebar"] > div:first-child {{
    padding: 16px 12px !important;
    background: {GRAPHITE} !important;
}}

section[data-testid="stSidebar"] [data-testid="stSidebarContent"] {{
    padding: 0 !important;
}}

/* All text inside sidebar - light */
section[data-testid="stSidebar"] *,
section[data-testid="stSidebar"] p,
section[data-testid="stSidebar"] span,
section[data-testid="stSidebar"] div {{
    color: #D1D5DB;
}}

section[data-testid="stSidebar"] h1,
section[data-testid="stSidebar"] h2,
section[data-testid="stSidebar"] h3 {{
    color: #FFFFFF !important;
    font-weight: 600 !important;
}}

/* Sidebar labels - mute uppercase like sb-section */
section[data-testid="stSidebar"] label,
section[data-testid="stSidebar"] [data-testid="stWidgetLabel"] p {{
    color: rgba(255,255,255,0.45) !important;
    font-size: 10.5px !important;
    text-transform: uppercase !important;
    letter-spacing: 1.4px !important;
    font-weight: 600 !important;
}}

/* Sidebar inputs - dark variant */
section[data-testid="stSidebar"] .stSelectbox > div > div,
section[data-testid="stSidebar"] .stTextInput input,
section[data-testid="stSidebar"] .stTextArea textarea,
section[data-testid="stSidebar"] .stNumberInput input {{
    background: rgba(255,255,255,0.05) !important;
    border: 1px solid rgba(255,255,255,0.1) !important;
    color: #FFFFFF !important;
    border-radius: 6px !important;
}}

section[data-testid="stSidebar"] .stSelectbox > div > div:hover {{
    border-color: rgba(255,255,255,0.2) !important;
}}

section[data-testid="stSidebar"] .stButton button {{
    background: rgba(255,255,255,0.05) !important;
    border: 1px solid rgba(255,255,255,0.1) !important;
    color: #FFFFFF !important;
    font-weight: 500;
    border-radius: 6px !important;
}}

section[data-testid="stSidebar"] .stButton button:hover {{
    background: rgba(255,255,255,0.1) !important;
}}

section[data-testid="stSidebar"] [data-testid="stAlert"] {{
    background: rgba(255,255,255,0.05) !important;
    border: 1px solid rgba(255,255,255,0.1) !important;
    color: #D1D5DB !important;
}}

/* Sidebar logo */
.sb-logo {{
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 0 4px 14px;
    border-bottom: 1px solid rgba(255,255,255,0.08);
    margin-bottom: 12px;
}}

.sb-logo-mark {{
    width: 28px; height: 28px;
    background: {RED};
    border-radius: 6px;
    display: flex; align-items: center; justify-content: center;
    color: #fff;
    box-shadow: 0 2px 6px rgba(212,33,44,0.3);
    flex-shrink: 0;
}}

.sb-logo-mark i {{ font-size: 16px; }}

.sb-logo-text {{
    font-weight: 600;
    font-size: 14px;
    letter-spacing: -0.2px;
    color: white !important;
    font-family: 'Inter', sans-serif;
}}

.sb-logo-env {{
    font-family: 'JetBrains Mono', monospace;
    font-size: 10px;
    color: rgba(255,255,255,0.55) !important;
    padding: 1px 6px;
    background: rgba(255,255,255,0.07);
    border-radius: 3px;
    margin-left: auto;
    font-weight: 500;
}}

/* Sidebar nav section headings */
.sb-section {{
    font-size: 10.5px;
    text-transform: uppercase;
    letter-spacing: 1.4px;
    color: rgba(255,255,255,0.4) !important;
    padding: 12px 4px 4px;
    font-weight: 600;
    margin-top: 4px;
}}

/* Sidebar nav items */
.sb-item {{
    display: flex !important;
    align-items: center !important;
    gap: 10px !important;
    padding: 7px 10px !important;
    border-radius: 6px;
    color: #D1D5DB !important;
    font-size: 13px;
    cursor: pointer;
    text-decoration: none;
    margin-bottom: 1px;
    background: transparent;
    transition: background 0.12s;
}}

.sb-item:hover {{
    background: rgba(255,255,255,0.05);
    color: #fff !important;
}}

.sb-item.active {{
    background: rgba(212,33,44,0.12);
    color: #fff !important;
    position: relative;
}}

.sb-item.active::before {{
    content: '';
    position: absolute;
    left: -12px;
    top: 50%;
    transform: translateY(-50%);
    width: 3px;
    height: 18px;
    background: {RED};
    border-radius: 0 2px 2px 0;
}}

.sb-item.disabled {{
    opacity: 0.4;
    cursor: not-allowed;
}}

.sb-item i {{ font-size: 16px; width: 16px; flex-shrink: 0; }}

.sb-count {{
    margin-left: auto;
    font-family: 'JetBrains Mono', monospace;
    font-size: 10.5px;
    color: rgba(255,255,255,0.5) !important;
}}

.sb-item.active .sb-count {{ color: rgba(255,255,255,0.85) !important; }}

/* Sidebar foot - credits meter */
.sb-foot {{
    margin-top: 16px;
    padding: 10px;
    background: rgba(255,255,255,0.04);
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 6px;
}}

.sb-foot-row {{
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    font-size: 11px;
    color: rgba(255,255,255,0.6) !important;
    margin-bottom: 4px;
}}

.sb-foot-row strong {{
    color: #fff !important;
    font-family: 'JetBrains Mono', monospace;
    font-weight: 500;
}}

.sb-bar {{
    height: 3px;
    background: rgba(255,255,255,0.08);
    border-radius: 2px;
    overflow: hidden;
    margin: 6px 0 8px;
}}

.sb-bar > div {{
    height: 100%;
    background: {RED};
    transition: width 0.3s;
}}

.sb-foot a {{
    font-size: 11px;
    color: rgba(255,255,255,0.6) !important;
    text-decoration: none;
    display: block;
    padding-top: 6px;
    border-top: 1px solid rgba(255,255,255,0.06);
    margin-top: 4px;
}}

.sb-foot a:hover {{ color: #fff !important; }}

/* ═══════════ TOPBAR ═══════════ */

.topbar {{
    background: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 8px 16px;
    display: flex;
    align-items: center;
    gap: 16px;
    margin-bottom: 18px;
    height: 52px;
}}

.crumb {{
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 13px;
    color: {MUTED};
    flex-shrink: 0;
}}

.crumb strong {{
    color: {INK};
    font-weight: 500;
}}

.crumb i {{ font-size: 12px; color: {MUTED_2}; }}

.search-mock {{
    margin-left: auto;
    display: flex;
    align-items: center;
    gap: 8px;
    background: {BG};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 6px 10px;
    width: 280px;
    color: {MUTED};
    font-size: 13px;
}}

.search-mock i {{ font-size: 14px; }}

.search-mock .kbd {{
    margin-left: auto;
    font-family: 'JetBrains Mono', monospace;
    font-size: 10px;
    background: {PANEL};
    border: 1px solid {BORDER};
    padding: 1px 5px;
    border-radius: 3px;
    color: {MUTED};
}}

.topbtn {{
    width: 32px; height: 32px;
    display: flex; align-items: center; justify-content: center;
    border-radius: 6px;
    color: {MUTED};
    border: 1px solid {BORDER};
    background: {PANEL};
    position: relative;
}}

.topbtn:hover {{
    color: {INK};
    border-color: {BORDER_STRONG};
}}

.topbtn i {{ font-size: 15px; }}

.topbtn .dot {{
    position: absolute;
    top: 6px; right: 6px;
    width: 6px; height: 6px;
    background: {RED};
    border-radius: 50%;
    border: 1.5px solid {PANEL};
}}

.avatar {{
    width: 32px; height: 32px;
    border-radius: 50%;
    background: {GRAPHITE};
    color: #fff;
    display: flex; align-items: center; justify-content: center;
    font-weight: 600;
    font-size: 12px;
    border: 2px solid {RED};
    flex-shrink: 0;
}}

/* ═══════════ PAGE HEAD ═══════════ */

.page-head {{
    display: flex;
    align-items: flex-end;
    justify-content: space-between;
    margin-bottom: 20px;
    gap: 16px;
}}

.page-head h1 {{
    font-size: 22px !important;
    font-weight: 600 !important;
    letter-spacing: -0.4px;
    margin: 0 0 4px 0 !important;
}}

.page-head p {{
    color: {MUTED};
    font-size: 13.5px;
    margin: 0;
}}

.last-update {{
    font-size: 11px;
    color: {MUTED_2};
    font-family: 'JetBrains Mono', monospace;
}}

/* Time range pill group */
.timerange {{
    display: flex; gap: 0;
    background: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 6px;
    overflow: hidden;
}}

.timerange button {{
    padding: 6px 12px;
    font-size: 12.5px;
    font-family: 'Inter', sans-serif;
    background: none;
    border: none;
    color: {MUTED};
    cursor: pointer;
    border-right: 1px solid {BORDER};
}}

.timerange button:last-child {{ border-right: none; }}

.timerange button:hover {{ background: {BG}; color: {INK}; }}

.timerange button.active {{
    background: {GRAPHITE};
    color: #fff;
}}

/* ═══════════ STAT CARDS WITH SPARKLINE ═══════════ */

.stat {{
    background: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 14px 16px;
    position: relative;
    overflow: hidden;
    height: 100%;
}}

.stat-label {{
    font-size: 11.5px;
    color: {MUTED};
    text-transform: uppercase;
    letter-spacing: 0.8px;
    font-weight: 500;
    margin-bottom: 8px;
    display: flex;
    align-items: center;
    gap: 6px;
}}

.stat-label i {{ font-size: 13px; }}

.stat-value {{
    font-size: 26px;
    font-weight: 600;
    letter-spacing: -0.6px;
    line-height: 1.1;
    font-variant-numeric: tabular-nums;
    color: {INK};
    display: flex;
    align-items: baseline;
    gap: 6px;
}}

.stat-value .unit {{
    font-size: 13px;
    color: {MUTED};
    font-weight: 400;
}}

.stat-delta {{
    margin-top: 6px;
    font-size: 11.5px;
    display: flex;
    align-items: center;
    gap: 4px;
    color: {MUTED};
    font-family: 'JetBrains Mono', monospace;
}}

.stat-delta.up {{ color: {RED_DARK}; }}
.stat-delta.down {{ color: {MUTED}; }}

.stat-spark {{
    position: absolute;
    bottom: 12px;
    right: 12px;
    opacity: 0.55;
}}

/* ═══════════ CARDS ═══════════ */

.ec-card {{
    background: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 8px;
    margin-bottom: 12px;
}}

.card-head {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 14px 16px;
    border-bottom: 1px solid {BORDER};
}}

.card-title {{
    font-size: 13.5px;
    font-weight: 600;
    color: {INK};
    display: flex;
    align-items: center;
    gap: 8px;
}}

.card-title i {{ color: {RED}; font-size: 15px; }}

.card-actions {{
    display: flex;
    gap: 6px;
    align-items: center;
    font-size: 12px;
    color: {MUTED};
}}

.pill-btn {{
    padding: 3px 8px;
    background: {BG};
    border: 1px solid {BORDER};
    border-radius: 4px;
    font-size: 11.5px;
    color: {MUTED};
    cursor: pointer;
    font-family: inherit;
}}

.pill-btn:hover {{
    color: {INK};
    border-color: {BORDER_STRONG};
}}

.pill-btn.active {{
    background: {GRAPHITE};
    color: #fff;
    border-color: {GRAPHITE};
}}

.card-body {{ padding: 16px; }}

/* ═══════════ FUNNEL ═══════════ */

.funnel {{
    display: flex;
    flex-direction: column;
    gap: 8px;
    padding: 4px 0;
}}

.funnel-row {{
    display: grid;
    grid-template-columns: 140px 1fr 60px;
    align-items: center;
    gap: 12px;
    font-size: 12.5px;
}}

.funnel-label {{
    color: {INK};
    display: flex;
    align-items: center;
    gap: 8px;
}}

.funnel-label i {{ font-size: 14px; color: {MUTED}; }}

.funnel-bar {{
    height: 18px;
    background: {BG};
    border-radius: 3px;
    position: relative;
    overflow: hidden;
}}

.funnel-fill {{
    height: 100%;
    background: {GRAPHITE};
    display: flex;
    align-items: center;
    padding-left: 8px;
    color: #fff;
    font-size: 11px;
    font-family: 'JetBrains Mono', monospace;
    transition: width 0.5s;
}}

.funnel-fill.red {{ background: {RED}; }}

.funnel-num {{
    font-family: 'JetBrains Mono', monospace;
    font-size: 12px;
    color: {MUTED};
    text-align: right;
}}

/* ═══════════ ACTIVITY FEED ═══════════ */

.activity {{ padding: 0; }}

.act-item {{
    padding: 11px 16px;
    border-bottom: 1px solid {BORDER};
    display: grid;
    grid-template-columns: auto 1fr auto;
    gap: 10px;
    align-items: flex-start;
    font-size: 12.5px;
}}

.act-item:last-child {{ border-bottom: none; }}

.act-ico {{
    width: 24px; height: 24px;
    border-radius: 4px;
    background: {BG};
    border: 1px solid {BORDER};
    display: flex; align-items: center; justify-content: center;
    color: {MUTED};
    flex-shrink: 0;
}}

.act-ico i {{ font-size: 13px; }}

.act-ico.red {{
    background: {RED_TINT};
    border-color: rgba(212,33,44,0.2);
    color: {RED};
}}

.act-text {{
    line-height: 1.4;
    color: {MUTED};
}}

.act-text strong {{
    color: {INK};
    font-weight: 500;
}}

.act-time {{
    color: {MUTED_2};
    font-family: 'JetBrains Mono', monospace;
    font-size: 11px;
}}

/* ═══════════ SYSTEM STATUS ROWS ═══════════ */

.sys-row {{
    padding: 11px 16px;
    border-bottom: 1px solid {BORDER};
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-size: 12.5px;
}}

.sys-row:last-child {{ border-bottom: none; }}

.sys-label {{
    color: {INK};
    display: flex;
    align-items: center;
    gap: 6px;
}}

.sys-val {{
    font-family: 'JetBrains Mono', monospace;
    color: {MUTED};
    font-size: 12px;
}}

.status-dot {{
    width: 7px; height: 7px;
    border-radius: 50%;
    display: inline-block;
    margin-right: 6px;
}}

.status-dot.ok {{
    background: #10B981;
    box-shadow: 0 0 0 3px rgba(16,185,129,0.15);
}}

.status-dot.warn {{ background: #F59E0B; }}
.status-dot.err {{ background: {RED}; }}

/* ═══════════ TABLE (.tbl) ═══════════ */

table.tbl {{
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
}}

table.tbl th {{
    text-align: left;
    font-weight: 500;
    font-size: 11px;
    color: {MUTED};
    text-transform: uppercase;
    letter-spacing: 0.8px;
    padding: 10px 16px;
    background: {BG};
    border-bottom: 1px solid {BORDER};
}}

table.tbl th.num, table.tbl td.num {{
    text-align: right;
    font-family: 'JetBrains Mono', monospace;
}}

table.tbl td {{
    padding: 11px 16px;
    border-bottom: 1px solid {BORDER};
}}

table.tbl tr:last-child td {{ border-bottom: none; }}
table.tbl tr:hover td {{ background: {BG}; }}

.tool-cell {{ display: flex; align-items: center; gap: 8px; }}

.tool-ico {{
    width: 24px; height: 24px;
    background: {BG};
    border: 1px solid {BORDER};
    border-radius: 4px;
    display: flex; align-items: center; justify-content: center;
    color: {RED};
}}

.tool-ico i {{ font-size: 14px; }}

.delta-pos {{
    color: {RED_DARK};
    font-family: 'JetBrains Mono', monospace;
    font-size: 12px;
}}

.delta-neg {{
    color: {MUTED};
    font-family: 'JetBrains Mono', monospace;
    font-size: 12px;
}}

/* ═══════════ BADGES ═══════════ */

.ec-badge {{
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: 10.5px;
    font-weight: 600;
    padding: 2px 7px;
    border-radius: 3px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    font-family: 'JetBrains Mono', monospace;
}}

.ec-badge.done {{
    background: {BG};
    color: {GRAPHITE};
    border: 1px solid {BORDER};
}}

.ec-badge.running, .ec-badge.live {{
    background: {RED_TINT};
    color: {RED_DARK};
}}

.ec-badge.queue {{
    background: {BG};
    color: {MUTED};
    border: 1px solid {BORDER};
}}

.ec-badge.failed {{
    background: #fef2f2;
    color: {RED_DARK};
    border: 1px solid #fecaca;
}}

/* ═══════════ STREAMLIT NATIVE TABS — pill style ═══════════ */

.stTabs [data-baseweb="tab-list"] {{
    background: transparent !important;
    border-bottom: 1px solid {BORDER};
    gap: 0;
    margin-bottom: 20px;
}}

.stTabs [data-baseweb="tab"] {{
    background: transparent !important;
    color: {MUTED} !important;
    border: none !important;
    border-bottom: 2px solid transparent !important;
    padding: 10px 16px !important;
    margin: 0 !important;
    font-weight: 500 !important;
    font-size: 13.5px !important;
    height: auto !important;
}}

.stTabs [data-baseweb="tab"]:hover {{ color: {INK} !important; }}

.stTabs [aria-selected="true"] {{
    color: {INK} !important;
    border-bottom: 2px solid {RED} !important;
    font-weight: 600 !important;
}}

/* ═══════════ BUTTONS ═══════════ */

.stButton button {{
    border-radius: 6px !important;
    font-weight: 500 !important;
    font-family: 'Inter', sans-serif !important;
    transition: all 0.15s ease !important;
    padding: 8px 14px !important;
    font-size: 13.5px !important;
}}

.stButton button[kind="primary"] {{
    background: {RED} !important;
    color: white !important;
    border: 1px solid {RED} !important;
    box-shadow: 0 1px 2px rgba(143, 16, 24, 0.1);
}}

.stButton button[kind="primary"]:hover {{
    background: {RED_DARK} !important;
    border-color: {RED_DARK} !important;
    box-shadow: 0 4px 12px rgba(212,33,44,0.25);
}}

.stButton button[kind="secondary"] {{
    background: {PANEL} !important;
    color: {INK} !important;
    border: 1px solid {BORDER} !important;
}}

.stButton button[kind="secondary"]:hover {{
    border-color: {BORDER_STRONG} !important;
    background: {BG} !important;
}}

/* ═══════════ INPUTS ═══════════ */

.stTextInput input, .stTextArea textarea, .stSelectbox > div > div,
.stNumberInput input, .stDateInput input {{
    background: {PANEL} !important;
    border: 1px solid {BORDER} !important;
    border-radius: 6px !important;
    font-family: 'Inter', sans-serif !important;
    color: {INK} !important;
    font-size: 13.5px !important;
}}

.stTextInput input:focus, .stTextArea textarea:focus,
.stNumberInput input:focus {{
    border-color: {RED} !important;
    box-shadow: 0 0 0 3px rgba(212,33,44,0.08) !important;
}}

/* ═══════════ EXPANDERS ═══════════ */

[data-testid="stExpander"] details > summary {{
    background: {PANEL} !important;
    border: 1px solid {BORDER} !important;
    border-radius: 8px !important;
    font-weight: 500 !important;
    color: {INK} !important;
    padding: 12px 16px !important;
}}

[data-testid="stExpander"] details > summary:hover {{
    border-color: {BORDER_STRONG} !important;
}}

[data-testid="stExpander"] details[open] > summary {{
    border-radius: 8px 8px 0 0 !important;
    border-bottom: 1px solid {BORDER} !important;
}}

[data-testid="stExpander"] details[open] > div:not(summary) {{
    background: {PANEL};
    border: 1px solid {BORDER};
    border-top: none;
    border-radius: 0 0 8px 8px;
    padding: 16px !important;
}}

/* ═══════════ ALERTS ═══════════ */

[data-testid="stAlert"] {{
    border-radius: 6px !important;
    border-left-width: 3px !important;
    font-size: 13.5px;
}}

/* ═══════════ PROGRESS ═══════════ */

.stProgress > div > div {{
    background: {RED} !important;
}}

/* ═══════════ LANDING PAGE STYLES ═══════════ */

.ec-landing {{
    font-family: 'Inter', sans-serif;
    color: {INK};
    line-height: 1.6;
    background: {BG};
    margin: -1rem -1.5rem -4rem -1.5rem;
    padding-bottom: 0;
}}

.ec-landing .ec-container {{
    max-width: 1200px;
    margin: 0 auto;
    padding: 0 24px;
}}

.ec-landing-nav {{
    position: sticky;
    top: 0;
    z-index: 50;
    background: rgba(250, 250, 247, 0.85);
    backdrop-filter: saturate(180%) blur(12px);
    -webkit-backdrop-filter: saturate(180%) blur(12px);
    border-bottom: 1px solid {BORDER};
}}

.ec-landing-nav-inner {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 16px 24px;
    max-width: 1200px;
    margin: 0 auto;
}}

.ec-nav-logo {{
    display: flex;
    align-items: center;
    gap: 10px;
    font-family: 'Space Grotesk', sans-serif;
    font-weight: 700;
    font-size: 18px;
    letter-spacing: -0.5px;
}}

.ec-nav-logo-mark {{
    width: 32px; height: 32px;
    background: {RED};
    border-radius: 8px;
    display: flex; align-items: center; justify-content: center;
    color: #fff;
    position: relative;
    overflow: hidden;
}}

.ec-nav-logo-mark::after {{
    content: '';
    position: absolute;
    inset: 0;
    background: linear-gradient(135deg, transparent 50%, rgba(0,0,0,0.2) 100%);
}}

.ec-nav-logo-mark i {{ font-size: 18px; position: relative; z-index: 1; }}

.ec-nav-links {{
    display: flex;
    gap: 28px;
    list-style: none;
    padding: 0;
    margin: 0;
}}

.ec-nav-links a {{
    color: {INK};
    text-decoration: none;
    font-size: 14px;
    font-weight: 500;
    transition: color 0.2s;
}}

.ec-nav-links a:hover {{ color: {RED}; }}

.ec-btn {{
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding: 10px 18px;
    border-radius: 8px;
    font-size: 14px;
    font-weight: 500;
    text-decoration: none;
    border: none;
    cursor: pointer;
    transition: all 0.15s;
    font-family: 'Inter', sans-serif;
}}

.ec-btn-primary {{
    background: {RED};
    color: #fff;
    box-shadow: 0 1px 2px rgba(143, 16, 24, 0.1);
}}

.ec-btn-primary:hover {{
    background: {RED_DARK};
    box-shadow: 0 4px 12px rgba(212, 33, 44, 0.25);
    transform: translateY(-1px);
}}

.ec-btn-ghost {{
    background: transparent;
    color: {INK};
}}

.ec-btn-ghost:hover {{ background: {BORDER}; }}

.ec-btn-dark {{
    background: {GRAPHITE};
    color: #fff;
}}

.ec-btn-lg {{ padding: 14px 24px; font-size: 15px; }}

/* Hero */
.ec-hero {{
    padding: 80px 0 60px;
    position: relative;
}}

.ec-hero-grid {{
    display: grid;
    grid-template-columns: 1.05fr 1fr;
    gap: 60px;
    align-items: center;
}}

.ec-eyebrow {{
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding: 6px 14px;
    background: {RED_TINT};
    color: {RED_DARK};
    border-radius: 999px;
    font-size: 12.5px;
    font-weight: 600;
    margin-bottom: 24px;
    border: 1px solid rgba(212, 33, 44, 0.15);
}}

.ec-eyebrow i {{ font-size: 14px; }}

.ec-hero h1 {{
    font-family: 'Space Grotesk', sans-serif !important;
    font-size: clamp(40px, 6vw, 64px) !important;
    font-weight: 700 !important;
    line-height: 1.02 !important;
    letter-spacing: -0.03em !important;
    margin-bottom: 24px !important;
    color: {INK} !important;
}}

.ec-hero h1 .ec-accent {{
    color: {RED};
    position: relative;
    display: inline-block;
}}

.ec-hero h1 .ec-accent::after {{
    content: '';
    position: absolute;
    left: 0; right: 0; bottom: 6px;
    height: 8px;
    background: {RED};
    opacity: 0.15;
    z-index: -1;
    transform: skewX(-12deg);
}}

.ec-hero p.ec-lead {{
    font-size: 18px;
    color: {MUTED};
    margin-bottom: 32px;
    max-width: 520px;
}}

.ec-hero-actions {{
    display: flex;
    gap: 12px;
    flex-wrap: wrap;
    margin-bottom: 32px;
}}

.ec-hero-meta {{
    display: flex;
    gap: 28px;
    flex-wrap: wrap;
    font-size: 13px;
    color: {MUTED};
}}

.ec-hero-meta-item {{
    display: flex;
    align-items: center;
    gap: 6px;
}}

.ec-hero-meta-item i {{ color: {RED}; font-size: 16px; }}

/* Mock browser */
.ec-mock {{
    background: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 20px;
    box-shadow:
        0 1px 2px rgba(0,0,0,0.04),
        0 20px 60px -20px rgba(17, 17, 17, 0.18);
    overflow: hidden;
}}

.ec-mock-header {{
    background: {GRAPHITE};
    padding: 12px 16px;
    display: flex;
    align-items: center;
    gap: 8px;
}}

.ec-mock-dot {{ width: 10px; height: 10px; border-radius: 50%; }}
.ec-mock-dot.r {{ background: #FF5F56; }}
.ec-mock-dot.y {{ background: #FFBD2E; }}
.ec-mock-dot.g {{ background: #27C93F; }}

.ec-mock-url {{
    flex: 1;
    text-align: center;
    background: rgba(255,255,255,0.08);
    color: rgba(255,255,255,0.6);
    font-size: 11px;
    padding: 4px 12px;
    border-radius: 4px;
    font-family: 'JetBrains Mono', monospace;
}}

.ec-mock-body {{ padding: 20px; }}

.ec-mock-tabs {{
    display: flex;
    gap: 6px;
    margin-bottom: 16px;
}}

.ec-mock-tab {{
    padding: 6px 12px;
    border-radius: 6px;
    font-size: 11.5px;
    font-weight: 500;
    background: {BG};
    color: {MUTED};
    border: 1px solid {BORDER};
}}

.ec-mock-tab.active {{
    background: {GRAPHITE};
    color: #fff;
    border-color: {GRAPHITE};
}}

.ec-mock-grid {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 10px;
}}

.ec-mock-tile {{
    aspect-ratio: 1;
    border-radius: 10px;
    position: relative;
    overflow: hidden;
}}

.ec-mock-tile.t1 {{ background: linear-gradient(135deg, #2a2a2a, #4a3030 50%, #8F1018); border: 2px solid {RED}; }}
.ec-mock-tile.t2 {{ background: linear-gradient(135deg, #1C1C1C, #3a3a3a); }}
.ec-mock-tile.t3 {{ background: linear-gradient(135deg, #6B7280, #111111); }}
.ec-mock-tile.t4 {{ background: linear-gradient(135deg, #8F1018, #1C1C1C); }}

.ec-mock-tile-label {{
    position: absolute;
    bottom: 8px; left: 8px;
    background: rgba(0,0,0,0.55);
    color: #fff;
    font-size: 10px;
    padding: 3px 8px;
    border-radius: 4px;
    font-weight: 500;
}}

.ec-mock-tile-heart {{
    position: absolute;
    top: 8px; right: 8px;
    width: 24px; height: 24px;
    background: rgba(255,255,255,0.15);
    border-radius: 50%;
    display: flex; align-items: center; justify-content: center;
    color: #fff;
}}

.ec-mock-tile-heart.liked {{ background: {RED}; }}
.ec-mock-tile-heart i {{ font-size: 12px; }}

/* Features section */
.ec-section {{ padding: 100px 0; }}

.ec-section-head {{
    text-align: center;
    max-width: 640px;
    margin: 0 auto 56px;
}}

.ec-section-head h2 {{
    font-family: 'Space Grotesk', sans-serif !important;
    font-size: clamp(32px, 4vw, 44px) !important;
    font-weight: 700 !important;
    letter-spacing: -0.02em !important;
    line-height: 1.1 !important;
    margin-bottom: 16px !important;
    color: {INK} !important;
}}

.ec-section-head p {{
    color: {MUTED};
    font-size: 17px;
}}

.ec-features-grid {{
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 16px;
}}

.ec-feature {{
    background: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 12px;
    padding: 28px;
    transition: all 0.25s;
    position: relative;
    overflow: hidden;
}}

.ec-feature:hover {{
    transform: translateY(-3px);
    box-shadow: 0 12px 32px -12px rgba(17,17,17,0.12);
    border-color: rgba(212,33,44,0.3);
}}

.ec-feature-icon {{
    width: 44px; height: 44px;
    border-radius: 10px;
    background: {RED_TINT};
    color: {RED};
    display: flex; align-items: center; justify-content: center;
    margin-bottom: 18px;
}}

.ec-feature-icon i {{ font-size: 22px; }}

.ec-feature.dark {{
    background: {GRAPHITE};
    color: #fff;
    border-color: {GRAPHITE};
}}

.ec-feature.dark .ec-feature-icon {{
    background: rgba(212,33,44,0.15);
    color: {RED};
}}

.ec-feature.dark .ec-feature-desc {{ color: rgba(255,255,255,0.6); }}

.ec-feature h3 {{
    font-family: 'Space Grotesk', sans-serif !important;
    font-size: 19px !important;
    font-weight: 600 !important;
    margin-bottom: 8px !important;
    letter-spacing: -0.01em !important;
}}

.ec-feature.dark h3 {{ color: #fff !important; }}

.ec-feature-desc {{
    font-size: 14.5px;
    color: {MUTED};
    line-height: 1.55;
}}

.ec-feature-tag {{
    position: absolute;
    top: 20px; right: 20px;
    font-size: 10.5px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 1px;
    padding: 3px 8px;
    background: {RED};
    color: #fff;
    border-radius: 4px;
}}

.ec-feature-tag.soon {{
    background: rgba(255,255,255,0.15);
    color: rgba(255,255,255,0.7);
}}

/* CTA section */
.ec-cta-final {{
    padding: 100px 0;
    background: {BG};
}}

.ec-cta-box {{
    background: {GRAPHITE};
    color: #fff;
    border-radius: 20px;
    padding: 60px 40px;
    text-align: center;
    position: relative;
    overflow: hidden;
}}

.ec-cta-box::before {{
    content: '';
    position: absolute;
    top: -100px; right: -100px;
    width: 400px; height: 400px;
    background: radial-gradient(circle, rgba(212,33,44,0.25) 0%, transparent 70%);
    pointer-events: none;
}}

.ec-cta-box h2 {{
    font-family: 'Space Grotesk', sans-serif !important;
    font-size: clamp(28px, 4vw, 40px) !important;
    font-weight: 700 !important;
    color: #fff !important;
    margin-bottom: 16px !important;
    position: relative;
}}

.ec-cta-box p {{
    color: rgba(255,255,255,0.7);
    font-size: 16px;
    max-width: 500px;
    margin: 0 auto 32px;
    position: relative;
}}

.ec-cta-actions {{
    display: flex;
    gap: 12px;
    justify-content: center;
    flex-wrap: wrap;
    position: relative;
}}

.ec-btn-white {{
    background: #fff;
    color: {INK};
}}

.ec-btn-white:hover {{ background: {BORDER}; }}

/* Footer */
.ec-footer {{
    padding: 30px 0;
    border-top: 1px solid {BORDER};
    color: {MUTED};
    font-size: 13.5px;
    background: {BG};
}}

.ec-footer-inner {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex-wrap: wrap;
    gap: 16px;
    max-width: 1200px;
    margin: 0 auto;
    padding: 0 24px;
}}

.ec-footer-links {{
    display: flex;
    gap: 24px;
}}

.ec-footer-links a {{
    color: {MUTED};
    text-decoration: none;
}}

.ec-footer-links a:hover {{ color: {INK}; }}

/* Login form box (used on landing when not authenticated) */
.ec-login-box {{
    background: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 16px;
    padding: 32px;
    max-width: 420px;
    margin: 60px auto;
    box-shadow: 0 10px 30px -10px rgba(0,0,0,0.08);
}}

.ec-login-box h2 {{
    font-family: 'Space Grotesk', sans-serif !important;
    font-size: 24px !important;
    margin-bottom: 8px !important;
}}

/* Hide page if landing is showing */
.ec-landing-mode-only {{ display: block; }}

/* Responsive */
@media (max-width: 900px) {{
    .ec-hero-grid {{ grid-template-columns: 1fr; gap: 40px; }}
    .ec-features-grid {{ grid-template-columns: 1fr; }}
    .ec-nav-links {{ display: none; }}
    .search-mock {{ display: none; }}
}}
</style>
"""


def inject_global_css() -> None:
    """Wstrzyknij wszystkie style Ecombinata. Wywołaj raz po st.set_page_config()."""
    import streamlit as st
    st.markdown(_build_css(), unsafe_allow_html=True)
