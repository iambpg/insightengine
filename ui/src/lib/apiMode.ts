export type ApiMode = 'live' | 'mock';

/**
 * Production builds default to live. `next dev` defaults to mock so the UI
 * can be opened without ie-config. Set NEXT_PUBLIC_IE_API_MODE to force either.
 * Demo account passwords are compiled only when this is true (see next.config).
 */
export function isMockMode(): boolean {
  if (process.env.NEXT_PUBLIC_IE_API_MODE === 'live') return false;
  if (process.env.NEXT_PUBLIC_IE_API_MODE === 'mock') return true;
  return process.env.NODE_ENV !== 'production';
}
