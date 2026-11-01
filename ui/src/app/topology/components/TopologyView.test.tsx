import React from 'react';
import { act, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/lib/apiError';
import { api } from '@/lib/apiClient';
import type { DeviceDetailData } from '@/lib/types';
import TopologyView from './TopologyView';

const queryState = vi.hoisted(() => ({ value: '' }));

vi.mock('next/link', () => ({
  default: ({ href, children, ...props }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...props}>{children}</a>
  ),
}));

vi.mock('next/navigation', () => ({
  useSearchParams: () => new URLSearchParams(queryState.value),
}));

vi.mock('@/lib/apiMode', () => ({
  isMockMode: () => false,
  devicePath: (id: string) => `/device-detail?id=${id}`,
}));

vi.mock('@/lib/apiClient', () => ({
  api: { getDevice: vi.fn(), listSiteDevices: vi.fn(), listSites: vi.fn() },
}));

function device(id: string, hostname: string): DeviceDetailData {
  return {
    id,
    hostname,
    role: 'Core switch',
    site: 'Rotterdam',
    siteId: '1',
    mgmtIp: '10.1.0.1',
    modelFamily: 'C9500',
    health: 'healthy',
    uptime: '9d',
    lastPoll: '1m',
    firmware: '17.9',
    serialMasked: 'ABC••••••456',
    faceplate: { form_factor: 'access-switch-48', role: 'Core switch', ports: [] },
    issues: [],
    checks: [],
    hardware: [],
    checkRunAt: '',
  };
}

function deferred<T>() {
  let resolve: (value: T) => void = () => undefined;
  let reject: (reason?: unknown) => void = () => undefined;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

describe('TopologyView client navigation', () => {
  beforeEach(() => {
    queryState.value = '';
    window.history.pushState({}, '', '/');
    vi.mocked(api.getDevice).mockReset();
    vi.mocked(api.listSiteDevices).mockReset();
    vi.mocked(api.listSiteDevices).mockResolvedValue([]);
  });

  it('does not fetch a device until the id is in the query', async () => {
    vi.mocked(api.getDevice).mockImplementation(async (key: string) => {
      if (key === '10') return device('10', 'core-1');
      throw new ApiError(404, 'not_found', 'unknown device');
    });
    const { rerender } = render(<TopologyView />);
    expect(screen.queryByText(/unknown device/i)).toBeNull();
    expect(api.getDevice).not.toHaveBeenCalled();
    expect(screen.getByRole('status').textContent).toMatch(/loading topology/i);

    queryState.value = 'id=10&form=access-switch-48';
    rerender(<TopologyView />);
    expect(await screen.findByRole('heading', { level: 1, name: 'core-1' })).toBeInTheDocument();
    expect(api.getDevice).toHaveBeenCalledWith('10');
    expect(api.getDevice).not.toHaveBeenCalledWith('access-switch-48');
    expect(screen.queryByText(/unknown device/i)).toBeNull();
  });

  it('ignores a slow unknown-device response when the id changes', async () => {
    const first = deferred<DeviceDetailData>();
    vi.mocked(api.getDevice).mockImplementation((key: string) => {
      if (key === '1') return first.promise;
      if (key === '2') return Promise.resolve(device('2', 'edge-2'));
      return Promise.reject(new ApiError(404, 'not_found', 'unknown device'));
    });
    queryState.value = 'id=1';
    const { rerender } = render(<TopologyView />);
    await waitFor(() => expect(api.getDevice).toHaveBeenCalledWith('1'));

    queryState.value = 'id=2';
    rerender(<TopologyView />);
    expect(await screen.findByRole('heading', { level: 1, name: 'edge-2' })).toBeInTheDocument();

    await act(async () => {
      first.reject(new ApiError(404, 'not_found', 'unknown device'));
      await first.promise.catch(() => undefined);
    });
    expect(screen.getByRole('heading', { level: 1, name: 'edge-2' })).toBeInTheDocument();
    expect(screen.queryByText(/unknown device/i)).toBeNull();
  });
});
