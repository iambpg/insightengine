import React from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '@/lib/apiClient';
import AccessPointList from './AccessPointList';

vi.mock('next/link', () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => <a href={href}>{children}</a>,
}));

vi.mock('@/lib/apiMode', () => ({
  isMockMode: () => false,
  devicePath: (id: string, form?: string) => `/device-detail?id=${encodeURIComponent(id)}${form ? `&form=${encodeURIComponent(form)}` : ''}`,
}));

vi.mock('@/lib/apiClient', () => ({
  api: {
    listAccessPoints: vi.fn(),
    getAccessPointDetail: vi.fn(),
    discoveryCatalog: vi.fn(),
    approveAccessPoints: vi.fn(),
  },
}));

const row = {
  name: 'ap-ams01-114',
  mac: '00:11:22:33:44:55',
  wlc: 'wlc-9800',
  site: 'Rotterdam',
  netboxSite: 'Rotterdam',
  status: 'up',
  clients: 18,
  uptimeSeconds: 100,
  model: 'C9120AXI',
  neighborSwitch: 'sw-ams01',
  neighborPort: 'Gi1/0/14',
  radios: [{ slot: '0', channel: 36, utilization: 0.2, clients: 11, noise: -90, interference: 8, txPowerDbm: 18, width: 40, band: '5' }],
  ssids: [{ ssid: 'corp', radio: '0', band: '5', clients: 11 }],
};

describe('AccessPointList', () => {
  beforeEach(() => {
    vi.mocked(api.listAccessPoints).mockReset();
    vi.mocked(api.getAccessPointDetail).mockReset();
  });

  it('links the access point to its device page and can add it to NetBox', async () => {
    vi.mocked(api.listAccessPoints).mockResolvedValue({ rows: [row], total: 1, page: 1, pageSize: 50 });
    vi.mocked(api.discoveryCatalog).mockResolvedValue({ roles: ['Access point'], sites: ['Rotterdam'], platforms: [], roleChoices: [{ name: 'Access point', slug: 'access-point' }] });
    const user = userEvent.setup();
    render(<AccessPointList wlc="wlc-9800" />);
    const link = await screen.findByRole('link', { name: 'ap-ams01-114' });
    expect(link).toHaveAttribute('href', '/device-detail?id=ap%3A00%3A11%3A22%3A33%3A44%3A55&form=ceiling-ap');
    expect(screen.getByText('sw-ams01 Gi1/0/14')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Healthy/ })).toHaveAttribute('href', expect.stringContaining('tab=health'));
    await user.click(screen.getByRole('button', { name: 'Add to NetBox' }));
    expect(await screen.findByRole('dialog', { name: 'Add to NetBox' })).toBeInTheDocument();
    expect(await screen.findByRole('combobox', { name: 'Role' })).toHaveValue('Access point');
  });
});