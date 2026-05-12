"""Ecombinat — pre-auth login page.

Streamlit ma fundamentalny problem: gdy wstrzykujesz Streamlit components
(st.button, st.columns, st.form) WEWNĄTRZ HTML markdown, Streamlit renderuje
je jako OSOBNE DOM blocki — łamiąc strukturę otaczającego HTML. Czyli pełny
marketing landing ze "Zaloguj" przyciskiem w nav-barze nie jest możliwy.

Praktyczne rozwiązanie: pre-login = wycentrowana karta z hasłem w stylu
Ecombinata. Pełen marketing (hero/features/pricing) jest osobno - dostępny
PO zalogowaniu jako "Witaj" tab albo dedykowana statyczna strona na Cloudflare
Pages w przyszłości (gdy zaczniesz sprzedawać innym).
"""
from __future__ import annotations

import os

import streamlit as st


def render_landing(password_required: bool = True) -> bool:
    """Pre-auth gate. Returns True gdy user zalogowany (lub gate wyłączony).

    Bez APP_PASSWORD env -> wpuszczamy (lokalny dev).
    Z APP_PASSWORD i poprawnym hasłem -> wpuszczamy.
    Inaczej -> pokazuje login card.
    """
    expected = (os.getenv("APP_PASSWORD") or "").strip()
    if not expected:
        return True
    if st.session_state.get("_pw_ok"):
        return True

    _render_login_card(expected)
    return False


def _render_login_card(expected: str) -> None:
    """Wycentrowana karta z hasłem w stylu Ecombinat."""
    # Cała strona dostaje tło bez paddingu sidebarów
    st.markdown(
        """
        <style>
            section[data-testid="stSidebar"] { display: none !important; }
            .main .block-container {
                padding-top: 0 !important;
                max-width: 100% !important;
            }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # Top nav (czysty HTML, bez Streamlit widgets w środku)
    st.markdown(
        """
        <div style="background:#FAFAF7;min-height:100vh;margin:-1rem -1.5rem -4rem -1.5rem;padding-top:0;">
            <nav style="position:sticky;top:0;z-index:50;background:rgba(250,250,247,0.85);
                        backdrop-filter:saturate(180%) blur(12px);
                        border-bottom:1px solid #E5E7EB;padding:16px 24px;">
                <div style="max-width:1200px;margin:0 auto;display:flex;align-items:center;justify-content:space-between;">
                    <div style="display:flex;align-items:center;gap:10px;font-family:'Space Grotesk',sans-serif;font-weight:700;font-size:18px;">
                        <div style="width:32px;height:32px;background:#D4212C;border-radius:8px;
                                    display:flex;align-items:center;justify-content:center;color:#fff;
                                    position:relative;overflow:hidden;">
                            <i class="ti ti-flame" style="font-size:18px;"></i>
                        </div>
                        eCombinat
                    </div>
                    <div style="font-size:13px;color:#6B7280;font-family:'JetBrains Mono',monospace;">
                        v0.1 · production
                    </div>
                </div>
            </nav>

            <div style="max-width:480px;margin:80px auto 40px;padding:0 24px;">
                <div style="background:#FFFFFF;border:1px solid #E5E7EB;border-radius:16px;padding:36px;
                            box-shadow:0 10px 30px -10px rgba(0,0,0,0.08);">
                    <div style="display:inline-flex;align-items:center;gap:8px;padding:6px 14px;
                                background:#FDECED;color:#8F1018;border-radius:999px;
                                font-size:12.5px;font-weight:600;margin-bottom:24px;
                                border:1px solid rgba(212,33,44,0.15);">
                        <i class="ti ti-bolt"></i> Polski narzędziownik AI dla e-commerce
                    </div>
                    <h2 style="font-family:'Space Grotesk',sans-serif;font-size:28px;
                               font-weight:700;letter-spacing:-0.02em;color:#111111;
                               margin:0 0 8px 0;line-height:1.1;">
                        Wejdź do hali kombinatu
                    </h2>
                    <p style="color:#6B7280;font-size:14.5px;margin-bottom:28px;">
                        Zaloguj się żeby kontynuować pracę z agentami AI. Aktualnie
                        dostępny: <strong style="color:#111;">Handlowiec cold-email</strong>.
                    </p>
        """,
        unsafe_allow_html=True,
    )

    # Streamlit form - rendered AS A BLOCK, po HTML strukturze powyżej
    with st.form("login_form", clear_on_submit=False):
        pw = st.text_input(
            "Hasło",
            type="password",
            label_visibility="collapsed",
            placeholder="Wpisz hasło dostępu",
        )
        ok = st.form_submit_button("Wejdź do panelu →", type="primary", use_container_width=True)
        if ok:
            if pw == expected:
                st.session_state["_pw_ok"] = True
                st.rerun()
            else:
                st.error("Złe hasło.")

    # Zamknięcie HTML
    st.markdown(
        """
                    <div style="margin-top:20px;padding-top:20px;border-top:1px solid #E5E7EB;
                                font-size:12px;color:#9CA3AF;display:flex;justify-content:space-between;">
                        <span>Brak hasła? Skontaktuj się z administratorem.</span>
                        <span style="font-family:'JetBrains Mono',monospace;">ENV: production</span>
                    </div>
                </div>

                <div style="text-align:center;margin-top:32px;color:#6B7280;font-size:13px;">
                    Wkrótce: Generator zdjęć · Wideo · Opisy AI · Usuń tło · Upscaler 4K
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
