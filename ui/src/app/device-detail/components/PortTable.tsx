'use client';

import React, { useMemo, useState } from 'react';
import Icon from '@/components/ui/AppIcon';
import EmptyState from '@/components/ui/EmptyState';
import Pagination from '@/components/ui/Pagination';
import { PortStateBadge } from '@/components/ui/Badge';
import type { PortInfo, PortState } from '@/lib/types';

type Filter = PortState | 'all';

export default function PortTable({ ports, selectedId, onSelect }: { ports: PortInfo[]; selectedId: string | null; onSelect: (p: PortInfo) => void }) {
  const [filter, setFilter] = useState<Filter>('all');
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);

  const rows = useMemo(() => {
    const s = search.trim().toLowerCase();
    return ports.filter((p) => (filter === 'all' || p.state === filter) && (!s || p.name.toLowerCase().includes(s) || p.neighbour?.device.toLowerCase().includes(s)));
  }, [ports, filter, search]);

  const pageRows = rows.slice((page - 1) * pageSize, page * pageSize);
  const FILTERS: Filter[] = ['all', 'up', 'warning', 'fault', 'down', 'disabled'];

  return (
    <section className="rounded-lg border border-border bg-card shadow-card" aria-labelledby="ports-title">
      <header className="flex flex-wrap items-center gap-3 border-b border-border px-4 py-2.5">
        <h2 id="ports-title" className="text-base font-semibold">Ports</h2>
        <label className="relative ml-auto min-w-[200px]">
          <span className="sr-only">Search ports</span>
          <Icon name="MagnifyingGlassIcon" size={14} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
          <input
            type="search"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setPage(1);
            }}
            placeholder="Port or neighbour…"
            className="h-8 w-full rounded-md border border-input bg-background pl-8 pr-2 text-sm outline-none focus:border-ring"
          />
        </label>
        <div role="radiogroup" aria-label="Filter ports by state" className="flex flex-wrap gap-1">
          {FILTERS.map((f) => (
            <button
              key={`pf-${f}`}
              type="button"
              role="radio"
              aria-checked={filter === f}
              onClick={() => {
                setFilter(f);
                setPage(1);
              }}
              className={`rounded-full border px-2.5 py-1 text-xs font-medium capitalize transition-all active:scale-95 ${filter === f ? 'border-navy bg-navy text-primary-foreground' : 'border-border text-muted-foreground hover:bg-muted'}`}
            >
              {f}
            </button>
          ))}
        </div>
      </header>
      {rows.length === 0 ? (
        <EmptyState icon="CircleStackIcon" title="No ports match" description="No port on this device matches the current state filter or search." actionLabel="Show all ports" onAction={() => { setFilter('all'); setSearch(''); }} />
      ) : (
        <div className="scroll-thin overflow-x-auto">
          <table className="w-full min-w-[760px] text-sm">
            <thead>
              <tr className="border-b border-border bg-muted/60 text-left text-xs uppercase tracking-wide text-muted-foreground">
                <th scope="col" className="px-4 py-2.5">Port</th>
                <th scope="col" className="px-3 py-2.5">State</th>
                <th scope="col" className="px-3 py-2.5">Type</th>
                <th scope="col" className="px-3 py-2.5">Speed</th>
                <th scope="col" className="px-3 py-2.5">Utilisation</th>
                <th scope="col" className="px-3 py-2.5 text-right">Errors</th>
                <th scope="col" className="px-3 py-2.5">Neighbour</th>
              </tr>
            </thead>
            <tbody>
              {pageRows.map((p) => (
                <tr
                  key={p.id}
                  onClick={() => onSelect(p)}
                  className={`cursor-pointer border-b border-border transition-colors even:bg-muted/20 hover:bg-accent/10 ${selectedId === p.id ? 'bg-accent/20' : ''}`}
                >
                  <td className="px-4 py-2 font-mono-data font-semibold">{p.name}</td>
                  <td className="px-3 py-2"><PortStateBadge state={p.state} /></td>
                  <td className="px-3 py-2 font-mono-data text-xs text-muted-foreground">{p.type}</td>
                  <td className="px-3 py-2 font-mono-data text-xs">{p.speed}</td>
                  <td className="px-3 py-2">
                    <div className="flex items-center gap-2">
                      <div className="h-1.5 w-20 overflow-hidden rounded-full bg-muted">
                        <div className="h-full rounded-full" style={{ width: `${Math.min(100, p.utilisation)}%`, backgroundColor: p.utilisation > 85 ? 'var(--destructive)' : p.utilisation > 65 ? 'var(--warning)' : 'var(--teal)' }} />
                      </div>
                      <span className="font-mono-data text-xs tabular">{p.utilisation}%</span>
                    </div>
                  </td>
                  <td className={`px-3 py-2 text-right font-mono-data text-xs tabular ${p.errors > 100 ? 'font-semibold text-destructive' : p.errors > 0 ? 'text-warning-foreground' : 'text-muted-foreground'}`}>
                    {p.errors.toLocaleString('en-US')}
                  </td>
                  <td className="px-3 py-2 font-mono-data text-xs text-muted-foreground">{p.neighbour ? `${p.neighbour.device} · ${p.neighbour.port}` : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <Pagination page={page} pageSize={pageSize} total={rows.length} noun="ports" onPage={setPage} onPageSize={(n) => { setPageSize(n); setPage(1); }} sizes={[10, 25, 50]} />
    </section>
  );
}