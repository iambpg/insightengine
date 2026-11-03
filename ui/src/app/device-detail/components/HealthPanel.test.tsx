import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { DeviceHealthPanel } from '@/lib/types';
import HealthPanel from './HealthPanel';

const unsupported = (id: string, label: string) => ({
  id,
  label,
  supported: false,
  status: 'unsupported' as const,
  value: 'not supported by this device',
  detail: 'not supported by this device',
});

describe('HealthPanel', () => {
  it('shows a reading and the not-supported text for an access point', () => {
    const panel: DeviceHealthPanel = {
      profile: 'ap',
      profileLabel: 'Cisco access point',
      groups: [
        { id: 'memory', label: 'Memory', supported: false, status: 'unsupported', value: 'not supported by this device', detail: 'not supported by this device' },
        unsupported('fan', 'Fans'),
        unsupported('psu', 'Power supplies'),
        unsupported('temperature', 'Temperature'),
      ],
      interfacesSupported: false,
      interfaces: [],
      interfacesNote: 'not supported by this device',
      wlc: null,
      accessPoint: {
        note: 'Collected by Telegraf from the controller.',
        status: 'up',
        clients: 12,
        uptimeSeconds: 600,
        radios: [{ slot: '0', channel: 36, utilization: 0.2, clients: 12 }],
      },
    };
    render(<HealthPanel panel={panel} />);
    expect(screen.getAllByText('not supported by this device').length).toBeGreaterThan(3);
    expect(screen.getAllByText(/clients 12/).length).toBeGreaterThan(0);
    expect(screen.getByText(/channel 36/)).toBeInTheDocument();
  });

  it('highlights a critical-path interface', () => {
    const panel: DeviceHealthPanel = {
      profile: 'iosxe',
      profileLabel: 'Cisco IOS-XE',
      groups: [
        { id: 'memory', label: 'Memory', supported: true, status: 'warn', value: '91%', detail: 'Used ratio' },
        { id: 'fan', label: 'Fans', supported: true, status: 'ok', value: 'All normal', detail: 'States: normal' },
        { id: 'psu', label: 'Power supplies', supported: true, status: 'ok', value: '2 reported', detail: 'States: normal' },
        { id: 'temperature', label: 'Temperature', supported: true, status: 'ok', value: '47°C', detail: 'Highest sensor' },
      ],
      interfacesSupported: true,
      interfaces: [
        { name: 'Te1/1/1', ifIndex: '49', utilization: 0.82, dropsRate: 1.5, errorsRate: 0, criticalPath: true },
      ],
      interfacesNote: '',
      wlc: null,
      accessPoint: null,
    };
    render(<HealthPanel panel={panel} />);
    expect(screen.getByText('91%')).toBeInTheDocument();
    expect(screen.getByText('82%')).toBeInTheDocument();
    expect(screen.getByText('critical-path')).toBeInTheDocument();
  });
});
