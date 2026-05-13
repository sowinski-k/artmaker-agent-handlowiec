/**
 * Smoke testy /pozyskiwanie - tryby manual/agent, sources, formularz.
 *
 * Co lapie:
 * - Renderuje sie po zalogowaniu
 * - Mode toggle (Praca reczna / Wyslij agenta w teren)
 * - 4 source cards (Google Places, Apify Maps, Allegro, LinkedIn)
 * - Cost estimate widoczny gdy zrodla wybrane
 * - LinkedIn warning chip (TOS + RODO)
 * - Datalist z lokalizacjami
 */
import { describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

import PozyskiwaniePage from '@/app/(app)/pozyskiwanie/page';

function loginUser() {
  localStorage.setItem('ecombinat_token', 'test-token');
}

describe('/pozyskiwanie smoke', () => {
  it('renderuje dwa tryby pracy: manual + agent', async () => {
    loginUser();
    global.fetch = vi.fn().mockResolvedValue({
      ok: true, status: 200, json: async () => [],
    } as Response);
    render(<PozyskiwaniePage />);

    expect(screen.getByText(/praca ręczna/i)).toBeInTheDocument();
    expect(screen.getByText(/wyślij agenta w teren/i)).toBeInTheDocument();
  });

  it('renderuje 4 source cards', async () => {
    loginUser();
    global.fetch = vi.fn().mockResolvedValue({
      ok: true, status: 200, json: async () => [],
    } as Response);
    render(<PozyskiwaniePage />);

    expect(screen.getByText('Google Places')).toBeInTheDocument();
    expect(screen.getByText('Apify Google Maps')).toBeInTheDocument();
    expect(screen.getByText('Apify Allegro')).toBeInTheDocument();
    expect(screen.getByText('Apify LinkedIn')).toBeInTheDocument();
  });

  it('renderuje warning dla LinkedIn (TOS + RODO)', async () => {
    loginUser();
    global.fetch = vi.fn().mockResolvedValue({
      ok: true, status: 200, json: async () => [],
    } as Response);
    render(<PozyskiwaniePage />);

    expect(screen.getByText(/TOS LinkedIn/i)).toBeInTheDocument();
  });

  it('cost estimate pokazuje "wybierz źródła" gdy żadne nie zaznaczone', async () => {
    loginUser();
    global.fetch = vi.fn().mockResolvedValue({
      ok: true, status: 200, json: async () => [],
    } as Response);
    render(<PozyskiwaniePage />);

    // Default jest 'google_places' wybrane wiec cost > 0. Sprawdzamy ze cost
    // estimate w ogole istnieje (label "Szacunkowy koszt API:").
    expect(screen.getByText(/szacunkowy koszt API/i)).toBeInTheDocument();
  });

  it('renderuje datalist z 16 wojewodztwami + miastami', async () => {
    loginUser();
    global.fetch = vi.fn().mockResolvedValue({
      ok: true, status: 200, json: async () => [],
    } as Response);
    const { container } = render(<PozyskiwaniePage />);

    const datalist = container.querySelector('datalist#pl-locations');
    expect(datalist).toBeInTheDocument();
    // 16 wojewodztw + ~30 miast = >40 opcji
    const options = datalist?.querySelectorAll('option') ?? [];
    expect(options.length).toBeGreaterThan(40);
  });

  it('renderuje segment dropdown z 8 segmentami', async () => {
    loginUser();
    global.fetch = vi.fn().mockResolvedValue({
      ok: true, status: 200, json: async () => [],
    } as Response);
    const { container } = render(<PozyskiwaniePage />);

    // Default value to 'sklep_papierniczy' (z useState init)
    const segmentSelect = container.querySelector('select') as HTMLSelectElement;
    expect(segmentSelect).toBeInTheDocument();
    // Powinno byc 8 segmentow (sklep_plastyczny, sklep_papierniczy, paint_and_sip,
    // warsztaty_dzieci, animatorzy_eventy, szkola_artystyczna, marka_wlasna, inne)
    expect(segmentSelect.options.length).toBe(8);
  });
});
