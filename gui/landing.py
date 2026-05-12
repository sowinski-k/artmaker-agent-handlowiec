"""Ecombinat — landing page (pre-auth).

Pełen marketing page w stylu ecombinat.html, ale dostosowany do faktycznego
zakresu projektu na dziś (jeden moduł = Agenci AI, jeden agent = Handlowiec).
Pozostałe sekcje "coming soon" — vision rozwoju produktu.

Po kliknięciu "Zaloguj" pokazuje się formularz hasła wewnątrz tej samej strony
(session_state flag).
"""
from __future__ import annotations

import streamlit as st


def render_landing(password_required: bool) -> bool:
    """Wyrenderuj pełen landing page. Zwraca True jeśli user przeszedł autoryzację.

    Logika auth:
        - Jeśli password_required=False -> wpuszczamy bez gate'u (lokalny dev)
        - Jeśli password_required=True i session_state['_pw_ok'] -> wpuszczamy
        - Inaczej: pokazuje landing + (jeśli kliknięto "Zaloguj") password form
    """
    import os

    expected = (os.getenv("APP_PASSWORD") or "").strip()

    if not expected:
        return True  # Bez gate'u w dev

    if st.session_state.get("_pw_ok"):
        return True

    # Toggle: pokazujemy landing albo password form
    show_login = st.session_state.get("_show_login", False)

    if show_login:
        _render_login_form(expected)
        if st.button("← Wróć", key="back_to_landing"):
            st.session_state.pop("_show_login", None)
            st.rerun()
        return False
    else:
        _render_marketing_page()
        return False


def _render_login_form(expected: str) -> None:
    """Password form w stylu Ecombinat - karta na ciepłej bieli."""
    st.markdown(
        """
        <div class="ec-landing">
        <nav class="ec-landing-nav">
            <div class="ec-landing-nav-inner">
                <div class="ec-nav-logo">
                    <div class="ec-nav-logo-mark"><i class="ti ti-flame"></i></div>
                    eCombinat
                </div>
            </div>
        </nav>
        <div class="ec-container">
            <div class="ec-login-box">
                <h2>Zaloguj się</h2>
                <p style="color: #6B7280; margin-bottom: 20px;">
                    Wpisz hasło dostępu do panelu Ecombinat.
                </p>
        """,
        unsafe_allow_html=True,
    )
    with st.form("login_form_landing"):
        pw = st.text_input("Hasło", type="password", label_visibility="collapsed", placeholder="Hasło")
        ok = st.form_submit_button("Wejdź do panelu", type="primary", use_container_width=True)
        if ok:
            if pw == expected:
                st.session_state["_pw_ok"] = True
                st.session_state.pop("_show_login", None)
                st.rerun()
            else:
                st.error("Złe hasło.")
    st.markdown("</div></div>", unsafe_allow_html=True)


def _render_marketing_page() -> None:
    """Full Ecombinat landing - hero + features + final CTA + footer.

    UWAGA: "Zaloguj" musi być Streamlit button bo wewnątrz HTML form action
    nie działa - z punktu widzenia interaktywności potrzebujemy session_state.
    """
    # ─── NAV + HERO + LOGOS + FEATURES (HTML) ──────────────────────────
    st.markdown(
        """
        <div class="ec-landing">

        <nav class="ec-landing-nav">
            <div class="ec-landing-nav-inner">
                <div class="ec-nav-logo">
                    <div class="ec-nav-logo-mark"><i class="ti ti-flame"></i></div>
                    eCombinat
                </div>
                <ul class="ec-nav-links">
                    <li><a href="#features">Narzędzia</a></li>
                    <li><a href="#cta">Rozpal piec</a></li>
                </ul>
                <div style="display:flex;gap:12px;align-items:center;">
        """,
        unsafe_allow_html=True,
    )

    # "Zaloguj" musi być real button bo trigger state change
    cols = st.columns([6, 1, 1])
    with cols[1]:
        if st.button("Zaloguj", key="login_btn", use_container_width=True):
            st.session_state["_show_login"] = True
            st.rerun()
    with cols[2]:
        if st.button("Rozpal piec →", type="primary", key="cta_btn", use_container_width=True):
            st.session_state["_show_login"] = True
            st.rerun()

    st.markdown("</div></div></nav>", unsafe_allow_html=True)

    st.markdown(
        """
        <header class="ec-hero">
            <div class="ec-container">
                <div class="ec-hero-grid">
                    <div>
                        <span class="ec-eyebrow"><i class="ti ti-bolt"></i> Polski narzędziownik AI dla e-commerce</span>
                        <h1 class="ec-display">Wykuj <span class="ec-accent">zdjęcia, wideo i opisy</span> swoich produktów w 60 sekund.</h1>
                        <p class="ec-lead">Higgsfield dla sklepów. Zamiast 14 subskrypcji i sesji fotograficznej za 8 000 zł — jeden kombinat, który robi wszystko.</p>

                        <div class="ec-hero-meta">
                            <div class="ec-hero-meta-item"><i class="ti ti-check"></i> Bez karty na start</div>
                            <div class="ec-hero-meta-item"><i class="ti ti-check"></i> Polskie wsparcie</div>
                            <div class="ec-hero-meta-item"><i class="ti ti-check"></i> Faktura VAT</div>
                        </div>
                    </div>

                    <div>
                        <div class="ec-mock">
                            <div class="ec-mock-header">
                                <div class="ec-mock-dot r"></div>
                                <div class="ec-mock-dot y"></div>
                                <div class="ec-mock-dot g"></div>
                                <div class="ec-mock-url">ecombinat.pl/agenci/handlowiec</div>
                            </div>
                            <div class="ec-mock-body">
                                <div class="ec-mock-tabs">
                                    <div class="ec-mock-tab active">Agenci AI</div>
                                    <div class="ec-mock-tab">Hala</div>
                                    <div class="ec-mock-tab">Kuźnia</div>
                                </div>
                                <div class="ec-mock-grid">
                                    <div class="ec-mock-tile t1">
                                        <div class="ec-mock-tile-heart liked"><i class="ti ti-heart"></i></div>
                                        <div class="ec-mock-tile-label">Handlowiec cold-email</div>
                                    </div>
                                    <div class="ec-mock-tile t2">
                                        <div class="ec-mock-tile-heart"><i class="ti ti-heart"></i></div>
                                        <div class="ec-mock-tile-label">Wkrótce</div>
                                    </div>
                                    <div class="ec-mock-tile t3">
                                        <div class="ec-mock-tile-heart"><i class="ti ti-heart"></i></div>
                                        <div class="ec-mock-tile-label">Wkrótce</div>
                                    </div>
                                    <div class="ec-mock-tile t4">
                                        <div class="ec-mock-tile-heart"><i class="ti ti-heart"></i></div>
                                        <div class="ec-mock-tile-label">Wkrótce</div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </header>

        <section class="ec-section" id="features">
            <div class="ec-container">
                <div class="ec-section-head">
                    <h2 class="ec-display">Wszystkie narzędzia w jednej hali</h2>
                    <p>Każdy moduł wykuty pod konkretne zadanie sklepu. Bez 14 subskrypcji, bez 14 loginów.</p>
                </div>

                <div class="ec-features-grid">
                    <div class="ec-feature dark">
                        <span class="ec-feature-tag">Live</span>
                        <div class="ec-feature-icon"><i class="ti ti-robot"></i></div>
                        <h3>Handlowiec cold-email</h3>
                        <p class="ec-feature-desc">Agent AI który pozyskuje leady, researchuje firmy i pisze spersonalizowane maile B2B. Pełen pipeline od Google Maps po Woodpecker.</p>
                    </div>

                    <div class="ec-feature">
                        <span class="ec-feature-tag soon" style="background: #E5E7EB; color: #6B7280;">Wkrótce</span>
                        <div class="ec-feature-icon"><i class="ti ti-photo"></i></div>
                        <h3>Generator zdjęć</h3>
                        <p class="ec-feature-desc">Twój produkt w każdej scenie — od hali fabrycznej po loftowe wnętrza. 4 warianty na raz.</p>
                    </div>

                    <div class="ec-feature">
                        <span class="ec-feature-tag soon" style="background: #E5E7EB; color: #6B7280;">Wkrótce</span>
                        <div class="ec-feature-icon"><i class="ti ti-video"></i></div>
                        <h3>Wideo produktowe</h3>
                        <p class="ec-feature-desc">Klip 6–10 s z ruchem kamery i światłem premium. Pod TikTok, Reels i karty produktu.</p>
                    </div>

                    <div class="ec-feature">
                        <span class="ec-feature-tag soon" style="background: #E5E7EB; color: #6B7280;">Wkrótce</span>
                        <div class="ec-feature-icon"><i class="ti ti-wand"></i></div>
                        <h3>Opisy AI</h3>
                        <p class="ec-feature-desc">SEO-friendly opisy w tonie marki. Polski, angielski, niemiecki — wszystko w jednym kliknięciu.</p>
                    </div>

                    <div class="ec-feature">
                        <span class="ec-feature-tag soon" style="background: #E5E7EB; color: #6B7280;">Wkrótce</span>
                        <div class="ec-feature-icon"><i class="ti ti-eraser"></i></div>
                        <h3>Usuwanie tła</h3>
                        <p class="ec-feature-desc">Czyste wycinki na białym, przezroczystym lub dowolnym tle. Batch do 200 zdjęć.</p>
                    </div>

                    <div class="ec-feature">
                        <span class="ec-feature-tag soon" style="background: #E5E7EB; color: #6B7280;">Wkrótce</span>
                        <div class="ec-feature-icon"><i class="ti ti-arrows-maximize"></i></div>
                        <h3>Upscaler 4K</h3>
                        <p class="ec-feature-desc">Stare zdjęcia z magazynu? Wyciągamy detale i ostrość do druku i Allegro Premium.</p>
                    </div>
                </div>
            </div>
        </section>

        <section class="ec-cta-final" id="cta">
            <div class="ec-container">
                <div class="ec-cta-box">
                    <h2 class="ec-display">Rozpal piec już dziś.</h2>
                    <p>Zacznij od jedynego dostępnego agenta — Handlowca cold-email. Reszta narzędzi wjeżdża wkrótce.</p>
                </div>
            </div>
        </section>

        <footer class="ec-footer">
            <div class="ec-footer-inner">
                <div style="display:flex;align-items:center;gap:10px;font-family:'Space Grotesk',sans-serif;font-weight:700;">
                    <div class="ec-nav-logo-mark" style="width:26px;height:26px;"><i class="ti ti-flame" style="font-size:14px;"></i></div>
                    eCombinat
                </div>
                <div class="ec-footer-links">
                    <a href="#">Regulamin</a>
                    <a href="#">Prywatność</a>
                    <a href="#">Kontakt</a>
                </div>
                <div>© 2026 Ecombinat</div>
            </div>
        </footer>

        </div>
        """,
        unsafe_allow_html=True,
    )
