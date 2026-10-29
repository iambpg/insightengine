import React from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import SettingsView from './SettingsView';

const roleBox = vi.hoisted(() => ({ role: 'Administrator' as 'Administrator' | 'Engineer' }));

vi.mock('@/lib/useSession', () => ({
  useSession: () => ({ role: roleBox.role, ready: true, session: null }),
}));

describe('Settings Vault tab', () => {
  it('shows Vault to an administrator and hides it from an engineer', async () => {
    const user = userEvent.setup();
    roleBox.role = 'Administrator';
    const { unmount } = render(<SettingsView />);
    const vault = await screen.findByRole('tab', { name: 'Vault' });
    await user.click(vault);
    expect(screen.getByRole('heading', { name: 'Vault' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'NetBox' })).toBeInTheDocument();
    unmount();

    roleBox.role = 'Engineer';
    render(<SettingsView />);
    expect(screen.queryByRole('tab', { name: 'Vault' })).not.toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Applications' })).toBeInTheDocument();
  });
});
