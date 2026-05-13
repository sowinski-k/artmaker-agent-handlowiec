/**
 * Smoke testy /drafty - email-style preview.
 *
 * Co lapie:
 * - Renderuje sie po zalogowaniu
 * - Empty state gdy brak draftow
 * - Email card z subject + body + kontekst leada
 * - Track badge (Private Label / Panel B2B / Obie)
 */
import { describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

import DraftyPage from '@/app/(app)/drafty/page';

function loginUser() {
  localStorage.setItem('ecombinat_token', 'test-token');
}

function mockFetchSequence(...responses: unknown[]) {
  let i = 0;
  global.fetch = vi.fn().mockImplementation(async () => ({
    ok: true,
    status: 200,
    json: async () => responses[i++] ?? [],
  } as Response));
}

describe('/drafty smoke', () => {
  it('renderuje empty state gdy brak draftow', async () => {
    loginUser();
    mockFetchSequence([], []);
    render(<DraftyPage />);

    await waitFor(() => {
      expect(screen.getByText(/brak draftów do review/i)).toBeInTheDocument();
    });
  });

  it('renderuje email card z subject + body', async () => {
    loginUser();
    mockFetchSequence(
      [{
        id: 7, lead_id: 42, company: 'Test ArtBox',
        lead_contact_name: 'Anna', lead_email: 'a@artbox.pl',
        lead_segment: 'sklep_plastyczny', lead_city: 'Krakow',
        lead_score: 9.5,
        subject: 'Test subject',
        snippet1: 'Pani Anno, zerknalem na Wasza strone.',
        snippet2: 'Pisze z Artmakera.',
        snippet3: 'Mozemy produkowac w Chinach.',
        snippet4: null,
        snippet5: 'Wyslac wycene?',
        full_preview: 'preview', status: 'draft',
        template_variant: 'cold_v1_both',
        edited_by_user: false,
        generated_by_model: 'anthropic/claude-sonnet-4-6',
        created_at: '2026-05-13T12:00:00+00:00',
        sent_at: null,
      }],
      [], // campaigns
    );
    render(<DraftyPage />);

    await waitFor(() => {
      expect(screen.getByText(/test artbox/i)).toBeInTheDocument();
      expect(screen.getByText('Test subject')).toBeInTheDocument();
      expect(screen.getByText(/zerknalem na Wasza strone/i)).toBeInTheDocument();
    });
  });

  it('renderuje track badge dla template_variant=both', async () => {
    loginUser();
    mockFetchSequence(
      [{
        id: 1, lead_id: 1, company: 'X',
        lead_contact_name: null, lead_email: null,
        lead_segment: null, lead_city: null, lead_score: null,
        subject: 'T', snippet1: '1', snippet2: '2', snippet3: '3',
        snippet4: null, snippet5: '5', full_preview: '',
        status: 'draft', template_variant: 'cold_v1_both',
        edited_by_user: false, generated_by_model: null,
        created_at: '2026-05-13T12:00:00+00:00', sent_at: null,
      }],
      [],
    );
    render(<DraftyPage />);

    await waitFor(() => {
      expect(screen.getByText(/obie ścieżki/i)).toBeInTheDocument();
    });
  });

  it('renderuje meta-info Do/Firma w email card', async () => {
    loginUser();
    mockFetchSequence(
      [{
        id: 1, lead_id: 1, company: 'Synchronik',
        lead_contact_name: 'Tomasz Krupa', lead_email: 'biuro@synchronik.pl',
        lead_segment: 'sklep_papierniczy', lead_city: 'Rzeszow',
        lead_score: 10.0,
        subject: 'T', snippet1: '1', snippet2: '2', snippet3: '3',
        snippet4: null, snippet5: '5', full_preview: '',
        status: 'draft', template_variant: 'cold_v1_private_label',
        edited_by_user: false, generated_by_model: null,
        created_at: '2026-05-13T12:00:00+00:00', sent_at: null,
      }],
      [],
    );
    render(<DraftyPage />);

    await waitFor(() => {
      expect(screen.getByText('Tomasz Krupa')).toBeInTheDocument();
      expect(screen.getByText(/biuro@synchronik\.pl/)).toBeInTheDocument();
      expect(screen.getByText('Synchronik')).toBeInTheDocument();
      expect(screen.getByText('Rzeszow')).toBeInTheDocument();
    });
  });
});
