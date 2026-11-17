import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import IseDashboard from './IseDashboard';

vi.mock('@/lib/apiClient', () => ({
  api: {
    netbridgeGet: vi.fn(async (path: string) => {
      if (path.startsWith('/ise/health')) {
        return {
          configured: true,
          ok: true,
          message: '',
          version: '3.4.0.608',
          activeSessions: 120,
          nodes: [
            { hostname: 'pnp-pan1', ip: '10.96.1.150', status: 'Connected', healthy: true, group: 'main', roles: ['Primary Admin'], cpu: 4, memory: 80, diskRoot: 37, diskOpt: 27, ntp: true, directory: true, services: [{ name: 'Database', running: true }, { name: 'Web', running: true }, { name: 'NTP', running: true }], issues: [] },
            { hostname: 'pnp-mon2', ip: '10.97.1.151', status: 'NotReachable', healthy: false, group: 'main', roles: ['Primary Monitoring'], cpu: null, memory: null, diskRoot: null, diskOpt: null, ntp: null, directory: null, services: [], issues: ['Deployment status is NotReachable'] },
            { hostname: 'pnp-psn1', ip: '10.96.1.152', status: 'Connected', healthy: true, group: 'policy', roles: ['Policy Service'], ntp: true, directory: true },
          ],
        };
      }
      if (path.startsWith('/ise/operations')) {
        return {
          configured: true,
          sessions: {
            active: 40,
            windowMinutes: 30,
            recent: 2,
            message: 'This monitoring query does not include pass or fail.',
            rows: [{ user: 'alex', client: '10.1.1.20', nas: '10.129.32.16', server: 'pnp-psn1' }],
          },
          inventory: [{ name: 'Endpoints', count: 50 }, { name: 'Network devices', count: 8 }],
          dependencies: [
            { name: 'DNS', status: 'ok', detail: 'All 3 node names resolve to their deployment addresses.', rows: [{ name: 'pnp-pan1', status: 'ok', detail: 'Resolves to the deployment address.' }] },
            { name: 'Active Directory', status: 'ok', detail: 'Configured: PnP-AD for example.local.' },
            { name: 'Reachability', status: 'ok', detail: 'All 3 nodes accepted a connection on port 443.' },
            { name: 'Certificates', status: 'warning', detail: '1 of 72 trusted certificates are expired.', attention: [{ name: 'PnP Signing CA', days: -89, date: '2026-08-14' }] },
          ],
          alarms: { available: false, message: 'ISE did not expose an alarm list on the monitoring API.', rows: [] },
        };
      }
      return {};
    }),
  },
}));

describe('ISE dashboard', () => {
  it('shows session load and groups the main and policy nodes', async () => {
    render(<IseDashboard />);
    expect(await screen.findByRole('heading', { name: 'ISE' })).toBeInTheDocument();
    expect(await screen.findByText('3.4.0.608')).toBeInTheDocument();
    expect(screen.getByText('120')).toBeInTheDocument();
    expect(screen.getByText('2 of 3')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Main nodes' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'pnp-pan1' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Open pnp-pan1' })).toHaveAttribute('href', '/ise/pnp-pan1');
    expect(screen.getByRole('heading', { name: 'pnp-psn1' })).toBeInTheDocument();
    expect(screen.getAllByText('Healthy')).toHaveLength(2);
    expect(screen.getByText('NotReachable')).toBeInTheDocument();
    expect(screen.getByText('Primary Admin')).toBeInTheDocument();
    expect(screen.queryByText('4%')).not.toBeInTheDocument();
    expect(screen.queryByText('Database')).not.toBeInTheDocument();
    expect(screen.queryByText('Deployment status is NotReachable')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Expand pnp-pan1' }));
    const gauges = screen.getByRole('region', { name: 'pnp-pan1 gauges' });
    const services = screen.getByRole('region', { name: 'pnp-pan1 application services' });
    const issues = screen.getByRole('region', { name: 'pnp-pan1 deployment issues' });
    expect(gauges).toHaveTextContent('4%');
    expect(gauges).toHaveTextContent('80%');
    expect(services).toHaveTextContent('Database');
    expect(issues).toHaveTextContent('No deployment issues');
    fireEvent.click(screen.getByRole('button', { name: 'Expand pnp-mon2' }));
    expect(screen.getByRole('region', { name: 'pnp-mon2 deployment issues' })).toHaveTextContent('Deployment status is NotReachable');
    expect(screen.getByText('Policy Service')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Collapse pnp-pan1' }));
    expect(screen.queryByRole('region', { name: 'pnp-pan1 gauges' })).not.toBeInTheDocument();
    const dependencies = screen.getByRole('heading', { name: 'Dependencies' });
    const sessions = screen.getByRole('heading', { name: 'Sessions' });
    expect(dependencies.compareDocumentPosition(sessions)).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
    expect(screen.queryByText(/pass or fail/)).not.toBeInTheDocument();
    expect(sessions).toBeInTheDocument();
    expect(screen.getByText('alex')).toBeInTheDocument();
    expect(screen.getAllByText('pnp-psn1').length).toBeGreaterThan(1);
    expect(screen.getByRole('heading', { name: 'Configuration and inventory' })).toBeInTheDocument();
    expect(screen.getByText('Endpoints')).toBeInTheDocument();
    expect(screen.getByText('50')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Node health' })).toBeInTheDocument();
    expect(screen.getByText(/alarm list/)).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Dependencies' })).toBeInTheDocument();
    expect(screen.getByText(/All 3 node names resolve/)).toBeInTheDocument();
    expect(screen.getByText(/NTP client is running on 2 of 2 nodes/)).toBeInTheDocument();
    expect(screen.getByText(/example\.local/)).toBeInTheDocument();
    expect(screen.getByText(/1 of 72 trusted certificates are expired/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Open DNS' }));
    const drawer = screen.getByRole('dialog', { name: 'DNS' });
    expect(drawer).toHaveClass('left-0');
    expect(drawer).toHaveTextContent('Resolves to the deployment address.');
    fireEvent.click(screen.getByRole('button', { name: 'Close dependency panel' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Open Certificates' }));
    expect(screen.getByRole('dialog', { name: 'Certificates' })).toHaveTextContent('PnP Signing CA');
    expect(screen.getByRole('dialog', { name: 'Certificates' })).toHaveTextContent('Expired 89 days ago');
    fireEvent.click(screen.getByRole('button', { name: 'Expand pnp-pan1' }));
    fireEvent.mouseEnter(screen.getByRole('button', { name: 'Open Database on pnp-pan1' }));
    expect(screen.getByRole('tooltip')).toHaveTextContent('Click to open the full check');
    fireEvent.click(screen.getByRole('button', { name: 'Open Database on pnp-pan1' }));
    const service = screen.getByRole('dialog', { name: 'Database' });
    expect(service).toHaveClass('right-0');
    expect(service).toHaveTextContent('The oracle process is running on this node.');
    expect(service).toHaveTextContent('Root disk is 37% used');
    expect(service).toHaveTextContent('Application disk /opt is 27% used');
    expect(service).toHaveTextContent('Not returned for this service: database errors, replication and synchronization alarms.');
    expect(service).not.toHaveTextContent('Running status');
    expect(service).toHaveTextContent('Configuration, reporting, or authentication-related operations may be affected.');
    fireEvent.click(screen.getByRole('button', { name: 'Close service panel' }));
    expect(screen.queryByRole('dialog', { name: 'Database' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Open NTP on pnp-pan1' }));
    const ntp = screen.getByRole('dialog', { name: 'NTP' });
    expect(ntp).toHaveTextContent('The NTP process is running on this node.');
    expect(ntp).toHaveTextContent('Not returned for this service: synchronization status, configured time sources, clock offset.');
    expect(ntp).not.toHaveTextContent('does not confirm the clock is in sync');
  });
});
