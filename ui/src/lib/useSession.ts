'use client';

import { useEffect, useState } from 'react';
import { api } from '@/lib/apiClient';
import { isApiError } from '@/lib/apiError';
import { readSession, subscribeSession, writeSession, type Session } from '@/lib/session';
import type { RoleName } from '@/lib/types';

/** Role from the browser session only. Does not call the API. */
export function useKnownRole(): RoleName | null {
  const [role, setRole] = useState<RoleName | null>(null);
  useEffect(() => {
    const apply = () => setRole(readSession()?.role ?? null);
    apply();
    return subscribeSession(apply);
  }, []);
  return role;
}

export function useSession(): { session: Session | null; role: RoleName | null; ready: boolean } {
  const [session, setSession] = useState<Session | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    setSession(readSession());
    let cancelled = false;
    api
      .me()
      .then((next) => {
        if (!cancelled) setSession(next);
      })
      .catch((error) => {
        if (isApiError(error) && error.status === 401) {
          writeSession(null);
          if (!cancelled) setSession(null);
        }
      })
      .finally(() => {
        if (!cancelled) setReady(true);
      });
    const unsubscribe = subscribeSession(() => setSession(readSession()));
    return () => {
      cancelled = true;
      unsubscribe();
    };
  }, []);

  return { session, role: session?.role ?? null, ready };
}
