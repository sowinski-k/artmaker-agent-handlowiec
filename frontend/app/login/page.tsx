'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';

import { login } from '@/lib/api';

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      await login(email, password);
      router.push('/pulpit');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Błąd logowania.');
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      <style dangerouslySetInnerHTML={{ __html: AUTH_CSS }} />
      <div className="auth-page">
        <nav className="auth-nav">
          <div className="auth-nav-inner">
            <Link href="/" className="logo">
              <div className="logo-mark"><i className="ti ti-flame"></i></div>
              eCombinat
            </Link>
            <div className="env-tag">v0.4 production</div>
          </div>
        </nav>

        <main className="auth-main">
          <div className="auth-card">
            <div className="eyebrow">
              <i className="ti ti-bolt"></i> Polski narzędziownik AI dla e-commerce
            </div>
            <h1 className="display">Zaloguj się</h1>
            <p className="auth-sub">Wpisz email i hasło, żeby wrócić do swojej hali.</p>

            <form onSubmit={handleSubmit}>
              <label className="auth-label">Email</label>
              <input type="email" className="auth-input"
                placeholder="ty@firma.pl" value={email} autoFocus required
                onChange={(e) => setEmail(e.target.value)} />

              <label className="auth-label">Hasło</label>
              <input type="password" className="auth-input"
                placeholder="hasło"
                value={password} required minLength={8}
                onChange={(e) => setPassword(e.target.value)} />

              {error && <div className="auth-error">{error}</div>}

              <button type="submit" className="btn btn-primary auth-submit" disabled={loading}>
                {loading ? 'Loguję...' : 'Wejdź do panelu →'}
              </button>
            </form>

            <div className="auth-footer">
              Nie masz konta? <Link href="/rejestracja" className="auth-link">Załóż konto</Link>
            </div>
          </div>

          <div className="auth-side-note">
            Wkrótce: Generator zdjęć · Wideo · Opisy AI · Usuń tło · Upscaler · Agent Celny · GPSR
          </div>
        </main>
      </div>
    </>
  );
}

export const AUTH_CSS = `
.auth-page { min-height: 100vh; background: #FAFAF7; display: flex; flex-direction: column; }
.auth-nav { background: rgba(250,250,247,0.85); backdrop-filter: saturate(180%) blur(12px); border-bottom: 1px solid #E5E7EB; padding: 16px 24px; }
.auth-nav-inner { max-width: 1200px; margin: 0 auto; display: flex; align-items: center; justify-content: space-between; }
.logo { display: flex; align-items: center; gap: 10px; font-family: 'Space Grotesk', sans-serif; font-weight: 700; font-size: 18px; letter-spacing: -0.5px; color: #111; text-decoration: none; }
.logo-mark { width: 32px; height: 32px; background: #D4212C; border-radius: 8px; display: flex; align-items: center; justify-content: center; color: #fff; position: relative; overflow: hidden; }
.logo-mark::after { content: ''; position: absolute; inset: 0; background: linear-gradient(135deg, transparent 50%, rgba(0,0,0,0.2) 100%); }
.logo-mark i { font-size: 18px; position: relative; z-index: 1; }
.env-tag { font-family: 'JetBrains Mono', monospace; font-size: 12px; color: #6B7280; }

.auth-main { flex: 1; padding: 60px 24px 40px; display: flex; flex-direction: column; align-items: center; }
.auth-card { max-width: 460px; width: 100%; background: #fff; border: 1px solid #E5E7EB; border-radius: 16px; padding: 36px; box-shadow: 0 10px 30px -10px rgba(0,0,0,0.08); }

.eyebrow { display: inline-flex; align-items: center; gap: 8px; padding: 6px 14px; background: #FDECED; color: #8F1018; border-radius: 999px; font-size: 12.5px; font-weight: 600; margin-bottom: 24px; border: 1px solid rgba(212,33,44,0.15); }
.eyebrow i { font-size: 14px; }

.auth-card h1 { font-family: 'Space Grotesk', sans-serif; font-size: 28px; font-weight: 700; letter-spacing: -0.02em; color: #111; margin: 0 0 8px 0; line-height: 1.1; }
.auth-sub { color: #6B7280; font-size: 14.5px; margin-bottom: 24px; }

.auth-label { display: block; font-size: 11px; color: #6B7280; text-transform: uppercase; letter-spacing: 0.8px; font-weight: 600; margin-bottom: 6px; margin-top: 14px; }
.auth-input { width: 100%; padding: 12px 14px; background: #FAFAF7; border: 1px solid #E5E7EB; border-radius: 8px; font-family: 'Inter', sans-serif; font-size: 14.5px; color: #111; outline: none; transition: border-color 0.15s, box-shadow 0.15s; }
.auth-input:focus { border-color: #D4212C; box-shadow: 0 0 0 3px rgba(212,33,44,0.08); background: #fff; }

.auth-error { color: #8F1018; font-size: 13px; margin-top: 14px; padding: 10px 12px; background: #FDECED; border-radius: 6px; border: 1px solid rgba(212,33,44,0.15); }

.btn { display: inline-flex; align-items: center; justify-content: center; gap: 8px; padding: 10px 18px; border-radius: 8px; font-size: 14px; font-weight: 500; border: none; cursor: pointer; font-family: inherit; }
.btn-primary { background: #D4212C; color: #fff; box-shadow: 0 1px 2px rgba(143,16,24,0.1); }
.btn-primary:hover:not(:disabled) { background: #8F1018; box-shadow: 0 4px 12px rgba(212,33,44,0.25); }
.btn-primary:disabled { opacity: 0.6; cursor: not-allowed; }
.auth-submit { width: 100%; padding: 12px 18px; margin-top: 18px; font-size: 14.5px; }

.auth-footer { margin-top: 22px; padding-top: 22px; border-top: 1px solid #E5E7EB; font-size: 13px; color: #6B7280; text-align: center; }
.auth-link { color: #D4212C; font-weight: 500; text-decoration: none; }
.auth-link:hover { text-decoration: underline; }

.auth-side-note { text-align: center; margin-top: 32px; color: #9CA3AF; font-size: 12px; max-width: 500px; }
`;
