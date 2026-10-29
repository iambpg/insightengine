'use client';

import React, { useEffect, useState } from 'react';
import Icon from '@/components/ui/AppIcon';
import { api } from '@/lib/apiClient';
import { reportLoadError } from '@/lib/loadError';
import type { LauncherApp, LauncherCatalog } from '@/lib/types';

const DOT: Record<LauncherApp['status'], string> = {
  up: 'bg-success',
  down: 'bg-destructive',
  unknown: 'bg-muted-foreground',
};

export default function AppsLauncher({ layout = 'menu' }: { layout?: 'menu' | 'page' }) {
  const [catalog, setCatalog] = useState<LauncherCatalog | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .listLauncherApps()
      .then((data) => {
        if (!cancelled) setCatalog(data);
      })
      .catch((cause) => {
        if (!cancelled) setError(reportLoadError(cause, 'the app list'));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (error) {
    return (
      <p role="alert" className="px-3 py-2 text-sm text-destructive">
        {error}
      </p>
    );
  }
  if (!catalog) {
    return <p className="px-3 py-2 text-sm text-muted-foreground">Loading apps…</p>;
  }

  const list = (
    <ul className={layout === 'page' ? 'grid grid-cols-1 gap-3 sm:grid-cols-2' : 'space-y-0.5'}>
      {catalog.apps.map((app) => (
        <li key={app.id}>
          {app.url ? (
            <a
              href={app.url}
              target="_blank"
              rel="noopener noreferrer"
              className={
                layout === 'page'
                  ? 'flex items-center gap-3 rounded-md border border-border bg-card px-4 py-3 text-sm hover:bg-muted'
                  : 'flex items-center gap-2 rounded-md px-3 py-2 text-sm hover:bg-muted'
              }
            >
              <span className={`h-2 w-2 shrink-0 rounded-full ${DOT[app.status] || DOT.unknown}`} title={app.status} />
              <span className="min-w-0 flex-1">
                <span className="block font-medium">{app.name}</span>
                {layout === 'page' ? (
                  <span className="block truncate font-mono-data text-[11px] text-muted-foreground">{app.url}</span>
                ) : null}
              </span>
              <Icon name="ArrowTopRightOnSquareIcon" size={14} className="text-muted-foreground" />
            </a>
          ) : (
            <span className="flex items-center gap-2 px-3 py-2 text-sm text-muted-foreground">
              <span className="h-2 w-2 rounded-full bg-muted-foreground" />
              {app.name} has no public URL
            </span>
          )}
        </li>
      ))}
    </ul>
  );

  if (layout === 'menu') return list;

  return (
    <section className="space-y-3 rounded-md border border-border bg-card p-5">
      <header>
        <h2 className="text-base font-semibold">Apps</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Opens each web UI on {catalog.host || 'this host'} in a new tab. The dot is that service&apos;s health.
          {catalog.role ? ` You are signed in as ${catalog.role}.` : ''} Each app still asks for its own login.
        </p>
      </header>
      {list}
    </section>
  );
}
