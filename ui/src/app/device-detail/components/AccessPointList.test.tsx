import React from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '@/lib/apiClient';
import AccessPointList from './AccessPointList';

vi.mock('@/lib/apiClient', () => ({
  api: { listAccessPoints: vi.fn(), getAccessPointDetail: vi.fn() },
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

  it('shows the NetBox site and opens inventory, radios and events', async () => {
    vi.mocked(api.listAccessPoints).mockResolvedValue({ rows: [row], total: 1, page: 1, pageSize: 50 });
    vi.mocked(api.getAccessPointDetail).mockResolvedValue({
      accessPoint: row,
      events: [{ t: 1700000000, what: 'channel', ap: row.name, radio: '0', from: '40', to: '36' }],
      degraded: [],
    });
    const user = userEvent.setup();
    render(<AccessPointList wlc="wlc-9800" />);
    expect(await screen.findByText('ap-ams01-114')).toBeInTheDocument();
    expect(screen.getByText('sw-ams01 Gi1/0/14')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'ap-ams01-114' }));
    expect(await screen.findByText(/40 → 36/)).toBeInTheDocument();
    expect(screen.getByText(/corp band/)).toBeInTheDocument();
  });
});