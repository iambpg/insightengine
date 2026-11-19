import React from 'react';
import fs from 'fs';
import os from 'os';
import path from 'path';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type { DeviceDetailData, DeviceNeighbor } from '@/lib/types';
import CdpNeighbourPanel from './CdpNeighbourPanel';

vi.mock('next/link', () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => <a href={href}>{children}</a>,
}));

function neighbour(index: number, extra: Partial<DeviceNeighbor> = {}): DeviceNeighbor {
  const kinds = [
    { remoteName: 'dist-sw-02', remotePlatform: 'WS-C9300-48P', remoteAddress: '10.22.1.2', remotePort: 'Te1/0/13' },
    { remoteName: 'core-rtr-01', remotePlatform: 'Cisco ISR4451 Router', remoteAddress: '10.22.1.1', remotePort: 'Gi0/0/0' },
    { remoteName: 'ap-fl2-014', remotePlatform: 'C9120AXI-E', remoteAddress: '10.22.8.14', remotePort: 'Gig0' },
    { remoteName: 'fw-ams01-a', remotePlatform: 'PA-460', remoteAddress: '10.22.1.9', remotePort: 'ethernet1/1' },
  ];
  const sample = kinds[index % kinds.length];
  return {
    localPort: `Gi1/0/${index + 1}`,
    remoteName: `${sample.remoteName}${index >= kinds.length ? `-${index}` : ''}`,
    remotePort: sample.remotePort,
    remoteAddress: sample.remoteAddress.replace(/(\d+)$/, String(10 + index)),
    protocol: 'cdp',
    source: index % 5 === 4 ? 'lldp' : 'cdp',
    remotePlatform: sample.remotePlatform,
    remoteDeviceId: sample.remoteName,
    remoteCapabilities: sample.remotePlatform,
    lastSeen: '2026-11-19 12:00 UTC',
    ...extra,
  };
}

function device(neighbors: DeviceNeighbor[], extra: Partial<DeviceDetailData> = {}): DeviceDetailData {
  return {
    id: '42',
    hostname: 'sw-rot04-07',
    role: 'Access switch',
    site: 'Rotterdam',
    mgmtIp: '10.22.14.17',
    modelFamily: 'C9300-24P',
    health: 'healthy',
    uptime: '1d',
    lastPoll: '1m',
    firmware: '17.9',
    serialMasked: 'ABC••••••456',
    faceplate: { form_factor: 'access-switch-24', role: 'Access switch', modelName: 'C9300-24P', ports: [] },
    issues: [],
    checks: [],
    hardware: [],
    checkRunAt: '',
    interfaces: [
      { name: 'GigabitEthernet1/0/1', type: '1000base-t', enabled: true, mac: '', description: 'uplink' },
    ],
    addresses: [{ address: '10.22.14.17/24', interface: 'Vlan10', status: 'active' }],
    neighbors,
    ...extra,
  };
}

function frame(neighbors: DeviceNeighbor[], extra: Partial<DeviceDetailData> = {}) {
  return (
    <div style={{ width: 1100 }}>
      <CdpNeighbourPanel device={device(neighbors, extra)} />
    </div>
  );
}

describe('CDP neighbour panel', () => {
  it('renders one chassis-free panel and keeps this device selected', () => {
    const { container } = render(frame([neighbour(0), neighbour(1), neighbour(2), neighbour(3)]));
    expect(screen.getAllByTestId('cdp-neighbour-panel')).toHaveLength(1);
    expect(container.querySelector('[data-chassis]')).toBeNull();
    const panel = screen.getByTestId('cdp-neighbour-panel');
    expect(within(panel).getByRole('heading', { name: 'CDP Neighbors' })).toBeInTheDocument();
    expect(within(panel).getByTestId('cdp-status')).toHaveTextContent('Active');
    expect(within(panel).getByText('10.22.14.17')).toBeInTheDocument();
    expect(within(panel).getAllByTestId(/cdp-node-/)).toHaveLength(4);
  });

  it('selects a neighbour and lists the same count on the Neighbors tab', async () => {
    const user = userEvent.setup();
    render(frame([neighbour(0), neighbour(1), neighbour(2), neighbour(3, { netboxId: '9' })]));
    const panel = screen.getByTestId('cdp-neighbour-panel');
    await user.hover(within(panel).getByTestId('cdp-node-0'));
    expect(within(panel).getByText('Gi1/0/1 → Te1/0/13')).toBeInTheDocument();
    await user.click(within(panel).getByTestId('cdp-node-1'));
    expect(within(panel).getByTestId('cdp-node-1')).toHaveStyle({ boxShadow: '0 0 0 3px #22c55e, 0 0 14px #4ade80' });
    expect(within(panel).getByText('10.22.1.11')).toBeInTheDocument();
    expect(within(panel).getAllByText('Cisco ISR4451 Router').length).toBeGreaterThan(0);
    await user.click(within(panel).getByRole('tab', { name: 'Neighbors (4)' }));
    const list = within(panel).getByRole('list');
    expect(within(list).getAllByRole('button')).toHaveLength(4);
    await user.click(within(list).getByRole('button', { name: /fw-ams01-a/ }));
    expect(within(panel).getByRole('link', { name: 'Open device' })).toBeInTheDocument();
  });

  it('keeps the interface and address lines on the Interfaces tab', async () => {
    const user = userEvent.setup();
    render(frame([neighbour(0)]));
    const panel = screen.getByTestId('cdp-neighbour-panel');
    await user.click(within(panel).getByRole('tab', { name: 'Interfaces' }));
    expect(within(panel).getByText('GigabitEthernet1/0/1 · uplink · enabled · 1000base-t')).toBeInTheDocument();
    expect(within(panel).getByText('10.22.14.17/24 on Vlan10')).toBeInTheDocument();
  });

  it('shows the empty neighbour sentence and a grey dashed line for an unknown peer', () => {
    render(frame([]));
    const panel = screen.getByTestId('cdp-neighbour-panel');
    expect(within(panel).getByText('No Netdisco LLDP or CDP neighbours were returned.')).toBeInTheDocument();
    expect(within(panel).getByTestId('cdp-status')).toHaveTextContent('No data');
    expect(within(panel).queryByTestId(/cdp-node-/)).toBeNull();
  });

  it('draws a grey dashed line when the neighbour has no name or address and caps the ring at 12', () => {
    const rows = Array.from({ length: 13 }, (_, index) => neighbour(index));
    rows[0] = neighbour(0, { remoteName: '', remoteAddress: '', remotePlatform: '' });
    const { container } = render(frame(rows));
    const panel = screen.getByTestId('cdp-neighbour-panel');
    expect(within(panel).getAllByTestId(/cdp-node-/)).toHaveLength(12);
    expect(within(panel).getByTestId('cdp-more')).toHaveTextContent('+1 more');
    expect(within(panel).getByRole('tab', { name: 'Neighbors (13)' })).toBeInTheDocument();
    const dashed = container.querySelector('line[stroke-dasharray]');
    expect(dashed).toBeTruthy();
    expect(dashed).toHaveAttribute('stroke', '#94a3b8');
  });

  it('keeps a neighbour note in place of the empty sentence', () => {
    render(frame([], { neighborNote: 'Netdisco has not discovered this device yet' }));
    const panel = screen.getByTestId('cdp-neighbour-panel');
    expect(within(panel).getByText('Netdisco has not discovered this device yet')).toBeInTheDocument();
    expect(within(panel).queryByText('No Netdisco LLDP or CDP neighbours were returned.')).toBeNull();
  });

  it('writes the panel frames when IE_CDP_SHOTS is set', async () => {
    if (process.env.IE_CDP_SHOTS !== '1') return;
    const user = userEvent.setup();
    const dir = process.env.IE_CDP_SHOT_DIR || path.join(os.tmpdir(), 'cdp-shots');
    fs.mkdirSync(dir, { recursive: true });
    const cases: Array<[string, DeviceNeighbor[], number | null]> = [
      ['4-neighbours', [neighbour(0), neighbour(1), neighbour(2), neighbour(3)], null],
      ['12-plus-neighbours', Array.from({ length: 13 }, (_, index) => neighbour(index)), null],
      ['neighbour-selected', [neighbour(0), neighbour(1), neighbour(2), neighbour(3, { netboxId: '9' })], 1],
      ['no-neighbours', [], null],
    ];
    for (const [name, rows, pick] of cases) {
      const { container, unmount } = render(frame(rows));
      if (pick !== null) await user.click(screen.getByTestId(`cdp-node-${pick}`));
      const html = `<!doctype html><html><head><meta charset="utf-8"><style>body{margin:0;font-family:ui-sans-serif,system-ui,sans-serif}button,a{font-family:inherit}</style></head><body>${container.innerHTML}</body></html>`;
      fs.writeFileSync(path.join(dir, `${name}.html`), html);
      unmount();
    }
    expect(fs.existsSync(path.join(dir, 'no-neighbours.html'))).toBe(true);
  });
});
