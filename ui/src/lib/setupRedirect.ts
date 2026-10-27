import type { SetupState } from '@/lib/contract';

const REDIRECT_STATES = new Set(['unconfigured', 'applying', 'failed']);

/**
 * Where the browser should go given a setup payload.
 * Network failures are not a state: callers must not redirect when the request throws,
 * otherwise a dead setup service bounces the UI forever.
 */
export function redirectForSetup(
  state: Pick<SetupState, 'state'> | null | undefined,
  pathname: string
): '/setup/' | null {
  if (!state || !REDIRECT_STATES.has(state.state)) return null;
  if (pathname.startsWith('/setup')) return null;
  return '/setup/';
}
