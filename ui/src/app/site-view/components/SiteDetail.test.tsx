import React from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '@/lib/apiClient';
import type { AlertItem, DeviceRow, SiteRow } from '@/lib/types';
import SiteDetail from './SiteDetail';

vi.mock('@/lib/apiMode', () => ({
  devicePath: (id: string) => `/device-detail?id=${id}`,
}));

vi.mock('@/lib/apiClient', () => ({
  api: { listSiteDevices: vi.fn(), listAlerts: vi.fn(), getSiteBriefing: vi.fn(), getSiteSla: vi.fn() },
}));

function site(): SiteRow {
  return {
    id: '6',
    name: 'wc58',
    region: 'Western Cape',
    city: 'Cape Town',
    description: 'Rosmead store',
    address: '1 Main Road, Cape Town',
    deviceCount: 2,
    health: 'unreachable',
    alerts: 1,
    lastDiscovery: '4m',
  };
}

function device(partial: Partial<DeviceRow> & Pick<DeviceRow, 'id' | 'hostname' | 'role' | 'health'>): DeviceRow {
  return {
    site: 'wc58',
    siteId: '6',
    mgmtIp: '10.0.0.1',
    modelFamily: 'C9300',
    portsUp: 20,
    portsTotal: 24,
    portsWarn: 0,
    portsFault: 0,
    uptime: '3d',
    lastPoll: '1m',
    formFactor: 'access-switch-24',
    ...partial,
  };
}

describe('SiteDetail', () => {
  beforeEach(() => {
    vi.mocked(api.listSiteDevices).mockReset();
    vi.mocked(api.listAlerts).mockReset();
    vi.mocked(api.getSiteSla).mockReset();
    vi.mocked(api.getSiteSla).mockResolvedValue({
      points: [],
      limiterMbps: null,
      note: 'No SD-WAN or WAN device is recorded at this site.',
      windowSeconds: 180,
    });
    vi.mocked(api.getSiteBriefing).mockReset();
    vi.mocked(api.getSiteBriefing).mockResolvedValue({
      window: 'the past 24 hours',
      summary: 'Over the past 24 hours the switches kept forwarding.',
      sections: [{
        id: 'logs',
        title: 'Logs and config changes',
        text: '400 log lines arrived over the past 4 hours. No config change showed up in those lines.',
        notices: [{
          id: 'link-down',
          label: '41 lines reported a link down',
          tone: 'warning',
          total: 41,
          items: [{ title: 'wc58-sw1', detail: 'changed state to down', meta: '21:00:00' }],
        }],
      }],
      talkers: [{ device: 'wc58-sw1', port: 'Gi1/0/1', inMbps: 12.4, outMbps: 3.2 }],
      talkerNote: 'These are the ports that carried the most traffic in this window. Individual clients are not listed.',
    });
  });

  it('shows site condition panels instead of a device faceplate list', async () => {
    vi.mocked(api.listSiteDevices).mockResolvedValue([
      device({ id: 'sw', hostname: 'wc58-sw1', role: 'Access switch', health: 'healthy' }),
      device({ id: 'ap', hostname: 'wc58-ap1', role: 'Access point', health: 'unreachable', formFactor: 'ceiling-ap', portsUp: 0, portsTotal: 0 }),
    ]);
    const alert: AlertItem = {
      id: 'a1',
      severity: 'warning',
      title: 'AP is unreachable',
      detail: 'No SNMP sample',
      site: 'wc58',
      siteId: '6',
      deviceHostname: 'wc58-ap1',
      deviceId: 'ap',
      formFactor: 'ceiling-ap',
      category: 'snmp',
      raisedAt: '10:00',
      ageMinutes: 4,
      status: 'open',
    };
    vi.mocked(api.listAlerts).mockResolvedValue([alert]);

    render(<SiteDetail site={site()} />);

    expect(await screen.findByRole('heading', { name: 'Not working as expected' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'LAN Network' })).toBeInTheDocument();
    expect(screen.getByText('Working')).toBeInTheDocument();
    expect(screen.getByText(/The switch is answering/)).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Wi-Fi Network' })).toBeInTheDocument();
    expect(screen.getByText('Not answering')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'SDWAN/WAN Network' })).toBeInTheDocument();
    expect(screen.getByText(/No SD-WAN or WAN device is recorded/)).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Performance SLA' })).toBeInTheDocument();
    expect(screen.getByText(/No limiter is set/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Open wc58 on Google Maps' })).toHaveAttribute('href', expect.stringContaining('google.com/maps'));
    expect(screen.getByText('Rosmead store')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: "What's wrong" })).toBeInTheDocument();
    expect(screen.getAllByRole('link', { name: 'wc58-ap1' })[0]).toHaveAttribute('href', '/device-detail?id=ap');
    expect(screen.getByText('AP is unreachable')).toBeInTheDocument();
    expect(await screen.findByText(/the switches kept forwarding/)).toBeInTheDocument();
    expect(api.getSiteBriefing).toHaveBeenCalledWith('6', 'custom', 240);
    expect(screen.getByText(/Live · last 4 hours/)).toBeInTheDocument();
    expect(screen.queryByRole('combobox', { name: 'Time frame' })).toBeNull();
    const down = screen.getByRole('button', { name: '41 lines reported a link down' });
    await userEvent.hover(down);
    expect(await screen.findByRole('tooltip')).toHaveTextContent('changed state to down');
    await userEvent.click(down);
    expect(screen.getByRole('dialog', { name: '41 lines reported a link down' })).toHaveTextContent('changed state to down');
    await userEvent.click(screen.getByRole('tab', { name: 'Top talkers' }));
    expect(screen.getByText('Gi1/0/1')).toBeInTheDocument();
    expect(screen.getByText(/Individual clients are not listed/)).toBeInTheDocument();
    expect(screen.queryByText(/faceplate/i)).toBeNull();
  });
});
