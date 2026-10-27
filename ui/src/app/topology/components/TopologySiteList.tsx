'use client';

import React, { useEffect, useState } from 'react';
import Icon from '@/components/ui/AppIcon';
import EmptyState from '@/components/ui/EmptyState';
import ExampleDataBanner from '@/components/ui/ExampleDataBanner';
import Pagination from '@/components/ui/Pagination';
import { HealthBadge } from '@/components/ui/Badge';
import { Skeleton } from '@/components/ui/Skeleton';
import { api } from '@/lib/apiClient';
import { isMockMode } from '@/lib/apiMode';
import type { SiteRow } from '@/lib/types';

interface Props {
  onPick: (s: SiteRow) => void;
}

export default function TopologySiteList({ onPick }: Props) {
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [search, setSearch] = useState('');
  const [text, setText] = useState('');
  const [rows, setRows] = useState<SiteRow[] | null>(null);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    const t = setTimeout(() => {
      setSearch(text);
      setPage(1);
    }, 250);
    return () => clearTimeout(t);
  }, [text]);

  useEffect(() => {
    let cancelled = false;
    setRows(null);
    setError(null);
    api
      .listSites({ page, pageSize, search, health: 'all', region: 'all' })
      .then((r) => {
        if (cancelled) return;
        setRows(r.rows);
        setTotal(r.total);
      })
      .catch(() => !cancelled && setError('Failed to load sites. Check your connection and try again.'));
    return () => {
      cancelled = true;
    };
  }, [page, pageSize, search, reload]);

  return (
    <div className="space-y-3">
      <header className="border-y border-border bg-card p-4 shadow-card">
        <h1 className="text-xl font-semibold tracking-tight">Topology</h1>
        <p className="mt-0.5 text-sm text-muted-foreground">Sites with a topology available. Select a site to view its topology.</p>
      </header>

      <section className="border-y border-border bg-card shadow-card" aria-label="Sites with topology">
        <div className="border-b border-border p-3">
          <label className="relative block max-w-md">
            <span className="sr-only">Search sites</span>
            <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground">
              <Icon name="MagnifyingGlassIcon" size={16} />
            </span>
            <input
              type="search"
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="Search sites by name or city"
              className="w-full rounded-md border border-input bg-background py-2 pl-9 pr-3 text-sm outline-none focus:ring-2 focus:ring-ring"
            />
          </label>
        </div>

        {error ? (
          <div role="alert" className="m-3 flex items-center justify-between gap-3 rounded-md border border-destructive/30 bg-destructive/10 px-3 py-3 text-sm text-destructive">
            <span>{error}</span>
            <button type="button" onClick={() => setReload((n) => n + 1)} className="rounded-md border border-destructive/40 px-2 py-1 text-xs font-semibold">Retry</button>
          </div>
        ) : rows === null ? (
          <div className="p-3">
            {Array.from({ length: 6 }, (_, i) => (
              <Skeleton key={`ts-skel-${i + 1}`} className="mb-2 h-14 w-full" />
            ))}
          </div>
        ) : rows.length === 0 ? (
          <EmptyState icon="BuildingOffice2Icon" title="No sites match" description="No site matches your search." actionLabel="Clear search" onAction={() => setText('')} />
        ) : (
          <ul className="divide-y divide-border fade-in">
            {rows.map((s) => (
              <li key={s.id}>
                <button
                  type="button"
                  onClick={() => onPick(s)}
                  className="flex w-full items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-accent/10"
                >
                  <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground">
                    <Icon name="ShareIcon" size={18} />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-semibold">{s.name}</span>
                    <span className="mt-0.5 flex flex-wrap items-center gap-x-3 text-xs text-muted-foreground">
                      <span>{s.region}</span>
                      <span className="font-mono-data tabular">{s.deviceCount} devices</span>
                      {s.alerts > 0 && <span className="font-semibold text-destructive">▲ {s.alerts} alerts</span>}
                    </span>
                  </span>
                  <HealthBadge health={s.health} />
                  <Icon name="ChevronRightIcon" size={16} />
                </button>
              </li>
            ))}
          </ul>
        )}

        <Pagination page={page} pageSize={pageSize} total={total} onPage={setPage} onPageSize={(n) => { setPageSize(n); setPage(1); }} sizes={[10, 25, 50]} noun="sites" />
      </section>

      {isMockMode() ? <ExampleDataBanner text="Topology links are simulated example data. No live discovery is run." /> : null}
    </div>
  );
}
