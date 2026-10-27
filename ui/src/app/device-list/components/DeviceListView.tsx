'use client';

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import Icon from '@/components/ui/AppIcon';
import ExampleDataBanner from '@/components/ui/ExampleDataBanner';
import Pagination from '@/components/ui/Pagination';
import { api, type DeviceQuery } from '@/lib/apiClient';
import { isMockMode } from '@/lib/apiMode';
import type { DeviceHealth, DeviceRow } from '@/lib/types';
import HealthStrip from './HealthStrip';
import DeviceFilters from './DeviceFilters';
import DeviceTable from './DeviceTable';
import ColumnMenu, { COLUMNS, type ColumnKey } from './ColumnMenu';

export default function DeviceListView() {
  const [query, setQuery] = useState<DeviceQuery>({
    page: 1,
    pageSize: 25,
    search: '',
    health: 'all',
    role: 'all',
    sortKey: 'hostname',
    sortDir: 'asc',
  });
  const [rows, setRows] = useState<DeviceRow[] | null>(null);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);
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
    setRows(null);
    setError(null);
    api
      .listDevices(query)
      .then((res) => {
        if (cancelled) return;
        setRows(res.rows);
        setTotal(res.total);
        if (res.roles) setRoles(res.roles);
      })
      .catch(() => !cancelled && setError('Failed to load devices. Check your connection and try again.'));
    return () => {
      cancelled = true;
    };
  }, [query, reload]);

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
            Fleet health across ~2,000 sites. Open a device to see its faceplate and port graphs.
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

      <section className="rounded-none border-x-0 border-y border-border bg-card shadow-card" aria-label="Device table">
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
            <button type="button" className="rounded-md bg-navy-3 px-2.5 py-1 text-xs font-medium transition-all hover:bg-navy-2 active:scale-95">Acknowledge alerts</button>
            <button type="button" className="rounded-md bg-navy-3 px-2.5 py-1 text-xs font-medium transition-all hover:bg-navy-2 active:scale-95">Export CSV</button>
            <button type="button" onClick={() => setSelected([])} className="ml-auto text-xs text-down hover:text-primary-foreground">Clear selection</button>
          </div>
        )}

        <DeviceTable
          rows={rows}
          error={error}
          onRetry={() => setReload((n) => n + 1)}
          visible={visible}
          selected={selected}
          onSelect={setSelected}
          sortKey={query.sortKey}
          sortDir={query.sortDir}
          onSort={(k) => patch({ sortKey: k, sortDir: query.sortKey === k && query.sortDir === 'asc' ? 'desc' : 'asc', page: 1 })}
          onClear={() => patch({ search: '', health: 'all', role: 'all' })}
        />

        <Pagination
          page={query.page}
          pageSize={query.pageSize}
          total={total}
          noun="devices"
          onPage={(p) => setQuery((q) => ({ ...q, page: p }))}
          onPageSize={(n) => setQuery((q) => ({ ...q, pageSize: n, page: 1 }))}
        />
      </section>
    </div>
  );
}