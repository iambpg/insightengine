import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { DeviceDiscoveryJob, UnapprovedDevice } from '@/lib/contract';
import { api } from '@/lib/apiClient';
import NotInNetBoxView from './NotInNetBoxView';

vi.mock('@/lib/apiMode', () => ({ isMockMode: () => false }));

vi.mock('@/lib/apiClient', () => ({
  api: {
    listDiscovered: vi.fn(),
    listScans: vi.fn(),
    discoveryCatalog: vi.fn(),
    discoverDevice: vi.fn(),
    getDeviceDiscovery: vi.fn(),
    startScan: vi.fn(),
  },
}));

const running: DeviceDiscoveryJob = {
  id: '9',
  ip: '10.9.9.9',
  status: 'running',
  message: 'SNMP reachable via profile default',
  steps: [
    { name: 'snmp', status: 'done', message: 'SNMP reachable via profile default' },
    { name: 'discover', status: 'running', message: 'Discovering.' },
    { name: 'macsuck', status: 'queued', message: 'Waiting for discover to finish.' },
    { name: 'arpnip', status: 'queued', message: 'Waiting for discover to finish.' },
  ],
};

function foundDevice(): UnapprovedDevice {
  return {
    id: 'disc-1',
    ip: '10.9.9.9',
    hostname: 'sw-new',
    sysName: 'sw-new',
    firstSeen: '2026-11-01T00:00:00Z',
    lastSeen: '2026-11-01T00:00:00Z',
    suggested: { role: 'Access switch', site: 'Lab' },
  };
}

describe('NotInNetBoxView device discover', () => {
  beforeEach(() => {
    vi.mocked(api.listDiscovered).mockReset();
    vi.mocked(api.listScans).mockReset();
    vi.mocked(api.discoveryCatalog).mockReset();
    vi.mocked(api.discoverDevice).mockReset();
    vi.mocked(api.getDeviceDiscovery).mockReset();
    vi.mocked(api.startScan).mockReset();
    vi.mocked(api.discoveryCatalog).mockResolvedValue({ roles: [], sites: [], platforms: [] });
    vi.mocked(api.listScans).mockResolvedValue([]);
    vi.mocked(api.listDiscovered).mockResolvedValue([]);
  });

  it('polls each step and highlights the device when discover finishes', async () => {
    vi.mocked(api.discoverDevice).mockResolvedValue(running);
    vi.mocked(api.getDeviceDiscovery).mockResolvedValue({
      ...running,
      status: 'done',
      message: 'Discovery finished.',
      steps: running.steps.map((step) => ({ ...step, status: 'done' as const, message: step.name })),
    });
    vi.mocked(api.listDiscovered).mockImplementation(async () =>
      vi.mocked(api.getDeviceDiscovery).mock.calls.length ? [foundDevice()] : []
    );
    const user = userEvent.setup();
    render(<NotInNetBoxView />);
    await screen.findByRole('heading', { name: 'Discover device' });
    await user.type(screen.getByLabelText('IP address'), '10.9.9.9');
    await user.click(screen.getByRole('button', { name: 'Discover' }));
    expect(api.discoverDevice).toHaveBeenCalledWith('10.9.9.9', false);
    expect(await screen.findByText('Discovering.')).toBeInTheDocument();
    const row = (await screen.findAllByText('sw-new'))[0];
    expect(row.closest('tr')).toHaveAttribute('data-highlight', 'new');
  });

  it('shows the Netdisco error text', async () => {
    vi.mocked(api.discoverDevice).mockResolvedValue(running);
    vi.mocked(api.getDeviceDiscovery).mockResolvedValue({
      ...running,
      status: 'error',
      message: 'discover failed: could not SNMP connect',
      steps: [
        running.steps[0],
        { name: 'discover', status: 'error', message: 'discover failed: could not SNMP connect' },
        { name: 'macsuck', status: 'error', message: 'Not started because discover failed.' },
        { name: 'arpnip', status: 'error', message: 'Not started because discover failed.' },
      ],
    });
    const user = userEvent.setup();
    render(<NotInNetBoxView />);
    await screen.findByLabelText('IP address');
    await user.type(screen.getByLabelText('IP address'), '10.9.9.9');
    await user.click(screen.getByRole('checkbox', { name: 'Also discover CDP/LLDP neighbours' }));
    await user.click(screen.getByRole('button', { name: 'Discover' }));
    expect(api.discoverDevice).toHaveBeenCalledWith('10.9.9.9', true);
    expect((await screen.findAllByText('discover failed: could not SNMP connect')).length).toBeGreaterThan(0);
  });

  it('keeps prefix scans on the prefix endpoint', async () => {
    vi.mocked(api.startScan).mockResolvedValue({
      id: '3',
      target: 'prefix',
      value: '10.2.0.0/24',
      status: 'queued',
      startedAt: '2026-11-01T00:00:00Z',
      message: 'Queued a Netdisco walk of that prefix.',
    });
    const user = userEvent.setup();
    render(<NotInNetBoxView />);
    await screen.findByLabelText('IP address');
    await user.selectOptions(screen.getByRole('combobox'), 'prefix');
    await user.type(screen.getByLabelText('Prefix'), '10.2.0.0/24');
    await user.click(screen.getByRole('button', { name: 'Discover' }));
    await waitFor(() => expect(api.startScan).toHaveBeenCalledWith('prefix', '10.2.0.0/24'));
    expect(api.discoverDevice).not.toHaveBeenCalled();
  });
});
