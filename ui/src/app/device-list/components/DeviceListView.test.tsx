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
  api: { listDevices: vi.fn() },
}));

vi.mock('./HealthStrip', () => ({ default: () => null }));
vi.mock('./DeviceFilters', () => ({ default: () => null }));
vi.mock('./ColumnMenu', () => ({
  default: () => null,
  COLUMNS: [],
}));
vi.mock('./DeviceTable', () => ({
  default: ({ error }: { error: string | null }) => (error ? <div role="alert">{error}</div> : null),
}));

describe('DeviceListView signed-out state', () => {
  beforeEach(() => {
    vi.mocked(api.listDevices).mockReset();
  });

  it('points a 401 at the login screen instead of a generic load failure', async () => {
    vi.mocked(api.listDevices).mockRejectedValue(new ApiError(401, 'unauthorized', 'login required'));
    render(<DeviceListView />);
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('You are signed out - sign in');
    expect(screen.getByRole('link', { name: 'sign in' })).toHaveAttribute('href', '/login-screen');
    expect(screen.queryByText('Failed to load devices. Check your connection and try again.')).toBeNull();
  });

  it('names a service failure and does not offer the sign-in link', async () => {
    vi.mocked(api.listDevices).mockRejectedValue(new ApiError(503, 'down', 'unavailable'));
    render(<DeviceListView />);
    await waitFor(() => {
      expect(screen.getByRole('alert').textContent).toContain('The service failed while loading devices (HTTP 503).');
    });
    expect(screen.queryByRole('link', { name: 'sign in' })).toBeNull();
  });
});
