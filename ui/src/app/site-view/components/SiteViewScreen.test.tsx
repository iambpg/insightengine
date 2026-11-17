import React from 'react';
import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '@/lib/apiClient';
import type { SiteRow } from '@/lib/types';
import SiteViewScreen from './SiteViewScreen';

const queryState = vi.hoisted(() => ({ value: '' }));

vi.mock('next/navigation', () => ({
  useSearchParams: () => new URLSearchParams(queryState.value),
}));

vi.mock('@/lib/apiMode', () => ({
  isMockMode: () => false,
  devicePath: (id: string) => `/device-detail?id=${id}`,
}));

vi.mock('@/lib/apiClient', () => ({
  api: { listSites: vi.fn(), listSiteDevices: vi.fn(), listAlerts: vi.fn(), getSiteBriefing: vi.fn(), getSiteSla: vi.fn() },
}));

function site(id: string, name: string): SiteRow {
  return {
    id,
    name,
    region: 'Benelux-West',
    city: name,
    deviceCount: 2,
    health: 'healthy',
    alerts: 0,
    lastDiscovery: '1h',
  };
}

describe('SiteViewScreen client navigation', () => {
  beforeEach(() => {
    queryState.value = '';
    window.history.pushState({}, '', '/');
    vi.mocked(api.listSites).mockReset();
    vi.mocked(api.listSiteDevices).mockReset();
    vi.mocked(api.listAlerts).mockReset();
    vi.mocked(api.listAlerts).mockResolvedValue([]);
    vi.mocked(api.getSiteSla).mockReset();
    vi.mocked(api.getSiteSla).mockResolvedValue({ points: [], limiterMbps: null, note: '', windowSeconds: 180 });
    vi.mocked(api.getSiteBriefing).mockReset();
    vi.mocked(api.getSiteBriefing).mockResolvedValue({
      window: 'the past 24 hours',
      summary: 'Quiet.',
      sections: [],
      talkers: [],
      talkerNote: '',
    });
    vi.mocked(api.listSites).mockResolvedValue({
      rows: [site('1', 'Rotterdam'), site('2', 'Amsterdam')],
      total: 2,
      regions: ['Benelux-West'],
    });
    vi.mocked(api.listSiteDevices).mockResolvedValue([]);
  });

  it('does not lock the first site before the site id arrives', async () => {
    const { rerender } = render(<SiteViewScreen />);
    expect(api.listSites).not.toHaveBeenCalled();
    expect(screen.queryByRole('heading', { level: 2, name: 'Rotterdam' })).toBeNull();

    queryState.value = 'site=2&q=Amsterdam';
    rerender(<SiteViewScreen />);
    expect(await screen.findByRole('heading', { level: 2, name: 'Amsterdam' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { level: 2, name: 'Rotterdam' })).toBeNull();
    expect(screen.getByRole('button', { name: /Amsterdam/ })).toHaveAttribute('aria-current', 'true');
  });
});
