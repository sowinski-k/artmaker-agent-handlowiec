'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';

import { register } from '@/lib/api';

import { AUTH_CSS } from '../login/page';

export default function RejestracjaPage() {
  const router = useRouter();
  const [email, setEmail] = useState('');
  const [name, setName] = useState('');
  const [workspaceName, setWorkspaceName] = useState('');
  const [password, setPassword] = useState('');
  const [password2, setPassword2] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError('');
    if (password !== password2) {
      setError('Hasła nie są identyczne.');
      return;
    }
    if (password.length < 8) {
      setError('Hasło musi mieć co najmniej 8 znaków.');
      return;
    }
    setLoading(true);
    try {
      await register(email, password, name || undefined, workspaceName || undefined);
      router.push('/pulpit');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Błąd rejestracji.');
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
              <i className="ti ti-rocket"></i> Wystartuj za darmo, bez karty
            </div>
            <h1 className="display">Załóż konto</h1>
            <p className="auth-sub">
              50 darmowych kredytów na start. Bez karty, bez zobowiązań.
              Pierwszy moduł aktywny od razu: Handlowiec cold-email.
            </p>

            <form onSubmit={handleSubmit}>
              <label className="auth-label">Email *</label>
              <input type="email" className="auth-input"
                placeholder="ty@firma.pl" value={email} autoFocus required
                onChange={(e) => setEmail(e.target.value)} />

              <label className="auth-label">Imię (opcjonalne)</label>
              <input type="text" className="auth-input"
                placeholder="Jan" value={name}
                onChange={(e) => setName(e.target.value)} />

              <label className="auth-label">Nazwa firmy / workspace (opcjonalne)</label>
              <input type="text" className="auth-input"
                placeholder="Moja Firma sp. z o.o." value={workspaceName}
                onChange={(e) => setWorkspaceName(e.target.value)} />

              <label className="auth-label">Hasło * (min. 8 znaków, mała + wielka litera + cyfra)</label>
              <input type="password" className="auth-input"
                value={password} required minLength={8}
                onChange={(e) => setPassword(e.target.value)} />

              <label className="auth-label">Powtórz hasło *</label>
              <input type="password" className="auth-input"
                value={password2} required minLength={8}
                onChange={(e) => setPassword2(e.target.value)} />

              {error && <div className="auth-error">{error}</div>}

              <button type="submit" className="btn btn-primary auth-submit" disabled={loading}>
                {loading ? 'Tworzę konto...' : 'Załóż konto i wejdź →'}
              </button>
            </form>

            <div className="auth-footer">
              Masz już konto? <Link href="/login" className="auth-link">Zaloguj się</Link>
            </div>
          </div>

          <div className="auth-side-note">
            Twoje dane są izolowane workspace-by-workspace. Nikt inny ich nie widzi.
            HTTPS, bcrypt password hashing, rate-limit anti brute-force.
          </div>
        </main>
      </div>
    </>
  );
}
