import type { SetupState } from '@/lib/contract';
import { MOCK_SETUP_STATES } from '@/lib/contract';

const STORAGE_KEY = 'ie.mock.setupState';

export function mockSetupStates(): SetupState[] {
  return MOCK_SETUP_STATES.map((state) => ({ ...state }));
}

export function readMockSetupState(): SetupState {
  const override = (globalThis as { __IE_MOCK_SETUP__?: SetupState }).__IE_MOCK_SETUP__;
  if (override && isSetupState(override)) return { ...override };
  if (typeof window !== 'undefined') {
    try {
      const raw = window.sessionStorage.getItem(STORAGE_KEY);
      if (raw) {
        const parsed = JSON.parse(raw) as SetupState;
        if (isSetupState(parsed)) return parsed;
      }
    } catch {
      /* ignore broken demo overrides */
    }
  }
  return { state: 'complete' };
}

function isSetupState(value: SetupState): boolean {
  return (
    value.state === 'unconfigured' ||
    value.state === 'applying' ||
    value.state === 'complete' ||
    value.state === 'failed'
  );
}
