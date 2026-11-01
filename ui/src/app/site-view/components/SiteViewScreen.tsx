'use client';

import React, { useEffect, useState } from 'react';
import Icon from '@/components/ui/AppIcon';
import ExampleDataBanner from '@/components/ui/ExampleDataBanner';
import Pagination from '@/components/ui/Pagination';
import { api } from '@/lib/apiClient';
import { reportLoadError } from '@/lib/loadError';
import { isMockMode } from '@/lib/apiMode';
import { usePageQuery } from '@/lib/usePageQuery';
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
  const { ready, params } = usePageQuery('/site-view');
  const wantedSite = params.get('site') ?? '';
  const wantedQuery = params.get('q') ?? '';
  const [appliedQuery, setAppliedQuery] = useState<string | null>(null);

  useEffect(() => {
    if (!ready || appliedQuery === wantedQuery) return;
    setText(wantedQuery);
    setSearch(wantedQuery);
    setPage(1);
    setAppliedQuery(wantedQuery);
  }, [ready, wantedQuery, appliedQuery]);

  useEffect(() => {
    if (text === search) return;
    const id = setTimeout(() => {
      setSearch(text);
      setPage(1);
    }, 250);
    return () => clearTimeout(id);
  }, [text, search]);

  useEffect(() => {
    if (!ready) return undefined;
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
      })
      .catch((cause) => !cancelled && setError(reportLoadError(cause, 'sites')));
    return () => {
      cancelled = true;
    };
  }, [ready, page, pageSize, search, health, region, reload]);

  useEffect(() => {
    if (!ready || !rows) return;
    if (wantedSite) {
      const match = rows.find((row) => row.id === wantedSite);
      if (match) {
        setActive(match);
        return;
      }
    }
    setActive((current) => current ?? rows[0] ?? null);
  }, [ready, rows, wantedSite]);

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

        <SiteDetail site={active} loading={!ready || (rows === null && !error)} />
      </div>
    </div>
  );
}