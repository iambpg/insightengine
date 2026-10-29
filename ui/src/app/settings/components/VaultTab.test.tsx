import React from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import VaultTab from './VaultTab';

describe('VaultTab', () => {
  it('renders grouped credentials with secrets masked until the password is re-entered', async () => {
    const user = userEvent.setup();
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      writable: true,
      value: { writeText },
    });
    render(<VaultTab />);

    expect(screen.getByRole('heading', { name: 'Vault' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'NetBox' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Prometheus / Alertmanager' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Grafana' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Activepieces' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Netdisco' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Oxidized' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'SNMP' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'UI / admin' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'https://monitor.example.com:8092/' })).toHaveAttribute(
      'href',
      'https://monitor.example.com:8092/'
    );
    expect(screen.getByRole('link', { name: 'https://monitor.example.com:8086/' })).toBeInTheDocument();
    expect(screen.getByText('NETBOX_SUPERUSER_NAME')).toBeInTheDocument();
    expect(screen.getAllByText('admin').length).toBeGreaterThan(0);
    expect(screen.getByText('NETBOX_SUPERUSER_PASSWORD')).toBeInTheDocument();
    expect(screen.getAllByText('••••••••').length).toBeGreaterThan(0);
    expect(screen.queryByText('(mock)')).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Reveal NETBOX_SUPERUSER_PASSWORD' }));
    expect(screen.getByLabelText('Current administrator password')).toBeInTheDocument();
    await user.type(screen.getByLabelText('Current administrator password'), 'confirm-please');
    await user.click(screen.getByRole('button', { name: 'Confirm password' }));
    expect(await screen.findByText('(mock)')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Copy GRAFANA_ADMIN_USER' }));
    expect(writeText).toHaveBeenCalledWith('admin');
  });
});
