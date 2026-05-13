/**
 * Smoke testy strony /login.
 *
 * Co lapie:
 * - Strona sie renderuje bez exceptionów
 * - Sa pola email + password (zeby form mial sens)
 * - Submit button + link do rejestracji
 * - Validation HTML (email type, required, minLength)
 */
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';

import LoginPage from '@/app/login/page';

describe('/login renderowanie', () => {
  it('renderuje sie bez crashu', () => {
    render(<LoginPage />);
    expect(screen.getByRole('heading', { name: /zaloguj/i })).toBeInTheDocument();
  });

  it('ma pole email z type=email i required', () => {
    render(<LoginPage />);
    const emailInput = screen.getByPlaceholderText(/ty@firma\.pl/i) as HTMLInputElement;
    expect(emailInput.type).toBe('email');
    expect(emailInput.required).toBe(true);
  });

  it('ma pole password z minLength=8', () => {
    render(<LoginPage />);
    const passwordInput = screen.getByPlaceholderText(/hasło/i) as HTMLInputElement;
    expect(passwordInput.type).toBe('password');
    expect(passwordInput.minLength).toBe(8);
  });

  it('ma button submit z labelka "Wejdz do panelu"', () => {
    render(<LoginPage />);
    const btn = screen.getByRole('button', { name: /wejdź do panelu/i });
    expect(btn).toBeInTheDocument();
    expect((btn as HTMLButtonElement).type).toBe('submit');
  });

  it('ma link do rejestracji', () => {
    render(<LoginPage />);
    const link = screen.getByRole('link', { name: /załóż konto/i });
    expect(link).toHaveAttribute('href', '/rejestracja');
  });
});
