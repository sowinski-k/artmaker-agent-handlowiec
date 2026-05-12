/* Dashboard layout - sidebar + topbar + content (1:1 ecombinat-dashboard.html chrome). */

import Link from 'next/link';

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <style dangerouslySetInnerHTML={{ __html: APP_CSS }} />
      <div className="app">
        <aside className="sidebar">
          <div className="sb-logo">
            <div className="sb-logo-mark"><i className="ti ti-flame"></i></div>
            <div className="sb-logo-text">eCombinat</div>
            <span className="sb-logo-env">PROD</span>
          </div>

          <div className="sb-section">Hala</div>
          <Link href="/pulpit" className="sb-item active">
            <i className="ti ti-layout-dashboard"></i> Pulpit
          </Link>
          <a className="sb-item disabled"><i className="ti ti-folder"></i> Projekty <span className="sb-count">—</span></a>
          <a className="sb-item disabled"><i className="ti ti-photo"></i> Biblioteka <span className="sb-count">—</span></a>

          <div className="sb-section">Kuźnia</div>
          <Link href="/pulpit" className="sb-item">
            <i className="ti ti-robot"></i> Handlowiec cold-email <span className="sb-count">1</span>
          </Link>
          <a className="sb-item disabled"><i className="ti ti-photo"></i> Zdjęcia produktowe</a>
          <a className="sb-item disabled"><i className="ti ti-video"></i> Wideo</a>
          <a className="sb-item disabled"><i className="ti ti-wand"></i> Opisy AI</a>
          <a className="sb-item disabled"><i className="ti ti-eraser"></i> Usuń tło</a>
          <a className="sb-item disabled"><i className="ti ti-arrows-maximize"></i> Upscaler</a>

          <div className="sb-section">Integracje</div>
          <a className="sb-item"><i className="ti ti-mail"></i> Woodpecker</a>
          <a className="sb-item"><i className="ti ti-package"></i> Apify</a>
          <a className="sb-item"><i className="ti ti-api"></i> API</a>

          <div className="sb-foot">
            <div className="sb-foot-row">Kredyty <strong>0 / 100</strong></div>
            <div className="sb-bar"><div style={{ width: '0%' }}></div></div>
            <div className="sb-foot-row" style={{ marginBottom: 0 }}>Odnowienie <strong>jutro 02:00</strong></div>
            <a href="#">↑ Zwiększ plan →</a>
          </div>
        </aside>

        <main>
          {children}
        </main>
      </div>
    </>
  );
}

const APP_CSS = `
.app { display: grid; grid-template-columns: 224px 1fr; min-height: 100vh; }

aside.sidebar {
  background: var(--graphite);
  color: #fff;
  padding: 16px 12px;
  display: flex;
  flex-direction: column;
  gap: 2px;
  position: sticky;
  top: 0;
  height: 100vh;
  overflow-y: auto;
}
.sb-logo {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 8px 18px;
  border-bottom: 1px solid rgba(255,255,255,0.08);
  margin-bottom: 14px;
}
.sb-logo-mark {
  width: 28px; height: 28px;
  background: var(--red);
  border-radius: 6px;
  display: flex; align-items: center; justify-content: center;
  color: #fff;
  flex-shrink: 0;
}
.sb-logo-mark i { font-size: 16px; }
.sb-logo-text {
  font-weight: 600;
  font-size: 14px;
  letter-spacing: -0.2px;
}
.sb-logo-env {
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  color: var(--muted-2);
  padding: 1px 6px;
  background: rgba(255,255,255,0.06);
  border-radius: 3px;
  margin-left: auto;
}
.sb-section {
  font-size: 10.5px;
  text-transform: uppercase;
  letter-spacing: 1.4px;
  color: rgba(255,255,255,0.4);
  padding: 12px 10px 4px;
  font-weight: 600;
}
.sb-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 7px 10px;
  border-radius: 6px;
  color: #D1D5DB;
  font-size: 13px;
  cursor: pointer;
  text-decoration: none;
  position: relative;
  transition: background 0.12s;
}
.sb-item:hover { background: rgba(255,255,255,0.05); color: #fff; }
.sb-item.active { background: rgba(212,33,44,0.12); color: #fff; }
.sb-item.active::before {
  content: '';
  position: absolute;
  left: -12px;
  top: 50%;
  transform: translateY(-50%);
  width: 3px; height: 18px;
  background: var(--red);
  border-radius: 0 2px 2px 0;
}
.sb-item.disabled { opacity: 0.4; cursor: not-allowed; }
.sb-item i { font-size: 16px; width: 16px; }
.sb-item .sb-count {
  margin-left: auto;
  font-family: 'JetBrains Mono', monospace;
  font-size: 10.5px;
  color: rgba(255,255,255,0.5);
}
.sb-item.active .sb-count { color: rgba(255,255,255,0.85); }

.sb-foot {
  margin-top: auto;
  padding: 10px;
  background: rgba(255,255,255,0.04);
  border: 1px solid rgba(255,255,255,0.06);
  border-radius: 6px;
}
.sb-foot-row {
  display: flex; justify-content: space-between; align-items: baseline;
  font-size: 11px; color: rgba(255,255,255,0.6); margin-bottom: 4px;
}
.sb-foot-row strong { color: #fff; font-family: 'JetBrains Mono', monospace; font-weight: 500; }
.sb-bar {
  height: 3px; background: rgba(255,255,255,0.08); border-radius: 2px; overflow: hidden;
  margin: 6px 0 8px;
}
.sb-bar > div { height: 100%; background: var(--red); }
.sb-foot a {
  font-size: 11px; color: rgba(255,255,255,0.5);
  display: block; padding-top: 6px; border-top: 1px solid rgba(255,255,255,0.06);
}
.sb-foot a:hover { color: #fff; }

main { min-width: 0; }
`;
