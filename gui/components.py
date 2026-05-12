"""Ecombinat — reusable HTML components.

Streamlit ma ograniczone natywne komponenty UI. Tutaj custom HTML
helpers w stylu Ecombinat dashboard, używane przez st.markdown z
unsafe_allow_html=True.

Wszystkie funkcje zwracają string (HTML) - wstrzykiwany przez st.markdown.
Nie używają streamlit imports oprócz `st.markdown` w "render_*" wrapperach.
"""
from __future__ import annotations

import html as _html
from typing import Literal

import streamlit as st

from gui.theme import (
    APP_NAME,
    BORDER,
    BORDER_STRONG,
    ENV_LABEL,
    INK,
    MUTED,
    PANEL,
    RED,
    RED_DARK,
)


# ---- Top-of-page header + breadcrumb ---------------------------------------

def brand_header() -> None:
    """Logo Ecombinat z env tagiem. Na samej górze każdej strony."""
    initial = APP_NAME[0].upper()
    st.markdown(
        f"""
        <div class="ec-brand-header">
            <div class="ec-logo-mark">{initial}</div>
            <div class="ec-logo-text">
                {APP_NAME.lower()}
                <span class="ec-env">{ENV_LABEL}</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def breadcrumb(*crumbs: str) -> None:
    """Breadcrumb: 'Ecombinat → Agenci AI → Handlowiec cold-email'.

    Ostatni crumb jest pogrubiony (active). Renderowane przed page_header.
    """
    parts = []
    for i, c in enumerate(crumbs):
        safe = _html.escape(c)
        if i == len(crumbs) - 1:
            parts.append(f'<span class="ec-active">{safe}</span>')
        else:
            parts.append(f'<span>{safe}</span>')
            parts.append('<i class="ti ti-chevron-right"></i>')
    inner = "".join(parts)
    st.markdown(f'<div class="ec-breadcrumb">{inner}</div>', unsafe_allow_html=True)


def page_header(title: str, subtitle: str | None = None) -> None:
    """Tytuł strony + opcjonalny podtytuł. Po brand_header() i breadcrumb()."""
    safe_title = _html.escape(title)
    sub_html = (
        f'<div class="ec-page-sub">{_html.escape(subtitle)}</div>'
        if subtitle else ""
    )
    st.markdown(
        f"""
        <div class="ec-page-head">
            <h1>{safe_title}</h1>
            {sub_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


# ---- Stat cards ------------------------------------------------------------

def stat_card(
    label: str,
    value: str | int | float,
    *,
    unit: str | None = None,
    delta: str | None = None,
    delta_dir: Literal["up", "down", "flat"] = "flat",
    icon: str | None = None,
) -> str:
    """Pojedyncza stat card. Zwraca HTML jako string żeby wciskać w columns.

    Użycie:
        c1, c2, c3, c4 = st.columns(4)
        c1.markdown(stat_card("Leady", 142), unsafe_allow_html=True)
    """
    icon_html = (
        f'<i class="ti ti-{_html.escape(icon)}"></i>' if icon else ""
    )
    unit_html = (
        f'<span class="ec-unit">{_html.escape(unit)}</span>' if unit else ""
    )
    delta_class = f"ec-stat-delta {delta_dir}" if delta else "ec-stat-delta"
    delta_html = (
        f'<div class="{delta_class}">{_html.escape(delta)}</div>' if delta else ""
    )
    return f"""
    <div class="ec-stat-card">
        <div class="ec-stat-label">{icon_html}{_html.escape(label)}</div>
        <div class="ec-stat-value">{_html.escape(str(value))}{unit_html}</div>
        {delta_html}
    </div>
    """


def badge(text: str, kind: Literal["done", "running", "queue", "failed", "live"] = "queue") -> str:
    """Mała etykieta statusu (success/error/running). Wkleisz w table cell albo
    jako inline w innym HTML.
    """
    return f'<span class="ec-badge {kind}">{_html.escape(text)}</span>'


def section_title(text: str, icon: str | None = None) -> None:
    """Tytuł sekcji w środku strony (np. 'Ostatnie zdarzenia', 'Leady w bazie').

    Mniejszy niż page_header h1, z czerwoną ikoną Tabler obok.
    """
    icon_html = (
        f'<i class="ti ti-{_html.escape(icon)}"></i>' if icon else ""
    )
    st.markdown(
        f'<div class="ec-section-title">{icon_html}{_html.escape(text)}</div>',
        unsafe_allow_html=True,
    )


# ---- Sidebar nav -----------------------------------------------------------

def sidebar_nav_section(title: str) -> None:
    """Nagłówek sekcji w sidebar (np. 'MODUŁY', 'USTAWIENIA')."""
    st.markdown(
        f'<div class="ec-sb-section">{_html.escape(title)}</div>',
        unsafe_allow_html=True,
    )


def sidebar_nav_item(
    label: str,
    *,
    icon: str | None = None,
    count: int | str | None = None,
    active: bool = False,
) -> None:
    """Pozycja nawigacji w sidebar. Active dodaje czerwoną pionową kreskę po lewej."""
    cls = "ec-sb-item active" if active else "ec-sb-item"
    icon_html = (
        f'<i class="ti ti-{_html.escape(icon)}"></i>' if icon else ""
    )
    count_html = (
        f'<span class="ec-sb-count">{_html.escape(str(count))}</span>'
        if count is not None else ""
    )
    st.markdown(
        f'<div class="{cls}">{icon_html}<span>{_html.escape(label)}</span>{count_html}</div>',
        unsafe_allow_html=True,
    )


def sidebar_nav_subitem(label: str, *, active: bool = False) -> None:
    """Item drugiego poziomu w sidebar (np. konkretny agent pod 'Agenci AI')."""
    cls = "ec-sb-sub active" if active else "ec-sb-sub"
    st.markdown(
        f'<div class="{cls}">{_html.escape(label)}</div>',
        unsafe_allow_html=True,
    )
