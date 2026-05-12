/* Ecombinat - landing page (1:1 z ecombinat.html, konwersja HTML -> JSX).
 * Server Component - renderuje pelne SSR, SEO friendly.
 * CSS inline w <style> bo to one-off styling tej konkretnej strony.
 */

import Link from 'next/link';

export default function LandingPage() {
  return (
    <>
      <style dangerouslySetInnerHTML={{ __html: LANDING_CSS }} />

      <nav className="landing-nav">
        <div className="landing-nav-inner">
          <div className="logo">
            <div className="logo-mark"><i className="ti ti-flame"></i></div>
            eCombinat
          </div>
          <ul className="nav-links">
            <li><a href="#features">Narzędzia</a></li>
            <li><a href="#showcase">Realizacje</a></li>
            <li><a href="#pricing">Cennik</a></li>
            <li><a href="#">Blog</a></li>
          </ul>
          <div className="nav-cta">
            <Link href="/login" className="btn btn-ghost">Zaloguj</Link>
            <Link href="/login" className="btn btn-primary">
              Rozpal piec <i className="ti ti-arrow-right"></i>
            </Link>
          </div>
        </div>
      </nav>

      <header className="hero">
        <div className="container">
          <div className="hero-grid">
            <div>
              <span className="eyebrow">
                <i className="ti ti-bolt"></i> Polski narzędziownik AI dla e-commerce
              </span>
              <h1 className="display">
                Wykuj <span className="accent">zdjęcia, wideo i opisy</span> swoich produktów w 60 sekund.
              </h1>
              <p className="lead">
                Higgsfield dla sklepów. Zamiast 14 subskrypcji i sesji fotograficznej za 8 000 zł
                - jeden kombinat, który robi wszystko.
              </p>

              <div className="hero-actions">
                <Link href="/login" className="btn btn-primary btn-lg">
                  Wystartuj za darmo <i className="ti ti-arrow-right"></i>
                </Link>
                <a href="#features" className="btn btn-ghost btn-lg">
                  <i className="ti ti-player-play"></i> Zobacz funkcje
                </a>
              </div>

              <div className="hero-meta">
                <div className="hero-meta-item"><i className="ti ti-check"></i> 50 darmowych kredytów</div>
                <div className="hero-meta-item"><i className="ti ti-check"></i> Bez karty</div>
                <div className="hero-meta-item"><i className="ti ti-check"></i> Faktura VAT</div>
              </div>
            </div>

            <div className="hero-visual">
              <div className="mock">
                <div className="mock-header">
                  <div className="mock-dot r"></div>
                  <div className="mock-dot y"></div>
                  <div className="mock-dot g"></div>
                  <div className="mock-url">ecombinat.pl/agenci/handlowiec</div>
                </div>
                <div className="mock-body">
                  <div className="mock-tabs">
                    <div className="mock-tab active">Agenci AI</div>
                    <div className="mock-tab">Studio</div>
                    <div className="mock-tab">Plener</div>
                  </div>
                  <div className="mock-grid">
                    <div className="mock-tile t1">
                      <div className="mock-tile-heart liked"><i className="ti ti-heart"></i></div>
                      <div className="mock-tile-label">Handlowiec</div>
                    </div>
                    <div className="mock-tile t2">
                      <div className="mock-tile-heart"><i className="ti ti-heart"></i></div>
                      <div className="mock-tile-label">Wkrótce</div>
                    </div>
                    <div className="mock-tile t3">
                      <div className="mock-tile-heart"><i className="ti ti-heart"></i></div>
                      <div className="mock-tile-label">Wkrótce</div>
                    </div>
                    <div className="mock-tile t4">
                      <div className="mock-tile-heart"><i className="ti ti-heart"></i></div>
                      <div className="mock-tile-label">Wkrótce</div>
                    </div>
                  </div>
                </div>
              </div>

              <div className="float-badge b1">
                <div className="ok"><i className="ti ti-check"></i></div>
                Wykute w 47 s
              </div>
              <div className="float-badge b2">
                <i className="ti ti-trending-up"></i>
                CTR +124%
              </div>
            </div>
          </div>
        </div>
      </header>

      <section className="logos">
        <div className="container">
          <div className="logos-label">Zaufali nam ludzie z</div>
          <div className="logos-row">
            <div className="logo-fake"><i className="ti ti-building-store"></i> Allegro</div>
            <div className="logo-fake"><i className="ti ti-shopping-bag"></i> Shoper</div>
            <div className="logo-fake"><i className="ti ti-package"></i> InPost</div>
            <div className="logo-fake"><i className="ti ti-brand-shopify"></i> Shopify</div>
            <div className="logo-fake"><i className="ti ti-truck"></i> Booksy</div>
            <div className="logo-fake"><i className="ti ti-bolt"></i> Empik</div>
          </div>
        </div>
      </section>

      <section className="features" id="features">
        <div className="container">
          <div className="section-head">
            <h2 className="display">Wszystkie narzędzia w jednej hali</h2>
            <p>Każdy moduł wykuty pod konkretne zadanie sklepu. Bez 14 subskrypcji, bez 14 loginów, bez 14 zakładek.</p>
          </div>

          <div className="features-grid">
            <div className="feature dark">
              <span className="feature-tag">Live</span>
              <div className="feature-icon"><i className="ti ti-robot"></i></div>
              <h3>Handlowiec cold-email</h3>
              <p className="feature-desc">
                Agent AI który pozyskuje leady, researchuje firmy i pisze spersonalizowane maile B2B. Pełen pipeline od Google Maps po Woodpecker.
              </p>
            </div>

            <div className="feature">
              <span className="feature-tag" style={{ background: '#E5E7EB', color: '#6B7280' }}>Wkrótce</span>
              <div className="feature-icon"><i className="ti ti-photo"></i></div>
              <h3>Generator zdjęć</h3>
              <p className="feature-desc">Twój produkt w każdej scenie - od hali fabrycznej po loftowe wnętrza. 4 warianty na raz.</p>
            </div>

            <div className="feature">
              <span className="feature-tag" style={{ background: '#E5E7EB', color: '#6B7280' }}>Wkrótce</span>
              <div className="feature-icon"><i className="ti ti-video"></i></div>
              <h3>Wideo produktowe</h3>
              <p className="feature-desc">Klip 6-10 s z ruchem kamery i światłem premium. Pod TikTok, Reels i karty produktu.</p>
            </div>

            <div className="feature">
              <span className="feature-tag" style={{ background: '#E5E7EB', color: '#6B7280' }}>Wkrótce</span>
              <div className="feature-icon"><i className="ti ti-wand"></i></div>
              <h3>Opisy AI</h3>
              <p className="feature-desc">SEO-friendly opisy w tonie marki. Polski, angielski, niemiecki - wszystko w jednym kliknięciu.</p>
            </div>

            <div className="feature">
              <span className="feature-tag" style={{ background: '#E5E7EB', color: '#6B7280' }}>Wkrótce</span>
              <div className="feature-icon"><i className="ti ti-eraser"></i></div>
              <h3>Usuwanie tła</h3>
              <p className="feature-desc">Czyste wycinki na białym, przezroczystym lub dowolnym tle. Batch do 200 zdjęć.</p>
            </div>

            <div className="feature">
              <span className="feature-tag" style={{ background: '#E5E7EB', color: '#6B7280' }}>Wkrótce</span>
              <div className="feature-icon"><i className="ti ti-arrows-maximize"></i></div>
              <h3>Upscaler 4K</h3>
              <p className="feature-desc">Stare zdjęcia z magazynu? Wyciągamy detale i ostrość do druku i Allegro Premium.</p>
            </div>
          </div>
        </div>
      </section>

      <section className="cta-final">
        <div className="container">
          <div className="cta-box">
            <h2 className="display">Rozpal piec już dziś.</h2>
            <p>Zacznij od jedynego dostępnego agenta - Handlowca cold-email. Reszta narzędzi wjeżdża wkrótce.</p>
            <div className="cta-actions">
              <Link href="/login" className="btn btn-primary btn-lg">
                Zacznij za darmo <i className="ti ti-arrow-right"></i>
              </Link>
              <a href="mailto:kontakt@ecombinat.pl" className="btn btn-white btn-lg">
                <i className="ti ti-calendar"></i> Umów demo
              </a>
            </div>
          </div>
        </div>
      </section>

      <footer className="landing-footer">
        <div className="container footer-inner">
          <div className="logo" style={{ fontSize: '15px' }}>
            <div className="logo-mark" style={{ width: '26px', height: '26px' }}>
              <i className="ti ti-flame" style={{ fontSize: '14px' }}></i>
            </div>
            eCombinat
          </div>
          <div className="footer-links">
            <a href="#">Regulamin</a>
            <a href="#">Prywatność</a>
            <a href="mailto:kontakt@ecombinat.pl">Kontakt</a>
            <a href="#">Status</a>
          </div>
          <div>© 2026 eCombinat sp. z o.o.</div>
        </div>
      </footer>
    </>
  );
}

const LANDING_CSS = `
.landing-nav {
  position: sticky;
  top: 0;
  z-index: 50;
  background: rgba(250, 250, 247, 0.85);
  backdrop-filter: saturate(180%) blur(12px);
  -webkit-backdrop-filter: saturate(180%) blur(12px);
  border-bottom: 1px solid var(--border);
}
.landing-nav-inner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 24px;
  max-width: 1200px;
  margin: 0 auto;
}
.logo {
  display: flex;
  align-items: center;
  gap: 10px;
  font-family: 'Space Grotesk', sans-serif;
  font-weight: 700;
  font-size: 18px;
  letter-spacing: -0.5px;
}
.logo-mark {
  width: 32px; height: 32px;
  background: var(--red);
  border-radius: 8px;
  display: flex; align-items: center; justify-content: center;
  color: #fff;
  position: relative;
  overflow: hidden;
}
.logo-mark::after {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(135deg, transparent 50%, rgba(0,0,0,0.2) 100%);
}
.logo-mark i { font-size: 18px; position: relative; z-index: 1; }
.nav-links { display: flex; gap: 28px; list-style: none; }
.nav-links a { color: var(--ink); font-size: 14px; font-weight: 500; transition: color 0.2s; }
.nav-links a:hover { color: var(--red); }
.nav-cta { display: flex; gap: 12px; align-items: center; }
.btn {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 10px 18px;
  border-radius: var(--radius-sm);
  font-size: 14px;
  font-weight: 500;
  border: none;
  cursor: pointer;
  transition: transform 0.15s, background 0.2s, box-shadow 0.2s;
}
.btn:active { transform: scale(0.97); }
.btn-ghost { background: transparent; color: var(--ink); }
.btn-ghost:hover { background: var(--border); }
.btn-primary { background: var(--red); color: #fff; box-shadow: 0 1px 2px rgba(143, 16, 24, 0.1); }
.btn-primary:hover { background: var(--red-dark); box-shadow: 0 4px 12px rgba(212, 33, 44, 0.25); }
.btn-dark { background: var(--graphite); color: #fff; }
.btn-dark:hover { background: #000; }
.btn-white { background: #fff; color: var(--ink); }
.btn-white:hover { background: var(--border); }
.btn-lg { padding: 14px 24px; font-size: 15px; }

/* HERO */
.hero { padding: 80px 0 60px; position: relative; }
.hero-grid {
  display: grid;
  grid-template-columns: 1.05fr 1fr;
  gap: 60px;
  align-items: center;
}
.eyebrow {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 6px 14px;
  background: var(--red-tint);
  color: var(--red-dark);
  border-radius: 999px;
  font-size: 12.5px;
  font-weight: 600;
  margin-bottom: 24px;
  border: 1px solid rgba(212, 33, 44, 0.15);
}
.eyebrow i { font-size: 14px; }
.hero h1 {
  font-family: 'Space Grotesk', sans-serif;
  font-size: clamp(40px, 6vw, 64px);
  font-weight: 700;
  line-height: 1.02;
  letter-spacing: -0.03em;
  margin-bottom: 24px;
}
.hero h1 .accent { color: var(--red); position: relative; display: inline-block; }
.hero h1 .accent::after {
  content: '';
  position: absolute;
  left: 0; right: 0; bottom: 6px;
  height: 8px;
  background: var(--red);
  opacity: 0.15;
  z-index: -1;
  transform: skewX(-12deg);
}
.hero p.lead {
  font-size: 18px;
  color: var(--muted);
  margin-bottom: 32px;
  max-width: 520px;
}
.hero-actions { display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 32px; }
.hero-meta { display: flex; gap: 28px; flex-wrap: wrap; font-size: 13px; color: var(--muted); }
.hero-meta-item { display: flex; align-items: center; gap: 6px; }
.hero-meta-item i { color: var(--red); font-size: 16px; }

/* HERO MOCKUP */
.hero-visual { position: relative; }
.mock {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  box-shadow: 0 1px 2px rgba(0,0,0,0.04), 0 20px 60px -20px rgba(17, 17, 17, 0.18);
  overflow: hidden;
}
.mock-header {
  background: var(--graphite);
  padding: 12px 16px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.mock-dot { width: 10px; height: 10px; border-radius: 50%; }
.mock-dot.r { background: #FF5F56; }
.mock-dot.y { background: #FFBD2E; }
.mock-dot.g { background: #27C93F; }
.mock-url {
  flex: 1;
  text-align: center;
  background: rgba(255,255,255,0.08);
  color: rgba(255,255,255,0.6);
  font-size: 11px;
  padding: 4px 12px;
  border-radius: 4px;
  font-family: 'JetBrains Mono', monospace;
}
.mock-body { padding: 20px; }
.mock-tabs { display: flex; gap: 6px; margin-bottom: 16px; }
.mock-tab {
  padding: 6px 12px;
  border-radius: 6px;
  font-size: 11.5px;
  font-weight: 500;
  background: var(--bg);
  color: var(--muted);
  border: 1px solid var(--border);
}
.mock-tab.active { background: var(--graphite); color: #fff; border-color: var(--graphite); }
.mock-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.mock-tile { aspect-ratio: 1; border-radius: 10px; position: relative; overflow: hidden; }
.mock-tile.t1 { background: linear-gradient(135deg, #2a2a2a, #4a3030 50%, #8F1018); border: 2px solid var(--red); }
.mock-tile.t2 { background: linear-gradient(135deg, #1C1C1C, #3a3a3a); }
.mock-tile.t3 { background: linear-gradient(135deg, #6B7280, #111111); }
.mock-tile.t4 { background: linear-gradient(135deg, #8F1018, #1C1C1C); }
.mock-tile-label {
  position: absolute;
  bottom: 8px; left: 8px;
  background: rgba(0,0,0,0.55);
  color: #fff;
  font-size: 10px;
  padding: 3px 8px;
  border-radius: 4px;
  font-weight: 500;
  backdrop-filter: blur(4px);
}
.mock-tile-heart {
  position: absolute;
  top: 8px; right: 8px;
  width: 24px; height: 24px;
  background: rgba(255,255,255,0.15);
  border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  color: #fff;
  backdrop-filter: blur(4px);
}
.mock-tile-heart i { font-size: 12px; }
.mock-tile-heart.liked { background: var(--red); }

.float-badge {
  position: absolute;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 12px 16px;
  box-shadow: 0 10px 30px -10px rgba(0,0,0,0.15);
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 13px;
  font-weight: 500;
}
.float-badge i { color: var(--red); font-size: 18px; }
.float-badge.b1 { top: -16px; right: -24px; }
.float-badge.b2 { bottom: -16px; left: -24px; }
.float-badge .ok {
  width: 20px; height: 20px;
  background: var(--red);
  border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  color: #fff;
}
.float-badge .ok i { color: #fff; font-size: 12px; }

/* LOGOS */
.logos { padding: 40px 0; border-bottom: 1px solid var(--border); }
.logos-label {
  text-align: center;
  font-size: 12px;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 1.5px;
  margin-bottom: 24px;
  font-weight: 500;
}
.logos-row {
  display: flex;
  align-items: center;
  justify-content: space-around;
  flex-wrap: wrap;
  gap: 32px;
  opacity: 0.55;
}
.logo-fake {
  font-family: 'Space Grotesk', sans-serif;
  font-weight: 700;
  font-size: 18px;
  color: var(--graphite);
  letter-spacing: -0.5px;
  display: flex;
  align-items: center;
  gap: 6px;
}
.logo-fake i { font-size: 18px; }

/* FEATURES */
.features { padding: 100px 0; }
.section-head { text-align: center; max-width: 640px; margin: 0 auto 56px; }
.section-head h2 {
  font-family: 'Space Grotesk', sans-serif;
  font-size: clamp(32px, 4vw, 44px);
  font-weight: 700;
  letter-spacing: -0.02em;
  line-height: 1.1;
  margin-bottom: 16px;
}
.section-head p { color: var(--muted); font-size: 17px; }
.features-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }
.feature {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: 28px;
  transition: transform 0.25s, box-shadow 0.25s, border-color 0.25s;
  position: relative;
  overflow: hidden;
}
.feature:hover {
  transform: translateY(-3px);
  box-shadow: 0 12px 32px -12px rgba(17,17,17,0.12);
  border-color: rgba(212,33,44,0.3);
}
.feature-icon {
  width: 44px; height: 44px;
  border-radius: 10px;
  background: var(--red-tint);
  color: var(--red);
  display: flex; align-items: center; justify-content: center;
  margin-bottom: 18px;
}
.feature-icon i { font-size: 22px; }
.feature.dark { background: var(--graphite); color: #fff; border-color: var(--graphite); }
.feature.dark .feature-icon { background: rgba(212,33,44,0.15); color: var(--red); }
.feature.dark .feature-desc { color: rgba(255,255,255,0.6); }
.feature h3 {
  font-family: 'Space Grotesk', sans-serif;
  font-size: 19px;
  font-weight: 600;
  margin-bottom: 8px;
  letter-spacing: -0.01em;
}
.feature-desc { font-size: 14.5px; color: var(--muted); line-height: 1.55; }
.feature-tag {
  position: absolute;
  top: 20px; right: 20px;
  font-size: 10.5px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 1px;
  padding: 3px 8px;
  background: var(--red);
  color: #fff;
  border-radius: 4px;
}

/* CTA FINAL */
.cta-final { padding: 100px 0; background: var(--bg); }
.cta-box {
  background: var(--graphite);
  color: #fff;
  border-radius: var(--radius-lg);
  padding: 60px 40px;
  text-align: center;
  position: relative;
  overflow: hidden;
}
.cta-box::before {
  content: '';
  position: absolute;
  top: -100px; right: -100px;
  width: 400px; height: 400px;
  background: radial-gradient(circle, rgba(212,33,44,0.25) 0%, transparent 70%);
  pointer-events: none;
}
.cta-box h2 {
  font-family: 'Space Grotesk', sans-serif;
  font-size: clamp(28px, 4vw, 40px);
  font-weight: 700;
  margin-bottom: 16px;
  position: relative;
}
.cta-box p {
  color: rgba(255,255,255,0.7);
  font-size: 16px;
  max-width: 500px;
  margin: 0 auto 32px;
  position: relative;
}
.cta-actions {
  display: flex;
  gap: 12px;
  justify-content: center;
  flex-wrap: wrap;
  position: relative;
}

/* FOOTER */
.landing-footer {
  padding: 30px 0;
  border-top: 1px solid var(--border);
  color: var(--muted);
  font-size: 13.5px;
}
.footer-inner {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 16px;
}
.footer-links { display: flex; gap: 24px; }
.footer-links a { color: var(--muted); transition: color 0.2s; }
.footer-links a:hover { color: var(--ink); }

@media (max-width: 900px) {
  .hero-grid { grid-template-columns: 1fr; gap: 40px; }
  .features-grid { grid-template-columns: 1fr; }
  .nav-links { display: none; }
  .float-badge { display: none; }
}
`;
