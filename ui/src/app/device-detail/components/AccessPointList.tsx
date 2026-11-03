'use client';

import React, { useState } from 'react';
import { api } from '@/lib/apiClient';
import { useKeyedLoad } from '@/lib/useKeyedLoad';
import type { AccessPointRow } from '@/lib/types';

const PAGE = 50;

export default function AccessPointList({ wlc }: { wlc: string }) {
  const [page, setPage] = useState(1);
  const [q, setQ] = useState('');
  const [query, setQuery] = useState('');
  const key = `${wlc}|${page}|${query}`;
  const loaded = useKeyedLoad(key, true, 0, 'access points', () =>
    api.listAccessPoints({ wlc, page, pageSize: PAGE, q: query }),
  );
  const body = loaded.data;
  const rows = body?.rows ?? [];
  const total = body?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / PAGE));
  return (
    <section className="rounded-none border-x-0 border-y border-border bg-card p-4 shadow-card" aria-labelledby="ap-list-title">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 id="ap-list-title" className="text-base font-semibold">Access points</h2>
          <p className="text-xs text-muted-foreground">
            {total} on this controller. The list is paged. Telegraf collects these rows from the WLC.
          </p>
        </div>
        <form
          className="flex gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            setPage(1);
            setQuery(q.trim());
          }}
        >
          <label className="sr-only" htmlFor="ap-filter">Filter access points</label>
          <input
            id="ap-filter"
            value={q}
            onChange={(event) => setQ(event.target.value)}
            placeholder="Name or MAC"
            className="rounded-md border border-border bg-background px-3 py-1.5 text-sm"
          />
          <button type="submit" className="rounded-md border border-border px-3 py-1.5 text-sm font-medium">Filter</button>
        </form>
      </div>
      {loaded.error ? <p className="mt-3 text-sm text-destructive">{loaded.error}</p> : null}
      <table className="mt-3 w-full border-collapse text-sm">
        <thead>
          <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-muted-foreground">
            <th className="py-1.5 pr-3 font-semibold">Name</th>
            <th className="py-1.5 pr-3 font-semibold">Status</th>
            <th className="py-1.5 pr-3 font-semibold">Clients</th>
            <th className="py-1.5 font-semibold">Radios</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row: AccessPointRow) => (
            <tr key={`${row.wlc}-${row.name}-${row.mac}`} className="border-b border-border/70">
              <td className="py-1.5 pr-3">
                <span className="font-medium">{row.name}</span>
                <span className="mt-0.5 block font-mono-data text-xs text-muted-foreground">{row.mac}</span>
              </td>
              <td className="py-1.5 pr-3">{row.status}</td>
              <td className="py-1.5 pr-3 tabular">{row.clients ?? '—'}</td>
              <td className="py-1.5 text-xs text-muted-foreground">
                {row.radios.length === 0
                  ? '—'
                  : row.radios.map((radio) => `s${radio.slot || '?'}:${radio.channel ?? '—'}`).join(' ')}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="mt-3 flex items-center justify-between text-sm">
        <button type="button" disabled={page <= 1} onClick={() => setPage((n) => Math.max(1, n - 1))} className="rounded-md border border-border px-3 py-1 disabled:opacity-40">Previous</button>
        <span className="text-muted-foreground">Page {page} of {pages}</span>
        <button type="button" disabled={page >= pages} onClick={() => setPage((n) => n + 1)} className="rounded-md border border-border px-3 py-1 disabled:opacity-40">Next</button>
      </div>
    </section>
  );
}
