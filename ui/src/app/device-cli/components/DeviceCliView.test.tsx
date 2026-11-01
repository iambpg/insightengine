import React from 'react';
import { act, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/lib/apiError';
import { api } from '@/lib/apiClient';
import type { CliCatalog, DeviceDetailData } from '@/lib/types';
import DeviceCliView from './DeviceCliView';

const queryState = vi.hoisted(() => ({ value: '' }));

vi.mock('next/link', () => ({
  default: ({ href, children, className }: { href: string; children: React.ReactNode; className?: string }) => (
    <a href={href} className={className}>{children}</a>
  ),
}));

vi.mock('next/navigation', () => ({
  useSearchParams: () => new URLSearchParams(queryState.value),
}));

vi.mock('@/lib/apiMode', () => ({
  isMockMode: () => false,
  devicePath: (id: string, form?: string) => `/device-detail?id=${encodeURIComponent(id)}${form ? `&form=${encodeURIComponent(form)}` : ''}`,
}));

vi.mock('@/lib/apiClient', () => ({
  api: { getDevice: vi.fn(), getDeviceCli: vi.fn() },
}));

function device(id: string, hostname: string): DeviceDetailData {
  return {
    id,
    hostname,
    role: 'Access switch',
    site: 'Rotterdam',
    siteId: '1',
    mgmtIp: '10.1.0.2',
    modelFamily: 'C9300-48P',
    health: 'healthy',
    uptime: '3d',
    lastPoll: '1m',
    firmware: '17.9',
    serialMasked: 'ABC••••••456',
    faceplate: { form_factor: 'access-switch-48', role: 'Access switch', ports: [] },
    issues: [],
    checks: [],
    hardware: [],
    checkRunAt: '',
  };
}

function catalog(hostname: string): CliCatalog {
  return {
    platform: 'ios',
    platformLabel: 'Cisco IOS',
    commands: [],
    credentialsConfigured: true,
    hostname,
    mgmtIp: '10.1.0.2',
    message: '',
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

describe('DeviceCliView client navigation', () => {
  beforeEach(() => {
    queryState.value = '';
    window.history.pushState({}, '', '/');
    vi.mocked(api.getDevice).mockReset();
    vi.mocked(api.getDeviceCli).mockReset();
    vi.mocked(api.getDeviceCli).mockImplementation(async () => catalog('device'));
  });

  it('does not fetch until the id arrives, then shows that device', async () => {
    vi.mocked(api.getDevice).mockImplementation(async (key: string) => {
      if (key === '42') return device('42', 'edge-42');
      throw new ApiError(404, 'not_found', 'unknown device');
    });
    const { rerender } = render(<DeviceCliView />);
    expect(screen.queryByText(/unknown device/i)).toBeNull();
    expect(screen.queryByText(/needs a device id/i)).toBeNull();
    expect(api.getDevice).not.toHaveBeenCalled();

    queryState.value = 'id=42&form=access-switch-48';
    rerender(<DeviceCliView />);
    expect(await screen.findByRole('heading', { level: 1, name: 'edge-42' })).toBeInTheDocument();
    expect(api.getDevice).toHaveBeenCalledWith('42');
    expect(api.getDevice).not.toHaveBeenCalledWith('access-switch-48');
    expect(api.getDevice).not.toHaveBeenCalledWith('switch-stack');
    expect(screen.queryByText(/unknown device/i)).toBeNull();
  });

  it('ignores a slow unknown-device response after the id changes', async () => {
    const first = deferred<DeviceDetailData>();
    vi.mocked(api.getDevice).mockImplementation((key: string) => {
      if (key === '1') return first.promise;
      if (key === '2') return Promise.resolve(device('2', 'edge-2'));
      return Promise.reject(new ApiError(404, 'not_found', 'unknown device'));
    });
    queryState.value = 'id=1';
    const { rerender } = render(<DeviceCliView />);
    await waitFor(() => expect(api.getDevice).toHaveBeenCalledWith('1'));

    queryState.value = 'id=2';
    rerender(<DeviceCliView />);
    expect(await screen.findByRole('heading', { level: 1, name: 'edge-2' })).toBeInTheDocument();

    await act(async () => {
      first.reject(new ApiError(404, 'not_found', 'unknown device'));
      await first.promise.catch(() => undefined);
    });
    expect(screen.getByRole('heading', { level: 1, name: 'edge-2' })).toBeInTheDocument();
    expect(screen.queryByText(/unknown device/i)).toBeNull();
  });
});
