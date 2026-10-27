'use client';

import React, { useEffect, useState } from 'react';
import Icon from '@/components/ui/AppIcon';
import ExampleDataBanner from '@/components/ui/ExampleDataBanner';
import Pagination from '@/components/ui/Pagination';
import { api } from '@/lib/apiClient';
import { isMockMode } from '@/lib/apiMode';
import type { DeviceHealth, SiteRow } from '@/lib/types';
import SiteList from './SiteList';
import SiteDetail from './SiteDetail';

export default function SiteViewScreen() {
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [search, setSearch] = useState('');
  const [health, setHealth] = useState<DeviceHealth | 'all'>('all');
  const [region, setRegion] = useState('all');
  const [rows, setRows] = useState<SiteRow[] | null>(null);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [active, setActive] = useState<SiteRow | null>(null);
  const [reload, setReload] = useState(0);
  const [text, setText] = useState('');
  const [regions, setRegions] = useState<string[] | undefined>();

  useEffect(() => {
    const q = new URLSearchParams(window.location.search).get('q');
    if (q) {
      setText(q);
      setSearch(q);
    }
  }, []);

  useEffect(() => {
    if (text === search) return;
    const id = setTimeout(() => {
      setSearch(text);
      setPage(1);
    }, 250);
    return () => clearTimeout(id);
  }, [text, search]);

  useEffect(() => {
    let cancelled = false;
    setRows(null);
    setError(null);
    api
      .listSites({ page, pageSize, search, health, region })
      .then((res) => {
        if (cancelled) return;
        setRows(res.rows);
        setTotal(res.total);
        if (res.regions) setRegions(res.regions);
        const wanted = new URLSearchParams(window.location.search).get('site');
        setActive((current) => {
          if (wanted) {
            const match = res.rows.find((row) => row.id === wanted);
            if (match) return match;
          }
          return current ?? res.rows[0] ?? null;
        });
      })
      .catch(() => !cancelled && setError('Failed to load sites. Check your connection and try again.'));
    return () => {
      cancelled = true;
    };
  }, [page, pageSize, search, health, region, reload]);

  return (
    <div className="space-y-5">
      <header className="px-4">
        <h1 className="text-2xl font-semibold tracking-tight">Sites</h1>
        <p className="mt-1 text-sm text-muted-foreground">About 2,000 sites, about 10 switches each. Search, filter, then inspect a site's devices.</p>
      </header>
      {isMockMode() ? <ExampleDataBanner /> : null}

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[400px_1fr] 2xl:grid-cols-[440px_1fr]">
        <section className="flex flex-col rounded-none border-x-0 border-y border-border bg-card shadow-card" aria-label="Site list">
          <div className="space-y-2 border-b border-border p-3">
            <label className="relative block">
              <span className="sr-only">Search sites</span>
              <Icon name="MagnifyingGlassIcon" size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
              <input
                type="search"
                value={text}
                onChange={(e) => setText(e.target.value)}
                placeholder="Site name or city…"
                className="h-9 w-full rounded-md border border-input bg-background pl-9 pr-3 text-sm outline-none focus:border-ring"
              />
            </label>
            <div className="flex gap-2">
              <label className="flex-1">
                <span className="sr-only">Region</span>
                <select value={region} onChange={(e) => { setRegion(e.target.value); setPage(1); }} className="h-9 w-full rounded-md border border-input bg-card px-2 text-sm">
                  <option value="all">All regions</option>
                  {(regions && regions.length > 0 ? regions : ['Benelux-West', 'Benelux-North', 'Benelux-South', 'Rhine-East']).map((name) => (
                    <option key={name} value={name}>{name}</option>
                  ))}
                  {region !== 'all' && regions && !regions.includes(region) ? <option value={region}>{region}</option> : null}
                </select>
              </label>
              <label className="flex-1">
                <span className="sr-only">Health</span>
                <select value={health} onChange={(e) => { setHealth(e.target.value as DeviceHealth | 'all'); setPage(1); }} className="h-9 w-full rounded-md border border-input bg-card px-2 text-sm">
                  <option value="all">All health states</option>
                  <option value="healthy">Healthy</option>
                  <option value="warning">Warning</option>
                  <option value="critical">Critical</option>
                  <option value="unreachable">Unreachable</option>
                </select>
              </label>
            </div>
          </div>
          <SiteList
            rows={rows}
            error={error}
            onRetry={() => setReload((n) => n + 1)}
            activeId={active?.id ?? null}
            onPick={setActive}
            onClear={() => { setText(''); setSearch(''); setHealth('all'); setRegion('all'); }}
          />
          <Pagination page={page} pageSize={pageSize} total={total} noun="sites" sizes={[10, 25, 50]} onPage={setPage} onPageSize={(n) => { setPageSize(n); setPage(1); }} />
        </section>

        <SiteDetail site={active} />
      </div>
    </div>
  );
}