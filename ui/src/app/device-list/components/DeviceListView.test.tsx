import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/lib/apiError';
import { api } from '@/lib/apiClient';
import DeviceListView from './DeviceListView';

vi.mock('next/link', () => ({
  default: ({ href, children, className }: { href: string; children: React.ReactNode; className?: string }) => (
    <a href={href} className={className}>{children}</a>
  ),
}));

vi.mock('@/lib/apiMode', () => ({
  isMockMode: () => false,
  devicePath: (id: string) => `/device-detail?id=${id}`,
}));

vi.mock('@/lib/apiClient', () => ({
  api: { listDevices: vi.fn(), listSites: vi.fn(), listSiteDevices: vi.fn() },
}));

vi.mock('./HealthStrip', () => ({ default: () => null }));
vi.mock('./DeviceFilters', () => ({ default: () => null }));
vi.mock('./ColumnMenu', () => ({
  default: () => null,
  COLUMNS: [],
}));
vi.mock('./DeviceTable', () => ({
  default: ({ rows, error }: { rows: { hostname: string }[] | null; error: string | null }) => (
    error ? <div role="alert">{error}</div> : <ul>{(rows || []).map((row) => <li key={row.hostname}>{row.hostname}</li>)}</ul>
  ),
}));

describe('DeviceListView signed-out state', () => {
  beforeEach(() => {
    vi.mocked(api.listDevices).mockReset();
    vi.mocked(api.listSites).mockReset();
    vi.mocked(api.listSiteDevices).mockReset();
    vi.mocked(api.listDevices).mockResolvedValue({ rows: [], total: 0, isExampleData: false, roles: [] });
  });

  it('points a 401 at the login screen instead of a generic load failure', async () => {
    vi.mocked(api.listSites).mockRejectedValue(new ApiError(401, 'unauthorized', 'login required'));
    render(<DeviceListView />);
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('You are signed out - sign in');
    expect(screen.getByRole('link', { name: 'sign in' })).toHaveAttribute('href', '/login-screen');
    expect(screen.queryByText('Failed to load devices. Check your connection and try again.')).toBeNull();
  });

  it('names a service failure and does not offer the sign-in link', async () => {
    vi.mocked(api.listSites).mockRejectedValue(new ApiError(503, 'down', 'unavailable'));
    render(<DeviceListView />);
    await waitFor(() => {
      expect(screen.getByRole('alert').textContent).toContain('The service failed while loading sites (HTTP 503).');
    });
    expect(screen.queryByRole('link', { name: 'sign in' })).toBeNull();
  });

  it('lists NetBox sites collapsed and shows their devices when expanded', async () => {
    vi.mocked(api.listSites).mockResolvedValue({
      rows: [
        { id: '1', name: 'Empty site', region: '', city: '', deviceCount: 0, health: 'healthy', alerts: 0, lastDiscovery: '—' },
        { id: '2', name: 'DC', region: 'North', city: 'JHB', deviceCount: 1, health: 'warning', alerts: 0, lastDiscovery: '—' },
      ],
      total: 2,
      isExampleData: false,
    });
    vi.mocked(api.listSiteDevices).mockImplementation(async (id: string | number) => (
      String(id) === '2'
        ? [{
          id: 'd1', hostname: 'sw-1', role: 'Access switch', site: 'DC', siteId: '2', mgmtIp: '10.0.0.1',
          modelFamily: 'C9300', health: 'healthy', portsUp: 1, portsTotal: 2, portsWarn: 0, portsFault: 0,
          uptime: '1d', lastPoll: '1m', formFactor: 'generic' as const,
        }]
        : []
    ));
    const { default: userEvent } = await import('@testing-library/user-event');
    const user = userEvent.setup();
    render(<DeviceListView />);
    expect(await screen.findByRole('button', { name: 'Expand Empty site' })).toHaveAttribute('aria-expanded', 'false');
    expect(screen.getByRole('button', { name: 'Expand DC' })).toBeInTheDocument();
    expect(screen.queryByText('sw-1')).not.toBeInTheDocument();
    expect(api.listSiteDevices).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: 'Expand Empty site' }));
    expect(await screen.findByText('No devices in this site yet.')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Expand DC' }));
    expect(await screen.findByText('sw-1')).toBeInTheDocument();
    expect(api.listSiteDevices).toHaveBeenCalledWith('2');
    await user.click(screen.getByRole('button', { name: 'Collapse DC' }));
    expect(screen.queryByText('sw-1')).not.toBeInTheDocument();
  });
});
