import React from 'react';
import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/lib/apiError';
import { api } from '@/lib/apiClient';
import type { DeviceDetailData } from '@/lib/types';
import DeviceDetailView from './DeviceDetailView';

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
  api: {
    getDevice: vi.fn(),
    discoverDevice: vi.fn(),
    getDeviceDiscovery: vi.fn(),
    getTelemetryConfig: vi.fn(),
    getIpSlaConfig: vi.fn(),
    listAccessPoints: vi.fn(),
  },
}));

vi.mock('./DeviceGraphs', () => ({ default: () => null }));
vi.mock('@/components/faceplate/Faceplate', () => ({
  default: () => null,
  FaceplateLegend: () => null,
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
    status: 'active',
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

function deferred<T>() {
  let resolve: (value: T) => void = () => undefined;
  let reject: (reason?: unknown) => void = () => undefined;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

describe('DeviceDetailView client navigation', () => {
  beforeEach(() => {
    queryState.value = '';
    window.history.pushState({}, '', '/');
    vi.mocked(api.getDevice).mockReset();
    vi.mocked(api.discoverDevice).mockReset();
    vi.mocked(api.getDeviceDiscovery).mockReset();
  });

  afterEach(() => {
    window.history.pushState({}, '', '/');
  });

  it('stays on loading while the id is missing, then shows that device', async () => {
    vi.mocked(api.getDevice).mockImplementation(async (key: string) => {
      if (key === '42') return device('42', 'edge-42');
      throw new ApiError(404, 'not_found', 'unknown device');
    });

    const { rerender } = render(<DeviceDetailView />);
    expect(screen.queryByText(/unknown device/i)).toBeNull();
    expect(screen.queryByText(/needs a device id/i)).toBeNull();
    expect(api.getDevice).not.toHaveBeenCalled();
    expect(screen.getByRole('status').textContent).toMatch(/loading device/i);

    queryState.value = 'form=access-switch-48';
    rerender(<DeviceDetailView />);
    expect(screen.queryByText(/unknown device/i)).toBeNull();
    expect(api.getDevice).not.toHaveBeenCalled();

    queryState.value = 'id=42&form=access-switch-48';
    rerender(<DeviceDetailView />);
    expect(screen.queryByText(/unknown device/i)).toBeNull();
    expect(await screen.findByRole('heading', { level: 1, name: 'edge-42' })).toBeInTheDocument();
    expect(api.getDevice).toHaveBeenCalledTimes(1);
    expect(api.getDevice).toHaveBeenCalledWith('42');
    expect(screen.getByRole('button', { name: /Controller config/ })).toBeInTheDocument();
    expect(screen.queryByText(/unknown device/i)).toBeNull();
  });

  it('asks for an id when the url never has one and does not fetch a faceplate key', async () => {
    queryState.value = 'form=ceiling-ap';
    render(<DeviceDetailView />);
    expect(await screen.findByRole('alert')).toHaveTextContent(/needs a device id/i);
    expect(screen.queryByText(/unknown device/i)).toBeNull();
    expect(api.getDevice).not.toHaveBeenCalled();
  });

  it('shows unknown device only after a 404 for the id in the url', async () => {
    queryState.value = 'id=99&form=generic';
    vi.mocked(api.getDevice).mockRejectedValue(new ApiError(404, 'not_found', 'unknown device'));
    render(<DeviceDetailView />);
    expect(await screen.findByRole('alert')).toHaveTextContent('unknown device');
    expect(api.getDevice).toHaveBeenCalledTimes(1);
    expect(api.getDevice).toHaveBeenCalledWith('99');
  });

  it('drops a slow response for the previous id', async () => {
    const first = deferred<DeviceDetailData>();
    vi.mocked(api.getDevice).mockImplementation((key: string) => {
      if (key === '1') return first.promise;
      if (key === '2') return Promise.resolve(device('2', 'edge-2'));
      return Promise.reject(new ApiError(404, 'not_found', 'unknown device'));
    });

    queryState.value = 'id=1&form=access-switch-24';
    const { rerender } = render(<DeviceDetailView />);
    await waitFor(() => expect(api.getDevice).toHaveBeenCalledWith('1'));
    expect(screen.queryByText(/unknown device/i)).toBeNull();
    expect(screen.queryByRole('heading', { level: 1, name: 'edge-1' })).toBeNull();

    queryState.value = 'id=2&form=access-switch-48';
    rerender(<DeviceDetailView />);
    expect(await screen.findByRole('heading', { level: 1, name: 'edge-2' })).toBeInTheDocument();

    await act(async () => {
      first.resolve(device('1', 'edge-1'));
      await first.promise;
    });
    expect(screen.getByRole('heading', { level: 1, name: 'edge-2' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { level: 1, name: 'edge-1' })).toBeNull();
    expect(screen.queryByText(/unknown device/i)).toBeNull();
  });

  it('drops a slow 404 for the previous id', async () => {
    const first = deferred<DeviceDetailData>();
    vi.mocked(api.getDevice).mockImplementation((key: string) => {
      if (key === '1') return first.promise;
      if (key === '2') return Promise.resolve(device('2', 'edge-2'));
      return Promise.reject(new ApiError(404, 'not_found', 'unknown device'));
    });

    queryState.value = 'id=1';
    const { rerender } = render(<DeviceDetailView />);
    await waitFor(() => expect(api.getDevice).toHaveBeenCalledWith('1'));

    queryState.value = 'id=2&form=access-switch-48';
    rerender(<DeviceDetailView />);
    expect(await screen.findByRole('heading', { level: 1, name: 'edge-2' })).toBeInTheDocument();

    await act(async () => {
      first.reject(new ApiError(404, 'not_found', 'unknown device'));
      await first.promise.catch(() => undefined);
    });
    expect(screen.getByRole('heading', { level: 1, name: 'edge-2' })).toBeInTheDocument();
    expect(screen.queryByText(/unknown device/i)).toBeNull();
  });

  it('reads the id from the address bar when the router snapshot is still empty', async () => {
    window.history.pushState({}, '', '/device-detail?id=7&form=generic');
    vi.mocked(api.getDevice).mockImplementation(async (key: string) => {
      if (key === '7') return device('7', 'core-7');
      throw new ApiError(404, 'not_found', 'unknown device');
    });
    render(<DeviceDetailView />);
    expect(screen.queryByText(/unknown device/i)).toBeNull();
    expect(await screen.findByRole('heading', { level: 1, name: 'core-7' })).toBeInTheDocument();
    expect(api.getDevice).toHaveBeenCalledWith('7');
    expect(api.getDevice).not.toHaveBeenCalledWith('switch-stack');
  });

  it('rediscovers the management address and shows the Netdisco error', async () => {
    queryState.value = 'id=42';
    vi.mocked(api.getDevice).mockResolvedValue(device('42', 'edge-42'));
    vi.mocked(api.discoverDevice).mockResolvedValue({
      id: '9',
      ip: '10.1.0.2',
      status: 'running',
      message: 'SNMP reachable via profile default',
      steps: [
        { name: 'snmp', status: 'done', message: 'SNMP reachable via profile default' },
        { name: 'discover', status: 'running', message: 'Discovering.' },
        { name: 'macsuck', status: 'queued', message: 'Waiting for discover to finish.' },
        { name: 'arpnip', status: 'queued', message: 'Waiting for discover to finish.' },
      ],
    });
    vi.mocked(api.getDeviceDiscovery).mockResolvedValue({
      id: '9',
      ip: '10.1.0.2',
      status: 'error',
      message: 'discover failed: could not SNMP connect',
      steps: [
        { name: 'snmp', status: 'done', message: 'SNMP reachable via profile default' },
        { name: 'discover', status: 'error', message: 'discover failed: could not SNMP connect' },
        { name: 'macsuck', status: 'error', message: 'Not started because discover failed.' },
        { name: 'arpnip', status: 'error', message: 'Not started because discover failed.' },
      ],
    });
    const user = userEvent.setup();
    render(<DeviceDetailView />);
    await user.click(await screen.findByRole('button', { name: 'Rediscover' }));
    expect(api.discoverDevice).toHaveBeenCalledWith('10.1.0.2', false);
    expect((await screen.findAllByText('discover failed: could not SNMP connect')).length).toBeGreaterThan(0);
  });
});
