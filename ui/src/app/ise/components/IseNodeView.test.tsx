import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import IseNodeView from './IseNodeView';

vi.mock('@/lib/apiClient', () => ({
  api: {
    netbridgeGet: vi.fn(async () => ({
      configured: true,
      ok: true,
      version: '3.4.0.608',
      message: '',
      node: {
        hostname: 'pnp-pan1',
        fqdn: 'pnp-pan1.example',
        ip: '10.96.1.150',
        status: 'Connected',
        healthy: true,
        group: 'main',
        roles: ['Primary Admin'],
        cpu: 4,
        cpus: [5, 3],
        memory: 80,
        uptime: '12 days 4 hours',
        description: 'Cisco Identity Services Engine',
        load: ['0.20', '0.18', '0.15'],
        filesystems: [{ name: '/', percent: 37, used: '40 GB', size: '100 GB' }, { name: '/opt', percent: 27, used: '20 GB', size: '80 GB' }],
        memoryParts: [{ name: 'Physical memory', percent: 80, used: '64 GB', size: '80 GB' }, { name: 'Swap space', percent: 2, used: '1 GB', size: '16 GB' }],
        services: [{ name: 'Database', running: true }, { name: 'Web', running: true }],
        issues: [],
      },
    })),
  },
}));

describe('ISE node detail', () => {
  it('shows the fuller reading for the node that was opened', async () => {
    render(<IseNodeView hostname="pnp-pan1" />);
    expect(await screen.findByRole('heading', { name: 'pnp-pan1' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Back to ISE' })).toHaveAttribute('href', '/ise');
    expect(screen.getByText('12 days 4 hours')).toBeInTheDocument();
    expect(screen.getByText('Cisco Identity Services Engine')).toBeInTheDocument();
    expect(screen.getByText('Core 1')).toBeInTheDocument();
    expect(screen.getByText('Core 2')).toBeInTheDocument();
    expect(screen.getByText('Physical memory')).toBeInTheDocument();
    expect(screen.getByText('/opt')).toBeInTheDocument();
    expect(screen.getByText('Database')).toBeInTheDocument();
    expect(screen.getByText('No deployment issues.')).toBeInTheDocument();
  });
});
