import React from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import VaultTab from './VaultTab';

const GROUPS = [
  'NetBox',
  'Grafana',
  'Prometheus / Alertmanager',
  'Activepieces',
  'Netdisco',
  'Oxidized',
  'SNMP',
  'UI / admin',
];

function groupButton(name: string) {
  return screen.getByRole('button', { name: new RegExp(name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')) });
}

describe('VaultTab', () => {
  it('keeps groups collapsed until expanded, then re-masks when collapsed', async () => {
    const user = userEvent.setup();
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      writable: true,
      value: { writeText },
    });
    render(<VaultTab />);

    expect(screen.getByRole('heading', { name: 'Vault' })).toBeInTheDocument();
    for (const name of GROUPS) {
      const button = groupButton(name);
      expect(button).toHaveAttribute('aria-expanded', 'false');
    }
    const netbox = groupButton('NetBox');
    expect(netbox).toHaveTextContent('https://monitor.example.com:8092/');
    expect(netbox).toHaveTextContent('3 keys');
    expect(groupButton('Prometheus / Alertmanager')).toHaveTextContent('https://monitor.example.com:8086/');
    expect(screen.queryByText('NETBOX_SUPERUSER_PASSWORD')).not.toBeInTheDocument();
    expect(screen.queryByText('GRAFANA_ADMIN_USER')).not.toBeInTheDocument();
    expect(screen.queryByText('(mock)')).not.toBeInTheDocument();

    await user.click(netbox);
    expect(netbox).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByText('NETBOX_SUPERUSER_NAME')).toBeInTheDocument();
    expect(screen.getByText('NETBOX_SUPERUSER_PASSWORD')).toBeInTheDocument();
    expect(screen.getAllByText('••••••••').length).toBeGreaterThan(0);

    await user.click(screen.getByRole('button', { name: 'Reveal NETBOX_SUPERUSER_PASSWORD' }));
    await user.type(screen.getByLabelText('Current administrator password'), 'confirm-please');
    await user.click(screen.getByRole('button', { name: 'Confirm password' }));
    expect(await screen.findByText('(mock)')).toBeInTheDocument();

    await user.click(netbox);
    expect(netbox).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByText('NETBOX_SUPERUSER_PASSWORD')).not.toBeInTheDocument();
    expect(screen.queryByText('(mock)')).not.toBeInTheDocument();

    await user.click(netbox);
    expect(screen.getByText('NETBOX_SUPERUSER_PASSWORD')).toBeInTheDocument();
    expect(screen.queryByText('(mock)')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Reveal NETBOX_SUPERUSER_PASSWORD' })).toBeInTheDocument();
    expect(screen.getAllByText('••••••••').length).toBeGreaterThan(0);

    const grafana = groupButton('Grafana');
    grafana.focus();
    await user.keyboard('{Enter}');
    expect(grafana).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByText('GRAFANA_ADMIN_USER')).toBeInTheDocument();
    await user.keyboard(' ');
    expect(grafana).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByText('GRAFANA_ADMIN_USER')).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Expand all' }));
    expect(screen.getByText('NETBOX_SUPERUSER_PASSWORD')).toBeInTheDocument();
    expect(screen.getByText('GRAFANA_ADMIN_USER')).toBeInTheDocument();
    expect(screen.getByText('ADMIN_BASIC_PASSWORD')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Copy GRAFANA_ADMIN_USER' }));
    expect(writeText).toHaveBeenCalledWith('admin');

    await user.click(screen.getByRole('button', { name: 'Reveal NETBOX_SUPERUSER_PASSWORD' }));
    expect(await screen.findByText('(mock)')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Collapse all' }));
    expect(screen.queryByText('NETBOX_SUPERUSER_PASSWORD')).not.toBeInTheDocument();
    expect(screen.queryByText('GRAFANA_ADMIN_USER')).not.toBeInTheDocument();
    expect(screen.queryByText('(mock)')).not.toBeInTheDocument();
    for (const name of GROUPS) {
      expect(groupButton(name)).toHaveAttribute('aria-expanded', 'false');
    }
  });
});
