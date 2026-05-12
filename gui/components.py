"""Ecombinat — reusable HTML components for the dashboard.

Wszystkie return HTML stringi (do wstrzykiwania przez st.markdown z
unsafe_allow_html=True). Komponenty mapują się 1:1 na klasy CSS z gui/theme.py.
"""
from __future__ import annotations

import html as _html
from typing import Literal

import streamlit as st

from gui.theme import APP_NAME, ENV_LABEL


# ═══════════ Brand header (top of dashboard) ════════════════════════════════

def topbar(
    crumbs: list[str],
    *,
    user_initials: str = "MK",
    show_search: bool = True,
    show_notifications: bool = True,
) -> None:
    """Render topbar w stylu ecombinat-dashboard.html.

    Args:
        crumbs: lista breadcrumbs (ostatni będzie pogrubiony)
        user_initials: 2 znaki w kółku avatara
        show_search: pokaż search mock (decorative, nie funkcjonalny)
        show_notifications: pokaż dzwoneczek z dot
    """
    parts = []
    for i, c in enumerate(crumbs):
        safe = _html.escape(c)
        if i == 0:
            parts.append(f"<span>{safe}</span>")
        else:
            parts.append('<i class="ti ti-chevron-right"></i>')
            if i == len(crumbs) - 1:
                parts.append(f"<strong>{safe}</strong>")
            else:
                parts.append(f"<span>{safe}</span>")

    crumb_html = "".join(parts)

    search_html = (
        '<div class="search-mock">'
        '<i class="ti ti-search"></i>'
        '<span>Szukaj leadów, kampanii, ustawień…</span>'
        '<span class="kbd">⌘K</span>'
        '</div>'
        if show_search else '<div style="margin-left:auto;"></div>'
    )

    buttons_html = (
        '<button class="topbtn" title="Powiadomienia"><i class="ti ti-bell"></i><span class="dot"></span></button>'
        '<button class="topbtn" title="Pomoc"><i class="ti ti-help"></i></button>'
        if show_notifications else ""
    )

    st.markdown(
        f"""
        <div class="topbar">
            <div class="crumb">{crumb_html}</div>
            {search_html}
            {buttons_html}
            <div class="avatar">{_html.escape(user_initials)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def page_head(
    title: str,
    *,
    subtitle: str | None = None,
    last_update: str | None = None,
    right_widget: str | None = None,
) -> None:
    """Page head: tytuł + meta po lewej, opcjonalny widget po prawej (np. time range)."""
    sub_parts = []
    if subtitle:
        sub_parts.append(_html.escape(subtitle))
    if last_update:
        sub_parts.append(f'<span class="mono">·</span> <span class="last-update">{_html.escape(last_update)}</span>')
    sub_html = (
        f'<p>{" ".join(sub_parts)}</p>' if sub_parts else ""
    )

    right_html = right_widget or ""

    st.markdown(
        f"""
        <div class="page-head">
            <div>
                <h1>{_html.escape(title)}</h1>
                {sub_html}
            </div>
            <div>{right_html}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ═══════════ Stat cards ═════════════════════════════════════════════════════

def _sparkline_svg(points: list[float], color: str = "#D4212C") -> str:
    """Generuj SVG sparkline z normalized punktów (0-1)."""
    if not points or len(points) < 2:
        return ""
    width, height = 80, 28
    n = len(points)
    pmin, pmax = min(points), max(points)
    if pmax == pmin:
        # Flat line
        ys = [height // 2] * n
    else:
        ys = [
            height - int((p - pmin) / (pmax - pmin) * (height - 4)) - 2
            for p in points
        ]
    xs = [int(i * width / (n - 1)) for i in range(n)]
    points_str = " ".join(f"{x},{y}" for x, y in zip(xs, ys))
    return (
        f'<svg class="stat-spark" width="{width}" height="{height}" viewBox="0 0 {width} {height}">'
        f'<polyline fill="none" stroke="{color}" stroke-width="1.5" points="{points_str}" />'
        f'</svg>'
    )


def stat(
    label: str,
    value: str | int | float,
    *,
    unit: str | None = None,
    delta: str | None = None,
    delta_dir: Literal["up", "down", "flat"] = "flat",
    icon: str | None = None,
    sparkline: list[float] | None = None,
    spark_color: str = "#D4212C",
) -> str:
    """Pojedyncza stat card (HTML string do umieszczenia w st.columns).

    Args:
        label: short uppercase label
        value: główna wartość (np. 1284)
        unit: opcjonalna jednostka (np. "%", "/ 10")
        delta: opcjonalny opis zmiany (np. "+32% vs poprzedni")
        delta_dir: kolor delty - up=red, flat=muted
        icon: Tabler icon name (bez prefixu "ti-")
        sparkline: lista 4-12 floatów dla trend mini-charta
        spark_color: kolor sparkline (default red)
    """
    icon_html = (
        f'<i class="ti ti-{_html.escape(icon)}"></i>' if icon else ""
    )
    unit_html = (
        f'<span class="unit">{_html.escape(unit)}</span>' if unit else ""
    )
    delta_arrow = ""
    if delta_dir == "up":
        delta_arrow = '<i class="ti ti-arrow-up-right"></i>'
    delta_html = (
        f'<div class="stat-delta {delta_dir}">{delta_arrow}{_html.escape(delta)}</div>'
        if delta else ""
    )
    spark_html = _sparkline_svg(sparkline, spark_color) if sparkline else ""

    return f"""
    <div class="stat">
        <div class="stat-label">{icon_html}{_html.escape(label)}</div>
        <div class="stat-value tabular">{_html.escape(str(value))}{unit_html}</div>
        {delta_html}
        {spark_html}
    </div>
    """


# ═══════════ Cards (generic container) ══════════════════════════════════════

def card_head(title: str, *, icon: str | None = None, right_html: str = "") -> str:
    """Standalone card head (do otwarcia karty przez st.markdown z body via st.container)."""
    icon_html = f'<i class="ti ti-{_html.escape(icon)}"></i>' if icon else ""
    return f"""
    <div class="ec-card">
        <div class="card-head">
            <div class="card-title">{icon_html}{_html.escape(title)}</div>
            <div class="card-actions">{right_html}</div>
        </div>
    """


def card_close() -> str:
    return "</div>"


# ═══════════ Badge ══════════════════════════════════════════════════════════

def badge(text: str, kind: Literal["done", "running", "queue", "failed", "live"] = "queue") -> str:
    return f'<span class="ec-badge {kind}">{_html.escape(text)}</span>'


# ═══════════ Funnel ═════════════════════════════════════════════════════════

def funnel(
    rows: list[dict],
    *,
    accent_first: bool = True,
    footer_label: str | None = None,
    footer_value: str | None = None,
) -> None:
    """Funnel chart card.

    Args:
        rows: lista dictów z keys: label, value, percent, icon (opcjonalnie)
        accent_first: pierwsze 2 wiersze na czerwono (jak w HTML wzorze)
        footer_label/value: opcjonalny footer pod funnelem
    """
    html_rows = []
    for i, row in enumerate(rows):
        icon = row.get("icon")
        icon_html = f'<i class="ti ti-{_html.escape(icon)}"></i>' if icon else ""
        label = _html.escape(str(row.get("label", "")))
        value = _html.escape(str(row.get("value", "")))
        percent = float(row.get("percent", 0))
        fill_class = "funnel-fill red" if accent_first and i < 2 else "funnel-fill"
        # Kolory pochodne dla pozostałych wierszy
        bg = ""
        if not (accent_first and i < 2):
            shades = ["#2A2A2A", "#444", "#666"]
            if i - 2 < len(shades):
                bg = f"background: {shades[i - 2]};"
        html_rows.append(f"""
            <div class="funnel-row">
                <div class="funnel-label">{icon_html}{label}</div>
                <div class="funnel-bar">
                    <div class="{fill_class}" style="width: {percent}%;{bg}">{value}</div>
                </div>
                <div class="funnel-num">{percent:.1f}%</div>
            </div>
        """)

    footer_html = ""
    if footer_label and footer_value:
        footer_html = f"""
        <div style="border-top: 1px solid #E5E7EB; margin-top: 14px; padding-top: 12px;
                    font-size: 12px; color: #6B7280; display: flex; justify-content: space-between;">
            <span>{_html.escape(footer_label)}</span>
            <strong class="mono" style="color: #111111; font-weight: 600;">{_html.escape(footer_value)}</strong>
        </div>
        """

    st.markdown(
        f"""
        <div class="card-body">
            <div class="funnel">
                {"".join(html_rows)}
            </div>
            {footer_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


# ═══════════ Activity feed ══════════════════════════════════════════════════

def activity_feed(items: list[dict]) -> None:
    """Lista zdarzeń (act-item) z ikoną, tekstem i czasem.

    Each item dict:
        text: str  (z możliwymi <strong>...</strong> dla emfazy)
        time: str  (np. "14:32")
        icon: str  (Tabler icon bez prefixu)
        accent: bool  (czerwony icon czy szary)
    """
    rows = []
    for item in items:
        icon = item.get("icon", "circle-dot")
        accent = "red" if item.get("accent") else ""
        text = item.get("text", "")  # ALLOWED HTML for <strong> - upstream validates
        time = _html.escape(item.get("time", ""))
        rows.append(f"""
            <div class="act-item">
                <div class="act-ico {accent}"><i class="ti ti-{_html.escape(icon)}"></i></div>
                <div class="act-text">{text}</div>
                <span class="act-time">{time}</span>
            </div>
        """)
    st.markdown(
        f'<div class="activity">{"".join(rows)}</div>',
        unsafe_allow_html=True,
    )


# ═══════════ System status rows ═════════════════════════════════════════════

def system_status(rows: list[dict]) -> None:
    """sys-row list z status dotami.

    Each row dict:
        label: str
        value: str
        status: 'ok' | 'warn' | 'err' | None (None = no dot)
    """
    html_rows = []
    for r in rows:
        status = r.get("status")
        dot_html = f'<span class="status-dot {status}"></span>' if status else ""
        html_rows.append(f"""
            <div class="sys-row">
                <span class="sys-label">{dot_html}{_html.escape(r.get("label", ""))}</span>
                <span class="sys-val">{_html.escape(r.get("value", ""))}</span>
            </div>
        """)
    st.markdown("".join(html_rows), unsafe_allow_html=True)


# ═══════════ Data table (.tbl) ══════════════════════════════════════════════

def data_table(headers: list[dict], rows: list[list[str]]) -> None:
    """Render .tbl styled table.

    Args:
        headers: lista dictów: {label, num (bool)}
        rows: list of list of strings (komórki). Strings są wstawiane jako HTML
              dla flexibility (np. <span class='delta-pos'>+34%</span>)
    """
    th = "".join(
        f'<th class="num">{_html.escape(h["label"])}</th>'
        if h.get("num") else
        f'<th>{_html.escape(h["label"])}</th>'
        for h in headers
    )
    body = []
    for row in rows:
        tds = "".join(
            f'<td class="num">{cell}</td>' if headers[i].get("num") else f'<td>{cell}</td>'
            for i, cell in enumerate(row)
        )
        body.append(f"<tr>{tds}</tr>")
    st.markdown(
        f'<table class="tbl"><thead><tr>{th}</tr></thead><tbody>{"".join(body)}</tbody></table>',
        unsafe_allow_html=True,
    )


# ═══════════ Sidebar nav helpers ════════════════════════════════════════════

def sb_logo() -> None:
    """Logo Ecombinat w sidebar."""
    st.markdown(
        f"""
        <div class="sb-logo">
            <div class="sb-logo-mark"><i class="ti ti-flame"></i></div>
            <div class="sb-logo-text">{_html.escape(APP_NAME.lower())}</div>
            <span class="sb-logo-env">{_html.escape(ENV_LABEL)}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def sb_section(title: str) -> None:
    st.markdown(
        f'<div class="sb-section">{_html.escape(title)}</div>',
        unsafe_allow_html=True,
    )


def sb_item(
    label: str,
    *,
    icon: str | None = None,
    count: int | str | None = None,
    active: bool = False,
    disabled: bool = False,
) -> None:
    classes = ["sb-item"]
    if active:
        classes.append("active")
    if disabled:
        classes.append("disabled")
    icon_html = f'<i class="ti ti-{_html.escape(icon)}"></i>' if icon else ""
    count_html = (
        f'<span class="sb-count">{_html.escape(str(count))}</span>'
        if count is not None else ""
    )
    st.markdown(
        f'<div class="{" ".join(classes)}">{icon_html}<span>{_html.escape(label)}</span>{count_html}</div>',
        unsafe_allow_html=True,
    )


def sb_foot(*, credits_used: int, credits_total: int, renews_label: str) -> None:
    """Footer sidebara - meter kredytów (token usage)."""
    pct = (credits_used / credits_total * 100) if credits_total else 0
    pct = max(0, min(100, pct))
    st.markdown(
        f"""
        <div class="sb-foot">
            <div class="sb-foot-row">Kredyty <strong>{credits_used} / {credits_total}</strong></div>
            <div class="sb-bar"><div style="width:{pct:.0f}%"></div></div>
            <div class="sb-foot-row" style="margin-bottom:0;">Odnowienie <strong>{_html.escape(renews_label)}</strong></div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ═══════════ Time range pill picker ═════════════════════════════════════════

def time_range_html(options: list[str], active: str) -> str:
    """HTML for time range picker (do umieszczenia w page_head right_widget).

    UWAGA: to jest decorative HTML - interaktywność wymaga Streamlit native widgets.
    Dla MVP wystarczy pokaz wzorca, w przyszłości przepiąć na faktyczny stan.
    """
    btns = []
    for opt in options:
        cls = "active" if opt == active else ""
        btns.append(f'<button class="{cls}">{_html.escape(opt)}</button>')
    return f'<div class="timerange">{"".join(btns)}</div>'
