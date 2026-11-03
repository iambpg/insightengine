import React from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import NetBridgeView from './NetBridgeView';

vi.mock('@/lib/apiClient', () => ({
  api: {
    netbridgeGet: vi.fn(async (path: string) => {
      if (path.startsWith('/open-count')) return { open: 3 };
      if (path.startsWith('/summary')) {
        return {
          netdiscoDevices: 4,
          netboxDevices: 2,
          notInNetbox: 1,
          stacksPending: 1,
          apsPending: 0,
          openConflicts: 3,
          eox: { configured: false, message: 'Cisco Support API credentials are not configured. Add the client id and secret in Settings → Vault.' },
          fortimanager: { configured: false, message: '' },
          jobs: [],
        };
      }
      if (path.startsWith('/eox')) {
        return { configured: false, message: 'Cisco Support API credentials are not configured. Add the client id and secret in Settings → Vault.', rows: [], total: 0, counts: { past: 0, soon: 0, ok: 0, unknown: 0 } };
      }
      return { rows: [], total: 0, message: '' };
    }),
    netbridgePost: vi.fn(),
    listDiscovered: vi.fn(async () => []),
    listScans: vi.fn(async () => []),
    discoveryCatalog: vi.fn(async () => ({ roles: ['Access switch'], roleChoices: [{ name: 'Access switch', slug: 'access-switch' }], sites: [], platforms: [] })),
  },
}));

describe('NetBridge', () => {
  it('opens on the dashboard and shows the end-of-life credential message', async () => {
    const user = userEvent.setup();
    render(<NetBridgeView />);
    expect(screen.getByRole('heading', { name: 'NetBridge' })).toBeInTheDocument();
    expect(await screen.findByText(/Cisco Support API credentials are not configured/)).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: /Conflicts & Queue/ })).toHaveTextContent('3');
    await user.click(screen.getByRole('tab', { name: 'End of Life' }));
    expect(screen.getByRole('button', { name: /Past LDoS/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /<12 months/ })).toBeInTheDocument();
    await user.click(screen.getByRole('tab', { name: 'Not in NetBox' }));
    expect(await screen.findByRole('heading', { name: 'Not in NetBox' })).toBeInTheDocument();
  });
});
