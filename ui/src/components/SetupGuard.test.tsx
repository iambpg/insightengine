import React from 'react';
import { render, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import SetupGuard from '@/components/SetupGuard';
import { api } from '@/lib/apiClient';

vi.mock('@/lib/apiClient', () => ({
  api: { getSetupState: vi.fn() },
}));

const getSetupState = api.getSetupState as unknown as ReturnType<typeof vi.fn>;

describe('SetupGuard', () => {
  const assign = vi.fn();

  beforeEach(() => {
    assign.mockReset();
    getSetupState.mockReset();
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: { pathname: '/', assign, href: 'http://localhost/' },
    });
  });

  it('stays put when setup is complete', async () => {
    getSetupState.mockResolvedValue({ state: 'complete' });
    render(<SetupGuard />);
    await waitFor(() => expect(getSetupState).toHaveBeenCalled());
    expect(assign).not.toHaveBeenCalled();
  });

  it.each(['unconfigured', 'applying', 'failed'] as const)(
    'redirects when state is %s',
    async (state) => {
      getSetupState.mockResolvedValue({ state, step: 'admin' });
      render(<SetupGuard />);
      await waitFor(() => expect(assign).toHaveBeenCalledWith('/setup/'));
    }
  );

  it('does not redirect when the setup request fails', async () => {
    getSetupState.mockRejectedValue(new Error('network down'));
    render(<SetupGuard />);
    await waitFor(() => expect(getSetupState).toHaveBeenCalled());
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(assign).not.toHaveBeenCalled();
  });

  it('does not redirect again when the page is already /setup/', async () => {
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: { pathname: '/setup/', assign, href: 'http://localhost/setup/' },
    });
    getSetupState.mockResolvedValue({ state: 'unconfigured' });
    render(<SetupGuard />);
    await waitFor(() => expect(getSetupState).toHaveBeenCalled());
    expect(assign).not.toHaveBeenCalled();
  });
});
