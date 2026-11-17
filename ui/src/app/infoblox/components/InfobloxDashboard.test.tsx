import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import InfobloxDashboard from './InfobloxDashboard';

vi.mock('@/lib/apiClient', () => ({
  api: {
    netbridgeGet: vi.fn(async (path: string) => {
      if (path.startsWith('/infoblox/health')) {
        return {
          configured: true,
          ok: true,
          message: '',
          grid: 'PnP',
          version: 'v2.12',
          members: [
            { hostname: 'gm.example.com', ip: '10.1.1.10', status: 'Failed', healthy: false, group: 'grid', roles: ['VNIOS', 'Active'], cpu: 12, memory: 40, diskRoot: 20, diskOpt: 30, services: [{ name: 'DNS', running: true }, { name: 'DHCP', running: false }], issues: ['DHCP is failed'] },
            { hostname: 'member.example.com', ip: '10.1.1.11', status: 'Working', healthy: true, group: 'member', roles: ['Not Configured'], services: [{ name: 'DNS', running: true }], issues: [] },
          ],
        };
      }
      return {};
    }),
  },
}));

describe('Infoblox dashboard', () => {
  it('shows the grid and links each member to its detail page', async () => {
    render(<InfobloxDashboard />);
    expect(await screen.findByRole('heading', { name: 'Infoblox' })).toBeInTheDocument();
    expect(await screen.findByText('PnP')).toBeInTheDocument();
    expect(screen.getByText('v2.12')).toBeInTheDocument();
    expect(screen.getByText('1 of 2')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Grid Master' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Open gm.example.com' })).toHaveAttribute('href', '/infoblox/gm.example.com');
    expect(screen.getByText('DHCP')).toBeInTheDocument();
    expect(screen.getByText('DHCP is failed')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'member.example.com' })).toBeInTheDocument();
    expect(screen.getByText('12%')).toBeInTheDocument();
  });
});
