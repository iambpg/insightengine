import type { RoleName } from '@/lib/types';

export interface Session {
  email: string;
  role: RoleName;
  csrfToken: string;
}

const KEY = 'ie.session';
const EVENT = 'ie-session';

export function readSession(): Session | null {
  if (typeof window === 'undefined') return null;
  try {
    const raw = window.sessionStorage.getItem(KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Session;
    if (!parsed || typeof parsed.email !== 'string' || typeof parsed.csrfToken !== 'string')
      return null;
    if (!parsed.role) return null;
    return parsed;
  } catch {
    return null;
  }
}

export function writeSession(session: Session | null): void {
  if (typeof window === 'undefined') return;
  try {
    if (session) window.sessionStorage.setItem(KEY, JSON.stringify(session));
    else window.sessionStorage.removeItem(KEY);
  } catch {
    /* storage unavailable; writes will fail the CSRF check server-side */
  }
  window.dispatchEvent(new Event(EVENT));
}

export function subscribeSession(listener: () => void): () => void {
  if (typeof window === 'undefined') return () => undefined;
  window.addEventListener(EVENT, listener);
  window.addEventListener('storage', listener);
  return () => {
    window.removeEventListener(EVENT, listener);
    window.removeEventListener('storage', listener);
  };
}

export function displayName(email: string): string {
  if (email === 'm.vanderberg@noc.example') return 'Marit van der Berg';
  return email;
}

export function displayInitials(email: string): string {
  if (email === 'm.vanderberg@noc.example') return 'MB';
  const local = email.split('@')[0] ?? email;
  return local.slice(0, 2).toUpperCase();
}
