import React from 'react';
import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/lib/apiError';
import { api } from '@/lib/apiClient';
import ApLivePanel from './ApLivePanel';

vi.mock('next/link', () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => <a href={href}>{children}</a>,
}));

vi.mock('@/lib/apiClient', () => ({
  api: { getAccessPointLive: vi.fn() },
}));

const fetched = '2026-11-22T10:15:04.000Z';

const iosxe = {
  accessPoint: {
    name: 'AP-LOBBY-12',
    mac: '00:a2:89:10:11:44',
    ip: '10.20.30.44',
    model: 'C9120AXI-E',
    serial: 'FGL2345AB12',
    ios: '17.9.4.27',
    mode: 'Local',
    adminState: 'Enabled',
    operState: 'Registered',
    uptime: '3 days 4 hours 12 minutes 8 seconds',
    joinTime: '11/18/2026 08:14:02',
    location: 'Floor 2',
    country: 'ZA',
    primaryController: 'wlc-rot-01',
    secondaryController: 'wlc-rot-02',
    siteTag: 'site-rotterdam',
    policyTag: 'policy-corp',
    rfTag: 'rf-default',
    apGroup: null,
    flexGroup: null,
    power: 'PoE/Full Power',
    cdpSwitch: 'sw-rot-01',
    cdpPort: 'GigabitEthernet1/0/14',
    radios: [
      { slot: '0', admin: 'Enabled', oper: 'Up', channel: '6', txPower: '* 2/8 (15 dBm)' },
      { slot: '1', admin: 'Enabled', oper: 'Up', channel: '36', txPower: '* 1/8 (17 dBm)' },
    ],
  },
  wlc: { id: '1', name: 'wlc-rot-01', ip: '10.20.1.10', platform: 'iosxe' },
  resolvedBy: 'metrics',
  fetchedAt: fetched,
  cached: false,
  attempts: [{ wlc: 'wlc-rot-01', result: 'ok', code: '', message: '' }],
};

const aireos = {
  accessPoint: {
    name: 'AP-CAFE-3',
    mac: '00:b4:c1:20:30:40',
    ip: '10.20.30.45',
    model: 'AIR-AP2802I-E-K9',
    serial: 'FGL998877665',
    ios: '8.10.190.0',
    mode: 'FlexConnect',
    adminState: 'ADMIN_ENABLED',
    operState: 'REGISTERED',
    uptime: '2 days, 03 h 11 m 04 s',
    joinTime: null,
    location: 'Cafe',
    country: 'ZA',
    primaryController: 'wlc-aireos-01',
    secondaryController: 'wlc-aireos-02',
    siteTag: null,
    policyTag: null,
    rfTag: null,
    apGroup: 'default-group',
    flexGroup: 'flex-rot',
    power: 'PoE/Full Power',
    cdpSwitch: 'sw-cafe-1',
    cdpPort: 'GigabitEthernet1/0/4',
    radios: [{ slot: '0', admin: 'Enabled', oper: 'Up', channel: '1', txPower: '*1/8 (17 dBm)' }],
  },
  wlc: { id: '2', name: 'wlc-aireos-01', ip: '10.20.1.20', platform: 'aireos' },
  resolvedBy: 'search',
  fetchedAt: fetched,
  cached: false,
  attempts: [
    { wlc: 'wlc-rot-01', result: 'not-found', code: 'ap_not_found_on_wlc', message: '' },
    { wlc: 'wlc-aireos-01', result: 'ok', code: '', message: '' },
  ],
};

const errors: { code: string; status: number; message: string; details?: unknown; link?: string }[] = [
  {
    code: 'no_ssh_credentials',
    status: 409,
    message: 'No SSH credentials are saved for wlc-rot-01. Save them in Device CLI for that wireless controller.',
    details: { wlc: { id: '42', name: 'wlc-rot-01' } },
    link: '/device-cli?id=42&form=wireless-controller',
  },
  { code: 'no_management_ip', status: 409, message: 'wlc-rot-01 has no management IP, so SSH was not attempted.' },
  { code: 'wlc_unreachable', status: 502, message: 'Could not open SSH to wlc-rot-01 (10.20.1.10). TCP 22 timed out or was refused.' },
  { code: 'wlc_auth_failed', status: 502, message: 'SSH authentication to wlc-rot-01 failed. Check the username and password saved for that wireless controller.' },
  { code: 'ap_not_found_on_wlc', status: 404, message: 'Access point AP-LOBBY-12 was not found on wlc-rot-01.' },
  { code: 'ap_not_found', status: 404, message: 'Access point AP-LOBBY-12 was not found on any wireless controller. Searched 2: wlc-rot-01, wlc-aireos-01.' },
  { code: 'bad_ap_name', status: 400, message: 'Access point name may only contain letters, numbers, dots, underscores, colons and hyphens, and must be at most 64 characters.' },
  { code: 'busy', status: 503, message: 'Live AP lookups are busy. Try again.' },
];

describe('ApLivePanel', () => {
  beforeEach(() => {
    vi.mocked(api.getAccessPointLive).mockReset();
  });

  it('renders the IOS-XE live facts', async () => {
    vi.mocked(api.getAccessPointLive).mockResolvedValue(iosxe);
    render(<ApLivePanel apKey="AP-LOBBY-12" wlcHint="wlc-rot-01" telemetryMissing={false} />);
    expect(await screen.findByText(/Live from/)).toHaveTextContent('Live from wlc-rot-01 (IOS-XE) · fetched 12:15:04 SAST');
    expect(screen.getByText('AP-LOBBY-12')).toBeInTheDocument();
    expect(screen.getByText('17.9.4.27')).toBeInTheDocument();
    expect(screen.getByText('site-rotterdam')).toBeInTheDocument();
    expect(screen.getByText('rf-default')).toBeInTheDocument();
    expect(screen.getByText(/Slot 0: admin Enabled · oper Up · channel 6/)).toBeInTheDocument();
    expect(screen.getByText('GigabitEthernet1/0/14')).toBeInTheDocument();
    expect(screen.getByText('Found by: metrics')).toBeInTheDocument();
    expect(screen.queryByText('FlexConnect group')).toBeNull();
  });

  it('renders the AireOS live facts', async () => {
    vi.mocked(api.getAccessPointLive).mockResolvedValue(aireos);
    render(<ApLivePanel apKey="AP-CAFE-3" wlcHint="" telemetryMissing={false} />);
    expect(await screen.findByText(/Live from/)).toHaveTextContent('Live from wlc-aireos-01 (AireOS) · fetched 12:15:04 SAST');
    expect(screen.getByText('default-group')).toBeInTheDocument();
    expect(screen.getByText('flex-rot')).toBeInTheDocument();
    expect(screen.getByText('ADMIN_ENABLED')).toBeInTheDocument();
    expect(screen.getByText('Found by: searched 2 controllers')).toBeInTheDocument();
    expect(screen.queryByText('Site tag')).toBeNull();
  });

  it('shows the prometheus note and both loading lines', async () => {
    vi.mocked(api.getAccessPointLive).mockReturnValue(new Promise(() => undefined));
    const { rerender } = render(<ApLivePanel apKey="AP-LOBBY-12" wlcHint="" telemetryMissing />);
    expect(await screen.findByTestId('ap-live-status')).toHaveTextContent('Searching controllers…');
    expect(screen.getByTestId('ap-live-no-prometheus')).toHaveTextContent('Not in Prometheus. Telemetry from this AP is not arriving.');
    rerender(<ApLivePanel apKey="AP-LOBBY-12" wlcHint="wlc-rot-01" telemetryMissing={false} />);
    expect(screen.getByTestId('ap-live-status')).toHaveTextContent('Asking wlc-rot-01…');
  });

  it.each(errors)('shows the $code error card', async (row) => {
    vi.mocked(api.getAccessPointLive).mockRejectedValue(new ApiError(row.status, row.code, row.message, row.details));
    render(<ApLivePanel apKey="AP-LOBBY-12" wlcHint="wlc-rot-01" telemetryMissing={false} />);
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(row.message);
    expect(screen.getByTestId(`ap-live-error-${row.code}`)).toBeInTheDocument();
    if (row.link) {
      expect(screen.getByRole('link', { name: /Device CLI/ })).toHaveAttribute('href', row.link);
    }
  });
});
