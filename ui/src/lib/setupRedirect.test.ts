import { describe, expect, it } from 'vitest';
import { MOCK_SETUP_STATES } from '@/lib/contract';
import { readMockSetupState } from '@/lib/mock/setupState';
import { redirectForSetup } from '@/lib/setupRedirect';

describe('redirectForSetup', () => {
  it('includes every setup state in the mock and only redirects away from complete', () => {
    const names = MOCK_SETUP_STATES.map((state) => state.state).sort();
    expect(names).toEqual(['applying', 'complete', 'failed', 'unconfigured']);
    for (const state of MOCK_SETUP_STATES) {
      const target = redirectForSetup(state, '/settings');
      if (state.state === 'complete') expect(target).toBeNull();
      else expect(target).toBe('/setup/');
    }
  });

  it('does not redirect when already on the setup path', () => {
    expect(redirectForSetup({ state: 'failed', step: 'database' }, '/setup/')).toBeNull();
    expect(redirectForSetup({ state: 'unconfigured', step: 'admin' }, '/setup/admin')).toBeNull();
  });

  it('does not treat a missing payload as incomplete', () => {
    expect(redirectForSetup(null, '/')).toBeNull();
    expect(redirectForSetup(undefined, '/')).toBeNull();
  });

  it('reads a mock override for the non-complete states', () => {
    const globalState = globalThis as { __IE_MOCK_SETUP__?: { state: 'failed'; step: string } };
    globalState.__IE_MOCK_SETUP__ = { state: 'failed', step: 'database' };
    expect(readMockSetupState()).toEqual({ state: 'failed', step: 'database' });
    delete globalState.__IE_MOCK_SETUP__;
    expect(readMockSetupState()).toEqual({ state: 'complete' });
  });
});
