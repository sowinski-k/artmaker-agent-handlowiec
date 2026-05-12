"""Ecombinat — central theming for the Streamlit app.

Streamlit's native theming is limited to ~5 colors. Everything else
(sidebar dark mode, typography, card styling, tabs, expanders) is achieved
through aggressive CSS injection on every page load.

Two responsibilities:
  - BRAND constants - palette, fonts, names, used both in CSS and Python
  - inject_global_css() - call once near st.set_page_config()
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
APP_TAGLINE = "Narzędziownik dla e-commerce"
ENV_LABEL = "v0.1"  # widoczne na sidebar przy logu - daje pewność co do wersji

# Top-level modules. Na razie tylko Agenci AI.
MODULES = [
    {
        "key": "agents",
        "label": "Agenci AI",
        "icon": "🤖",  # zastapiony przez Tabler icon w CSS jak chcesz
        "count": 1,
        "active": True,
        "items": [
            {"key": "agent_handlowiec", "label": "Handlowiec cold-email", "active": True},
        ],
    },
]


# ---- CSS payload -----------------------------------------------------------
# Zwracamy jako string żeby łatwo było wstrzykiwać. Nawiasy klamrowe musimy
# escape'ować przez podwojenie {{ }} bo to f-string nie jest.

def _build_css() -> str:
    return f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&family=Space+Grotesk:wght@500;600;700&display=swap');
@import url('https://cdn.jsdelivr.net/npm/@tabler/icons-webfont@3.5.0/dist/tabler-icons.min.css');

/* ─── Foundation: typography + reset ────────────────────────────────────── */

html, body, [class*="css"], .stApp {{
    font-family: 'Inter', -apple-system, system-ui, sans-serif !important;
    color: {INK};
    -webkit-font-smoothing: antialiased;
}}

.stApp {{ background: {BG} !important; }}

/* Tabular numerals dla liczb */
.tabular, .stMetric [data-testid="stMetricValue"] {{
    font-feature-settings: "tnum" !important;
    font-variant-numeric: tabular-nums !important;
}}

/* Mono dla kodu/liczb gdzie chcemy */
code, pre, kbd {{
    font-family: 'JetBrains Mono', monospace !important;
}}

/* ─── Hide Streamlit chrome we don't want ───────────────────────────────── */

#MainMenu {{ visibility: hidden; }}
footer {{ visibility: hidden; }}
header[data-testid="stHeader"] {{
    background: transparent !important;
    height: 0;
}}

/* ─── Main content area ─────────────────────────────────────────────────── */

.main .block-container {{
    padding-top: 1.5rem !important;
    padding-left: 2rem !important;
    padding-right: 2rem !important;
    max-width: 1400px !important;
}}

/* Headings */
h1 {{
    font-family: 'Inter', sans-serif !important;
    font-weight: 600 !important;
    font-size: 22px !important;
    letter-spacing: -0.4px !important;
    color: {INK} !important;
    margin-bottom: 4px !important;
}}

h2 {{
    font-weight: 600 !important;
    font-size: 16px !important;
    letter-spacing: -0.2px !important;
    color: {INK} !important;
}}

h3 {{
    font-weight: 600 !important;
    font-size: 14px !important;
    color: {INK} !important;
}}

/* Body text */
p, label, .stMarkdown {{
    color: {INK};
    font-size: 14px;
}}

small, .stCaption {{
    color: {MUTED} !important;
    font-size: 12.5px !important;
}}

/* ─── Sidebar: DARK theme ─────────────────────────────────────────────── */

section[data-testid="stSidebar"] {{
    background: {GRAPHITE} !important;
    border-right: 1px solid rgba(255,255,255,0.06);
}}

section[data-testid="stSidebar"] * {{
    color: #E5E7EB !important;
}}

section[data-testid="stSidebar"] h1,
section[data-testid="stSidebar"] h2,
section[data-testid="stSidebar"] h3 {{
    color: #FFFFFF !important;
    font-weight: 600 !important;
}}

/* Sidebar headings/labels mute */
section[data-testid="stSidebar"] label {{
    color: rgba(255,255,255,0.5) !important;
    font-size: 11px !important;
    text-transform: uppercase !important;
    letter-spacing: 1.4px !important;
    font-weight: 600 !important;
}}

/* Sidebar inputs - dark variant */
section[data-testid="stSidebar"] .stSelectbox > div > div,
section[data-testid="stSidebar"] .stTextInput input,
section[data-testid="stSidebar"] .stTextArea textarea {{
    background: rgba(255,255,255,0.05) !important;
    border: 1px solid rgba(255,255,255,0.1) !important;
    color: #FFFFFF !important;
}}

section[data-testid="stSidebar"] .stSelectbox > div > div:hover {{
    border-color: rgba(255,255,255,0.2) !important;
}}

/* Sidebar buttons */
section[data-testid="stSidebar"] .stButton button {{
    background: rgba(255,255,255,0.05) !important;
    border: 1px solid rgba(255,255,255,0.1) !important;
    color: #FFFFFF !important;
    font-weight: 500;
}}

section[data-testid="stSidebar"] .stButton button:hover {{
    background: rgba(255,255,255,0.1) !important;
    border-color: rgba(255,255,255,0.2) !important;
}}

/* Sidebar success/error/info boxes */
section[data-testid="stSidebar"] [data-testid="stAlert"] {{
    background: rgba(255,255,255,0.05) !important;
    border: 1px solid rgba(255,255,255,0.1) !important;
}}

/* ─── Tabs ─────────────────────────────────────────────────────────────── */

.stTabs [data-baseweb="tab-list"] {{
    background: transparent !important;
    border-bottom: 1px solid {BORDER};
    gap: 0;
}}

.stTabs [data-baseweb="tab"] {{
    background: transparent !important;
    color: {MUTED} !important;
    border: none !important;
    border-bottom: 2px solid transparent !important;
    padding: 12px 18px !important;
    margin: 0 !important;
    font-weight: 500 !important;
    font-size: 13.5px !important;
    height: auto !important;
}}

.stTabs [data-baseweb="tab"]:hover {{
    color: {INK} !important;
}}

.stTabs [aria-selected="true"] {{
    color: {INK} !important;
    border-bottom: 2px solid {RED} !important;
    font-weight: 600 !important;
}}

/* ─── Buttons ──────────────────────────────────────────────────────────── */

.stButton button {{
    border-radius: 6px !important;
    font-weight: 500 !important;
    font-family: 'Inter', sans-serif !important;
    transition: all 0.15s ease !important;
}}

/* Primary button - red */
.stButton button[kind="primary"] {{
    background: {RED} !important;
    color: white !important;
    border: 1px solid {RED} !important;
}}

.stButton button[kind="primary"]:hover {{
    background: {RED_DARK} !important;
    border-color: {RED_DARK} !important;
    transform: translateY(-1px);
    box-shadow: 0 4px 12px rgba(212,33,44,0.2);
}}

.stButton button[kind="primary"]:active {{
    transform: scale(0.98);
}}

/* Secondary button */
.stButton button[kind="secondary"] {{
    background: {PANEL} !important;
    color: {INK} !important;
    border: 1px solid {BORDER} !important;
}}

.stButton button[kind="secondary"]:hover {{
    border-color: {BORDER_STRONG} !important;
    background: {BG} !important;
}}

/* ─── Inputs ───────────────────────────────────────────────────────────── */

.stTextInput input, .stTextArea textarea, .stSelectbox > div > div,
.stNumberInput input, .stDateInput input {{
    background: {PANEL} !important;
    border: 1px solid {BORDER} !important;
    border-radius: 6px !important;
    font-family: 'Inter', sans-serif !important;
    color: {INK} !important;
}}

.stTextInput input:focus, .stTextArea textarea:focus,
.stNumberInput input:focus {{
    border-color: {RED} !important;
    box-shadow: 0 0 0 3px rgba(212,33,44,0.08) !important;
}}

/* ─── Expanders ────────────────────────────────────────────────────────── */

.streamlit-expanderHeader, [data-testid="stExpander"] details > summary {{
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

[data-testid="stExpander"] details[open] {{
    background: {PANEL};
    border-radius: 8px;
}}

[data-testid="stExpander"] details > div {{
    background: {PANEL};
    border: 1px solid {BORDER};
    border-top: none;
    border-radius: 0 0 8px 8px;
    padding: 16px !important;
}}

/* ─── Metric cards ─────────────────────────────────────────────────────── */

[data-testid="stMetric"] {{
    background: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 14px 16px;
}}

[data-testid="stMetricLabel"] {{
    color: {MUTED} !important;
    font-size: 11.5px !important;
    text-transform: uppercase;
    letter-spacing: 0.8px;
    font-weight: 500 !important;
    margin-bottom: 4px !important;
}}

[data-testid="stMetricValue"] {{
    font-size: 26px !important;
    font-weight: 600 !important;
    letter-spacing: -0.6px !important;
    color: {INK} !important;
    line-height: 1.1 !important;
}}

[data-testid="stMetricDelta"] {{
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 11.5px !important;
}}

/* ─── Tables / dataframes ──────────────────────────────────────────────── */

.stDataFrame, [data-testid="stDataFrame"] {{
    border: 1px solid {BORDER} !important;
    border-radius: 8px !important;
    overflow: hidden;
}}

/* ─── Alerts ───────────────────────────────────────────────────────────── */

[data-testid="stAlert"] {{
    border-radius: 6px !important;
    border-left-width: 3px !important;
    font-size: 13.5px;
}}

/* ─── Progress bars ────────────────────────────────────────────────────── */

.stProgress > div > div {{
    background: {RED} !important;
}}

/* ─── Custom helpers (used by gui/components.py) ───────────────────────── */

.ec-page-head {{
    margin-bottom: 24px;
    padding-bottom: 0;
}}

.ec-page-head h1 {{
    margin: 0 0 4px 0 !important;
    line-height: 1.2;
}}

.ec-page-head .ec-page-sub {{
    color: {MUTED};
    font-size: 13.5px;
}}

.ec-breadcrumb {{
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 12.5px;
    color: {MUTED};
    margin-bottom: 16px;
    font-family: 'Inter', sans-serif;
}}

.ec-breadcrumb i {{
    font-size: 11px;
    color: {MUTED_2};
}}

.ec-breadcrumb .ec-active {{
    color: {INK};
    font-weight: 500;
}}

.ec-badge {{
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: 10.5px;
    font-weight: 600;
    padding: 2px 8px;
    border-radius: 3px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    font-family: 'JetBrains Mono', monospace;
}}

.ec-badge.done {{ background: {BG}; color: {GRAPHITE}; border: 1px solid {BORDER}; }}
.ec-badge.running {{ background: {RED_TINT}; color: {RED_DARK}; }}
.ec-badge.queue {{ background: {BG}; color: {MUTED}; border: 1px solid {BORDER}; }}
.ec-badge.failed {{ background: #fef2f2; color: {RED_DARK}; border: 1px solid #fecaca; }}
.ec-badge.live {{ background: {RED_TINT}; color: {RED_DARK}; }}

.ec-stat-card {{
    background: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 14px 16px;
    height: 100%;
}}

.ec-stat-label {{
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

.ec-stat-label i {{ font-size: 13px; }}

.ec-stat-value {{
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

.ec-stat-value .ec-unit {{
    font-size: 13px;
    color: {MUTED};
    font-weight: 400;
}}

.ec-stat-delta {{
    margin-top: 6px;
    font-size: 11.5px;
    color: {MUTED};
    font-family: 'JetBrains Mono', monospace;
}}

.ec-stat-delta.up {{ color: {RED_DARK}; }}

.ec-section-title {{
    font-size: 13.5px;
    font-weight: 600;
    color: {INK};
    margin: 16px 0 8px;
    display: flex;
    align-items: center;
    gap: 8px;
}}

.ec-section-title i {{
    color: {RED};
    font-size: 15px;
}}

/* Brand header (top of page) */
.ec-brand-header {{
    display: flex;
    align-items: center;
    gap: 12px;
    padding-bottom: 16px;
    margin-bottom: 20px;
    border-bottom: 1px solid {BORDER};
}}

.ec-logo-mark {{
    width: 32px;
    height: 32px;
    background: {RED};
    border-radius: 6px;
    display: flex;
    align-items: center;
    justify-content: center;
    color: white;
    font-weight: 700;
    font-family: 'Space Grotesk', sans-serif;
    font-size: 14px;
    box-shadow: 0 2px 6px rgba(212,33,44,0.2);
    position: relative;
    overflow: hidden;
}}

.ec-logo-mark::after {{
    content: '';
    position: absolute;
    inset: 0;
    background: linear-gradient(135deg, transparent 50%, rgba(0,0,0,0.15) 100%);
}}

.ec-logo-text {{
    font-family: 'Space Grotesk', sans-serif;
    font-weight: 700;
    font-size: 18px;
    letter-spacing: -0.5px;
    color: {INK};
}}

.ec-logo-text .ec-env {{
    font-family: 'JetBrains Mono', monospace;
    font-size: 10px;
    color: {MUTED};
    background: {BG};
    border: 1px solid {BORDER};
    padding: 1px 6px;
    border-radius: 3px;
    margin-left: 8px;
    font-weight: 500;
}}

/* Sidebar navigation items - "MODUŁ" sections */
.ec-sb-section {{
    font-size: 10.5px;
    text-transform: uppercase;
    letter-spacing: 1.4px;
    color: rgba(255,255,255,0.4);
    padding: 12px 0 6px;
    font-weight: 600;
    margin-top: 4px;
}}

.ec-sb-item {{
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 7px 10px;
    border-radius: 6px;
    color: #D1D5DB;
    font-size: 13px;
    margin-bottom: 2px;
}}

.ec-sb-item.active {{
    background: rgba(212,33,44,0.12);
    color: white;
    position: relative;
}}

.ec-sb-item.active::before {{
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

.ec-sb-item i {{ font-size: 16px; width: 16px; }}

.ec-sb-count {{
    margin-left: auto;
    font-family: 'JetBrains Mono', monospace;
    font-size: 10.5px;
    color: rgba(255,255,255,0.5);
}}

.ec-sb-item.active .ec-sb-count {{ color: rgba(255,255,255,0.85); }}

.ec-sb-sub {{
    padding-left: 26px;
    font-size: 12.5px;
    color: rgba(255,255,255,0.7);
    padding-top: 4px;
    padding-bottom: 4px;
}}

.ec-sb-sub.active {{
    color: white;
    font-weight: 500;
}}
</style>
"""


def inject_global_css() -> None:
    """Wstrzyknij CSS Ecombinata. Wywołaj raz na początku app, po set_page_config."""
    import streamlit as st
    st.markdown(_build_css(), unsafe_allow_html=True)
