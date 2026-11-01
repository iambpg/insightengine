'use client';

import { useEffect, useState } from 'react';
import { useSearchParams } from 'next/navigation';

/**
 * An empty query is left unresolved for this long so a client navigation can
 * apply `?id=` before the page treats "no id" as final.
 * Reading the query during the first paint is not enough: a static page can
 * render once with an empty search string, and `window.location` can still be
 * the previous page during that render.
 */
const EMPTY_QUERY_SETTLE_MS = 50;

function locationQueryFor(pathname: string): string {
  if (typeof window === 'undefined') return '';
  const path = window.location.pathname.replace(/\/$/, '') || '/';
  const want = pathname.replace(/\/$/, '') || '/';
  if (path !== want) return '';
  const raw = window.location.search;
  if (!raw || raw === '?') return '';
  return raw.startsWith('?') ? raw.slice(1) : raw;
}

/**
 * Search params for one route.
 *
 * `ready` is false while the query may still be the empty static snapshot.
 * Callers show a loading state until it is true, then read `id` / `form`.
 * A non-empty router query is used on the same render. The address bar is
 * only a fallback once this route's pathname is current and the router
 * snapshot is still empty.
 */
export function usePageQuery(pathname: string): { ready: boolean; params: URLSearchParams } {
  const searchParams = useSearchParams();
  const routerQuery = searchParams?.toString() ?? '';
  const [trackedQuery, setTrackedQuery] = useState(routerQuery);
  const [fallback, setFallback] = useState('');
  const [emptyReady, setEmptyReady] = useState(false);

  if (routerQuery !== trackedQuery) {
    setTrackedQuery(routerQuery);
    setFallback('');
    setEmptyReady(false);
  }

  useEffect(() => {
    if (routerQuery) {
      setFallback('');
      setEmptyReady(false);
      return undefined;
    }
    const fromLocation = locationQueryFor(pathname);
    if (fromLocation) {
      setFallback(fromLocation);
      setEmptyReady(true);
      return undefined;
    }
    setFallback('');
    const timer = window.setTimeout(() => setEmptyReady(true), EMPTY_QUERY_SETTLE_MS);
    return () => window.clearTimeout(timer);
  }, [pathname, routerQuery]);

  if (routerQuery) return { ready: true, params: new URLSearchParams(routerQuery) };
  if (fallback) return { ready: true, params: new URLSearchParams(fallback) };
  return { ready: emptyReady, params: new URLSearchParams('') };
}
