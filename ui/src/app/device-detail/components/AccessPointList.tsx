'use client';

import React, { useState } from 'react';
import Link from 'next/link';
import { HealthBadge } from '@/components/ui/Badge';
import AddApDialog, { type ApDraft } from '@/components/AddApDialog';
import { api } from '@/lib/apiClient';
import { accessPointId, deviceHealthPath } from '@/lib/deviceHealthPath';
import { devicePath } from '@/lib/apiMode';
import { useKeyedLoad } from '@/lib/useKeyedLoad';
import { allowOperate } from '@/lib/settings/access';
import { useKnownRole } from '@/lib/useSession';
import type { AccessPointRow, DeviceHealth } from '@/lib/types';

const PAGE = 50;

function apHealth(status: string): DeviceHealth {
  const word = (status || '').toLowerCase();
  if (word === 'down') return 'critical';
  if (word === 'disassociating') return 'warning';
  return 'healthy';
}

function draftOf(row: AccessPointRow): ApDraft {
  return {
    name: row.name,
    wlc: row.wlc,
    model: row.model,
    serial: row.serial,
    ip: row.ip,
    ios: row.ios,
    location: row.location,
    siteTag: row.siteTag,
    suggestedSite: row.suggestedSite || row.netboxSite || row.site,
  };
}

export default function AccessPointList({ wlc }: { wlc: string }) {
  const canWrite = allowOperate(useKnownRole());
  const [page, setPage] = useState(1);
  const [q, setQ] = useState('');
  const [query, setQuery] = useState('');
  const [picked, setPicked] = useState<string[]>([]);
  const [adding, setAdding] = useState<ApDraft[]>([]);
  const key = `${wlc}|${page}|${query}`;
  const loaded = useKeyedLoad(key, true, 0, 'access points', () =>
    api.listAccessPoints({ wlc, page, pageSize: PAGE, q: query }),
  );
  const body = loaded.data;
  const rows = body?.rows ?? [];
  const total = body?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / PAGE));
  const rowId = (row: AccessPointRow) => row.mac || row.name;
  const selectable = rows.filter((row) => !row.inNetbox);
  const allOn = selectable.length > 0 && selectable.every((row) => picked.includes(rowId(row)));
  const chosen = rows.filter((row) => picked.includes(rowId(row)) && !row.inNetbox);
  return (
    <section className="rounded-none border-x-0 border-y border-border bg-card p-4 shadow-card" aria-labelledby="ap-list-title">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 id="ap-list-title" className="text-base font-semibold">Access points</h2>
          <p className="text-xs text-muted-foreground">
            {total} on this controller. Inventory, radios, RRM and neighbour come from the WLC. The site is the NetBox device site when the AP name or CDP switch matches.
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
            placeholder="Name, MAC or switch"
            className="rounded-md border border-border bg-background px-3 py-1.5 text-sm"
          />
          <button type="submit" className="rounded-md border border-border px-3 py-1.5 text-sm font-medium">Filter</button>
          {canWrite ? (
            <button type="button" disabled={chosen.length === 0} onClick={() => setAdding(chosen.map(draftOf))} className="rounded-md bg-primary px-3 py-1.5 text-sm font-semibold text-primary-foreground disabled:opacity-40">
              Add selected to NetBox
            </button>
          ) : null}
        </form>
      </div>
      {loaded.error ? <p className="mt-3 text-sm text-destructive">{loaded.error}</p> : null}
      <div className="scroll-thin mt-3 overflow-x-auto">
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-muted-foreground">
              <th className="py-1.5 pr-3 font-semibold">
                <input
                  type="checkbox"
                  aria-label="Select access points"
                  checked={allOn}
                  onChange={() => setPicked(allOn ? [] : selectable.map((row) => row.mac || row.name))}
                />
              </th>
              <th className="py-1.5 pr-3 font-semibold">Name</th>
              <th className="py-1.5 pr-3 font-semibold">Health</th>
              <th className="py-1.5 pr-3 font-semibold">Site</th>
              <th className="py-1.5 pr-3 font-semibold">Status</th>
              <th className="py-1.5 pr-3 font-semibold">Clients</th>
              <th className="py-1.5 pr-3 font-semibold">Neighbour</th>
              <th className="py-1.5 font-semibold">Radios</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row: AccessPointRow) => {
              const health = apHealth(row.status);
              const identity = row.mac || row.name;
              const href = devicePath(accessPointId(row.netboxId, identity), 'ceiling-ap');
              const pickedOn = picked.includes(identity);
              return (
                <tr key={`${row.wlc}-${identity}`} className="border-b border-border/70">
                  <td className="py-1.5 pr-3">
                    {row.inNetbox ? (
                      <span className="text-xs text-muted-foreground">In NetBox</span>
                    ) : (
                      <input
                        type="checkbox"
                        aria-label={`Select ${row.name}`}
                        checked={pickedOn}
                        onChange={() => setPicked((current) => pickedOn ? current.filter((item) => item !== identity) : [...current, identity])}
                      />
                    )}
                  </td>
                  <td className="py-1.5 pr-3">
                    <Link href={href} className="font-medium text-primary hover:underline">{row.name}</Link>
                    <span className="mt-0.5 block font-mono-data text-xs text-muted-foreground">{[row.model, row.mac].filter(Boolean).join(' · ') || '—'}</span>
                    {canWrite && !row.inNetbox ? (
                      <button type="button" className="mt-1 text-xs font-semibold" onClick={() => setAdding([draftOf(row)])}>Add to NetBox</button>
                    ) : null}
                  </td>
                  <td className="py-1.5 pr-3">
                    <HealthBadge health={health} href={deviceHealthPath(accessPointId(row.netboxId, identity), 'ceiling-ap', health)} />
                  </td>
                  <td className="py-1.5 pr-3">{row.netboxSite || row.site || '—'}</td>
                  <td className="py-1.5 pr-3">{row.status === 'up' ? 'Up' : row.status === 'down' ? 'Offline' : row.status || 'Unknown'}</td>
                  <td className="py-1.5 pr-3 tabular">{row.clients ?? '—'}</td>
                  <td className="py-1.5 pr-3 text-xs">
                    {row.neighborSwitch ? `${row.neighborSwitch} ${row.neighborPort || ''}`.trim() : '—'}
                  </td>
                  <td className="py-1.5 text-xs text-muted-foreground">
                    {row.radios.length === 0
                      ? '—'
                      : row.radios.map((radio) => `s${radio.slot || '?'}:${radio.channel ?? '—'}`).join(' ')}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="mt-3 flex items-center justify-between text-sm">
        <button type="button" disabled={page <= 1} onClick={() => setPage((n) => Math.max(1, n - 1))} className="rounded-md border border-border px-3 py-1 disabled:opacity-40">Previous</button>
        <span className="text-muted-foreground">Page {page} of {pages}</span>
        <button type="button" disabled={page >= pages} onClick={() => setPage((n) => n + 1)} className="rounded-md border border-border px-3 py-1 disabled:opacity-40">Next</button>
      </div>
      <AddApDialog open={adding.length > 0} aps={adding} onClose={() => setAdding([])} onDone={() => setPicked([])} />
    </section>
  );
}
