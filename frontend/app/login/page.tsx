'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';

export default function LoginPage() {
  const router = useRouter();
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      const res = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password }),
        credentials: 'include',
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        setError(data.detail || 'Złe hasło.');
        return;
      }
      router.push('/pulpit');
    } catch (err) {
      setError('Błąd połączenia z serwerem.');
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      <style dangerouslySetInnerHTML={{ __html: LOGIN_CSS }} />
      <div className="login-page">
        <nav className="login-nav">
          <div className="login-nav-inner">
            <Link href="/" className="logo">
              <div className="logo-mark"><i className="ti ti-flame"></i></div>
              eCombinat
            </Link>
            <div className="env-tag">v0.1 · production</div>
          </div>
        </nav>

        <main className="login-main">
          <div className="login-card">
            <div className="eyebrow">
              <i className="ti ti-bolt"></i> Polski narzędziownik AI dla e-commerce
            </div>
            <h1 className="display">Wejdź do hali kombinatu</h1>
            <p className="login-sub">
              Zaloguj się żeby kontynuować pracę z agentami AI. Aktualnie dostępny:{' '}
              <strong>Handlowiec cold-email</strong>.
            </p>

            <form onSubmit={handleSubmit}>
              <input
                type="password"
                placeholder="Wpisz hasło dostępu"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoFocus
                required
                className="pwd-input"
              />
              {error && <div className="login-error">{error}</div>}
              <button type="submit" className="btn btn-primary login-submit" disabled={loading}>
                {loading ? 'Loguję...' : 'Wejdź do panelu →'}
              </button>
            </form>

            <div className="login-footer">
              <span>Brak hasła? Skontaktuj się z administratorem.</span>
              <span className="mono">ENV: production</span>
            </div>
          </div>

          <div className="login-roadmap">
            Wkrótce: Generator zdjęć · Wideo · Opisy AI · Usuń tło · Upscaler 4K
          </div>
        </main>
      </div>
    </>
  );
}

const LOGIN_CSS = `
.login-page {
  min-height: 100vh;
  background: var(--bg);
  display: flex;
  flex-direction: column;
}
.login-nav {
  background: rgba(250, 250, 247, 0.85);
  backdrop-filter: saturate(180%) blur(12px);
  border-bottom: 1px solid var(--border);
  padding: 16px 24px;
}
.login-nav-inner {
  max-width: 1200px;
  margin: 0 auto;
  display: flex;
  align-items: center;
  justify-content: space-between;
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
.env-tag {
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
  color: var(--muted);
}
.login-main {
  flex: 1;
  padding: 60px 24px 40px;
  display: flex;
  flex-direction: column;
  align-items: center;
}
.login-card {
  max-width: 480px;
  width: 100%;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 16px;
  padding: 36px;
  box-shadow: 0 10px 30px -10px rgba(0,0,0,0.08);
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
.login-card h1 {
  font-family: 'Space Grotesk', sans-serif;
  font-size: 28px;
  font-weight: 700;
  letter-spacing: -0.02em;
  color: var(--ink);
  margin: 0 0 8px 0;
  line-height: 1.1;
}
.login-sub {
  color: var(--muted);
  font-size: 14.5px;
  margin-bottom: 28px;
}
.pwd-input {
  width: 100%;
  padding: 12px 14px;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 8px;
  font-family: 'Inter', sans-serif;
  font-size: 14.5px;
  color: var(--ink);
  margin-bottom: 12px;
  outline: none;
  transition: border-color 0.15s, box-shadow 0.15s;
}
.pwd-input:focus {
  border-color: var(--red);
  box-shadow: 0 0 0 3px rgba(212,33,44,0.08);
}
.login-error {
  color: var(--red-dark);
  font-size: 13px;
  margin-bottom: 12px;
  padding: 8px 12px;
  background: var(--red-tint);
  border-radius: 6px;
  border: 1px solid rgba(212,33,44,0.15);
}
.btn { display: inline-flex; align-items: center; justify-content: center; gap: 8px; padding: 10px 18px; border-radius: 8px; font-size: 14px; font-weight: 500; border: none; cursor: pointer; }
.btn-primary { background: var(--red); color: #fff; box-shadow: 0 1px 2px rgba(143, 16, 24, 0.1); }
.btn-primary:hover { background: var(--red-dark); box-shadow: 0 4px 12px rgba(212, 33, 44, 0.25); }
.btn-primary:disabled { opacity: 0.6; cursor: not-allowed; }
.login-submit { width: 100%; padding: 12px 18px; }
.login-footer {
  margin-top: 20px;
  padding-top: 20px;
  border-top: 1px solid var(--border);
  font-size: 12px;
  color: var(--muted-2);
  display: flex;
  justify-content: space-between;
}
.login-footer .mono { font-family: 'JetBrains Mono', monospace; }
.login-roadmap {
  text-align: center;
  margin-top: 32px;
  color: var(--muted);
  font-size: 13px;
}
`;
