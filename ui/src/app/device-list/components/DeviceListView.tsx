'use client';

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import Icon from '@/components/ui/AppIcon';
import ExampleDataBanner from '@/components/ui/ExampleDataBanner';
import Pagination from '@/components/ui/Pagination';
import Link from 'next/link';
import { api, type DeviceQuery } from '@/lib/apiClient';
import { isMockMode } from '@/lib/apiMode';
import { allowOperate } from '@/lib/settings/access';
import { useKnownRole } from '@/lib/useSession';
import { describeLoadError, redirectIfSignedOut } from '@/lib/loadError';
import { HealthBadge } from '@/components/ui/Badge';
import type { DeviceHealth, DeviceRow, SiteRow } from '@/lib/types';
import HealthStrip from './HealthStrip';
import DeviceFilters from './DeviceFilters';
import DeviceTable from './DeviceTable';
import ColumnMenu, { COLUMNS, type ColumnKey } from './ColumnMenu';

export default function DeviceListView() {
  const canWrite = allowOperate(useKnownRole());
  const [query, setQuery] = useState<DeviceQuery>({
    page: 1,
    pageSize: 25,
    search: '',
    health: 'all',
    role: 'all',
    sortKey: 'hostname',
    sortDir: 'asc',
  });
  const [sites, setSites] = useState<SiteRow[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [total, setTotal] = useState(0);
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const [foundSites, setFoundSites] = useState<SiteRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [signedOut, setSignedOut] = useState(false);
  const [selected, setSelected] = useState<string[]>([]);
  const [visible, setVisible] = useState<ColumnKey[]>(COLUMNS.map((c) => c.key));
  const [reload, setReload] = useState(0);
  const [roles, setRoles] = useState<string[] | undefined>();
  const stamp = () => {
    const d = new Date();
    const p = (n: number) => String(n).padStart(2, '0');
    return `${p(d.getUTCHours())}:${p(d.getUTCMinutes())}:${p(d.getUTCSeconds())}`;
  };
  const [updated, setUpdated] = useState(stamp);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setSignedOut(false);
    api
      .listSites({ page: query.page, pageSize: query.pageSize, search: query.search, health: query.health, region: 'all' })
      .then((res) => {
        if (cancelled) return;
        setSites(res.rows);
        setTotal(res.total);
      })
      .catch((cause) => {
        if (cancelled) return;
        const failure = describeLoadError(cause, 'sites');
        redirectIfSignedOut(failure);
        setSignedOut(failure.signedOut);
        setError(failure.text);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [query, reload]);

  useEffect(() => {
    let cancelled = false;
    api
      .listDevices({ page: 1, pageSize: 1, search: '', health: 'all', role: 'all', sortKey: 'hostname', sortDir: 'asc' })
      .then((res) => {
        if (!cancelled && res.roles) setRoles(res.roles);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [reload]);

  useEffect(() => {
    if (!query.search && query.role === 'all') {
      setFoundSites([]);
      return undefined;
    }
    let cancelled = false;
    api
      .listDevices({ ...query, page: 1, pageSize: 200 })
      .then((res) => {
        if (cancelled) return;
        const grouped = new Map<string, SiteRow>();
        for (const row of res.rows) {
          if (!row.siteId || grouped.has(row.siteId)) continue;
          const members = res.rows.filter((item) => item.siteId === row.siteId);
          grouped.set(row.siteId, {
            id: row.siteId,
            name: row.site || 'Site',
            region: '',
            city: '',
            deviceCount: members.length,
            health: members.some((item) => item.health === 'critical') ? 'critical' : members.some((item) => item.health === 'warning') ? 'warning' : row.health,
            alerts: 0,
            lastDiscovery: '',
          });
        }
        setFoundSites([...grouped.values()]);
      })
      .catch(() => {
        if (!cancelled) setFoundSites([]);
      });
    return () => {
      cancelled = true;
    };
  }, [query, reload]);

  const shownSites = useMemo(() => {
    if (!sites) return null;
    if (!query.search && query.role === 'all') return sites;
    const byId = new Map(sites.map((site) => [site.id, site]));
    for (const site of foundSites) {
      if (!byId.has(site.id)) byId.set(site.id, site);
    }
    return [...byId.values()].sort((left, right) => left.name.localeCompare(right.name));
  }, [sites, foundSites, query.search, query.role]);

  const patch = useCallback((p: Partial<DeviceQuery>) => {
    setSelected([]);
    setQuery((q) => ({ ...q, ...p, page: p.page ?? 1 }));
  }, []);

  const healthFilter = (h: DeviceHealth | 'all') => patch({ health: h });

  const activeFilters = useMemo(() => {
    const out: { id: string; label: string; clear: () => void }[] = [];
    if (query.search) out.push({ id: 'f-search', label: `“${query.search}”`, clear: () => patch({ search: '' }) });
    if (query.health !== 'all') out.push({ id: 'f-health', label: `Health: ${query.health}`, clear: () => patch({ health: 'all' }) });
    if (query.role !== 'all') out.push({ id: 'f-role', label: `Role: ${query.role}`, clear: () => patch({ role: 'all' }) });
    return out;
  }, [query.search, query.health, query.role, patch]);

  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-end justify-between gap-3 px-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Devices</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Sites from NetBox. A new site shows here as soon as it exists. Expand it to see the devices added to that site.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <Icon name="ClockIcon" size={14} />
            Updated <span className="font-mono-data text-foreground" suppressHydrationWarning>{updated} UTC</span>
          </span>
          <button
            type="button"
            onClick={() => {
              setReload((n) => n + 1);
              setUpdated(stamp());
            }}
            className="inline-flex items-center gap-1.5 rounded-md border border-border bg-card px-3 py-1.5 text-sm font-medium transition-all hover:bg-muted active:scale-95"
          >
            <Icon name="ArrowPathIcon" size={14} />
            Refresh
          </button>
        </div>
      </header>

      {isMockMode() ? <ExampleDataBanner /> : null}

      <HealthStrip activeHealth={query.health} onPick={healthFilter} />

      <section className={`rounded-none border-x-0 border-y border-border bg-card shadow-card ${loading && sites ? 'opacity-70' : ''}`} aria-label="Sites" aria-busy={loading}>
        <div className="flex flex-col gap-3 border-b border-border p-4">
          <div className="flex flex-wrap items-center gap-2">
            <DeviceFilters query={query} onChange={patch} roles={roles} />
            <div className="ml-auto flex items-center gap-2">
              <ColumnMenu visible={visible} onChange={setVisible} />
            </div>
          </div>
          {activeFilters.length > 0 && (
            <div className="flex flex-wrap items-center gap-2" aria-label="Active filters">
              {activeFilters.map((f) => (
                <span key={f.id} className="inline-flex items-center gap-1 rounded-full border border-accent/40 bg-accent/10 px-2.5 py-0.5 text-xs font-medium">
                  {f.label}
                  <button type="button" onClick={f.clear} aria-label={`Remove filter ${f.label}`} className="rounded-full p-0.5 hover:bg-accent/30">
                    <Icon name="XMarkIcon" size={12} />
                  </button>
                </span>
              ))}
              <button
                type="button"
                onClick={() => patch({ search: '', health: 'all', role: 'all' })}
                className="text-xs font-medium text-primary hover:underline"
              >
                Clear all
              </button>
            </div>
          )}
        </div>

        {selected.length > 0 && (
          <div className="slide-up flex items-center gap-3 border-b border-border bg-navy px-4 py-2 text-sm text-primary-foreground">
            <span className="font-medium tabular">{selected.length} selected</span>
            {canWrite ? <button type="button" className="rounded-md bg-navy-3 px-2.5 py-1 text-xs font-medium transition-all hover:bg-navy-2 active:scale-95">Acknowledge alerts</button> : null}
            <button type="button" className="rounded-md bg-navy-3 px-2.5 py-1 text-xs font-medium transition-all hover:bg-navy-2 active:scale-95">Export CSV</button>
            <button type="button" onClick={() => setSelected([])} className="ml-auto text-xs text-down hover:text-primary-foreground">Clear selection</button>
          </div>
        )}

        {signedOut ? (
          <div role="alert" className="m-4 rounded-md border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm">
            You are signed out - <Link href="/login-screen" className="font-semibold underline">sign in</Link>
          </div>
        ) : (
        <SiteList
          sites={shownSites}
          error={error}
          open={open}
          onToggle={(id) => setOpen((current) => ({ ...current, [id]: !current[id] }))}
          query={query}
          visible={visible}
          selected={selected}
          onSelect={setSelected}
          onSort={(k) => patch({ sortKey: k, sortDir: query.sortKey === k && query.sortDir === 'asc' ? 'desc' : 'asc', page: 1 })}
          onRetry={() => setReload((n) => n + 1)}
          onClear={() => patch({ search: '', health: 'all', role: 'all' })}
        />
        )}

        <Pagination
          page={query.page}
          pageSize={query.pageSize}
          total={total}
          noun="sites"
          onPage={(p) => setQuery((q) => ({ ...q, page: p }))}
          onPageSize={(n) => setQuery((q) => ({ ...q, pageSize: n, page: 1 }))}
        />
      </section>
    </div>
  );
}

function matchesDevice(row: DeviceRow, query: DeviceQuery, siteMatched: boolean): boolean {
  if (query.health !== 'all' && row.health !== query.health) return false;
  if (query.role !== 'all' && row.role.toLowerCase() !== query.role.toLowerCase()) return false;
  const needle = query.search.trim().toLowerCase();
  if (!needle || siteMatched) return true;
  return row.hostname.toLowerCase().includes(needle) || row.mgmtIp.toLowerCase().includes(needle) || row.site.toLowerCase().includes(needle);
}

function SiteList({
  sites,
  error,
  open,
  onToggle,
  query,
  visible,
  selected,
  onSelect,
  onSort,
  onRetry,
  onClear,
}: {
  sites: SiteRow[] | null;
  error: string | null;
  open: Record<string, boolean>;
  onToggle: (id: string) => void;
  query: DeviceQuery;
  visible: ColumnKey[];
  selected: string[];
  onSelect: (ids: string[]) => void;
  onSort: (key: keyof DeviceRow) => void;
  onRetry: () => void;
  onClear: () => void;
}) {
  if (error) {
    return (
      <div role="alert" className="m-4 flex items-center justify-between gap-3 rounded-md border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
        <span>{error}</span>
        <button type="button" onClick={onRetry} className="rounded-md border border-destructive/40 px-3 py-1 text-xs font-semibold">Retry</button>
      </div>
    );
  }
  if (sites === null) return <p className="px-4 py-6 text-sm text-muted-foreground">Loading sites…</p>;
  if (sites.length === 0) {
    return <p className="px-4 py-6 text-sm text-muted-foreground">No NetBox sites match these filters.</p>;
  }
  return (
    <div>
      {sites.map((site) => (
        <SitePanel
          key={site.id}
          site={site}
          expanded={!!open[site.id]}
          onToggle={() => onToggle(site.id)}
          query={query}
          visible={visible}
          selected={selected}
          onSelect={onSelect}
          onSort={onSort}
          onClear={onClear}
        />
      ))}
    </div>
  );
}

function SitePanel({
  site,
  expanded,
  onToggle,
  query,
  visible,
  selected,
  onSelect,
  onSort,
  onClear,
}: {
  site: SiteRow;
  expanded: boolean;
  onToggle: () => void;
  query: DeviceQuery;
  visible: ColumnKey[];
  selected: string[];
  onSelect: (ids: string[]) => void;
  onSort: (key: keyof DeviceRow) => void;
  onClear: () => void;
}) {
  const [rows, setRows] = useState<DeviceRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    if (!expanded) return undefined;
    let cancelled = false;
    setError(null);
    api
      .listSiteDevices(site.id)
      .then((devices) => {
        if (!cancelled) setRows(devices);
      })
      .catch((cause) => {
        if (cancelled) return;
        setRows([]);
        setError(describeLoadError(cause, 'devices').text);
      });
    return () => {
      cancelled = true;
    };
  }, [expanded, site.id, retry]);
  const place = [site.region, site.city].filter(Boolean).join(' · ');
  const needle = query.search.trim().toLowerCase();
  const siteMatched = !needle || site.name.toLowerCase().includes(needle) || site.city.toLowerCase().includes(needle) || site.region.toLowerCase().includes(needle);
  const shown = (rows || []).filter((row) => matchesDevice(row, query, siteMatched));
  return (
    <article className="border-b border-border">
      <button
        type="button"
        aria-expanded={expanded}
        aria-label={`${expanded ? 'Collapse' : 'Expand'} ${site.name}`}
        onClick={onToggle}
        className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-muted/50"
      >
        <Icon name={expanded ? 'ChevronDownIcon' : 'ChevronRightIcon'} size={18} className="shrink-0" />
        <span className="min-w-0">
          <span className="block text-base font-semibold">{site.name}</span>
          {place ? <span className="block text-xs text-muted-foreground">{place}</span> : null}
        </span>
        <span className="ml-auto text-sm text-muted-foreground">{site.deviceCount} {site.deviceCount === 1 ? 'device' : 'devices'}</span>
        <HealthBadge health={site.health} />
      </button>
      {expanded ? (
        <div className="border-t border-border bg-muted/20">
          {rows === null && !error ? <p className="px-4 py-4 text-sm text-muted-foreground">Loading devices…</p> : null}
          {rows !== null && shown.length === 0 && !error ? (
            <p className="px-4 py-4 text-sm text-muted-foreground">{site.deviceCount === 0 ? 'No devices in this site yet.' : 'No devices in this site match these filters.'}</p>
          ) : null}
          {rows !== null && (shown.length > 0 || error) ? (
            <DeviceTable
              rows={error ? null : shown}
              error={error}
              onRetry={() => {
                setRows(null);
                setRetry((value) => value + 1);
              }}
              visible={visible.filter((column) => column !== 'site')}
              selected={selected}
              onSelect={onSelect}
              sortKey={query.sortKey}
              sortDir={query.sortDir}
              onSort={onSort}
              onClear={onClear}
            />
          ) : null}
        </div>
      ) : null}
    </article>
  );
}