import React from 'react';
import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { writeSession } from '@/lib/session';
import RolesTab from './RolesTab';

describe('Roles and users', () => {
  it('keeps the built-in admin from being deleted or disabled', async () => {
    writeSession({
      email: 'm.vanderberg@noc.example',
      role: 'Administrator',
      csrfToken: 'test',
      id: 1,
      username: 'admin',
    });
    render(<RolesTab />);
    expect(await screen.findByRole('heading', { name: 'Permission matrix' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Users' })).toBeInTheDocument();
    const admin = await screen.findByText('admin');
    const row = admin.closest('tr');
    expect(row).not.toBeNull();
    expect(within(row as HTMLElement).getByRole('button', { name: 'Delete' })).toBeDisabled();
    expect(within(row as HTMLElement).getByRole('button', { name: 'Disable' })).toBeDisabled();
    expect(within(row as HTMLElement).getByRole('button', { name: 'Edit' })).toBeEnabled();
  });

  it('hides user changes from an engineer', async () => {
    writeSession({
      email: 's.kuipers@noc.example',
      role: 'Engineer',
      csrfToken: 'test',
    });
    render(<RolesTab />);
    expect(await screen.findByText(/Only an Administrator can change users/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Add user' })).not.toBeInTheDocument();
  });
});
