'use client';

import { useEffect, useRef, useState } from 'react';
import { reportLoadError } from '@/lib/loadError';

interface Record<T> {
  key: string;
  data: T | null;
  error: string | null;
}

/**
 * Load `key` and ignore a response that belongs to an older key.
 * A slow 404 for device A must not paint "unknown device" after the page
 * has moved on to device B. Data for a different key is not shown.
 */
export function useKeyedLoad<T>(
  key: string,
  enabled: boolean,
  reload: number,
  subject: string,
  load: (key: string) => Promise<T>,
): { data: T | null; error: string | null } {
  const loadRef = useRef(load);
  loadRef.current = load;
  const token = useRef(0);
  const [record, setRecord] = useState<Record<T> | null>(null);

  useEffect(() => {
    if (!enabled || !key) return undefined;
    const current = ++token.current;
    const requested = key;
    setRecord({ key: requested, data: null, error: null });
    let active = true;
    Promise.resolve()
      .then(() => loadRef.current(requested))
      .then(
        (data) => {
          if (!active || token.current !== current) return;
          setRecord({ key: requested, data, error: null });
        },
        (cause) => {
          if (!active || token.current !== current) return;
          setRecord({ key: requested, data: null, error: reportLoadError(cause, subject) });
        },
      );
    return () => {
      active = false;
    };
  }, [key, enabled, reload, subject]);

  if (!enabled || !key) return { data: null, error: null };
  if (!record || record.key !== key) return { data: null, error: null };
  return { data: record.data, error: record.error };
}
