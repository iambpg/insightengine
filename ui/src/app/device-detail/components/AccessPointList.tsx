'use client';

import React, { useState } from 'react';
import { api } from '@/lib/apiClient';
import { useKeyedLoad } from '@/lib/useKeyedLoad';
import type { AccessPointEvent, AccessPointRow } from '@/lib/types';

const PAGE = 50;

export default function AccessPointList({ wlc }: { wlc: string }) {
  const [page, setPage] = useState(1);
  const [q, setQ] = useState('');
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState('');
  const key = `${wlc}|${page}|${query}`;
  const loaded = useKeyedLoad(key, true, 0, 'access points', () =>
    api.listAccessPoints({ wlc, page, pageSize: PAGE, q: query }),
  );
  const detail = useKeyedLoad(open, Boolean(open), 0, 'access point', () => api.getAccessPointDetail(wlc, open));
  const body = loaded.data;
  const rows = body?.rows ?? [];
  const total = body?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / PAGE));
  const selected = detail.data?.accessPoint;
  const events = detail.data?.events ?? [];
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
        </form>
      </div>
      {loaded.error ? <p className="mt-3 text-sm text-destructive">{loaded.error}</p> : null}
      <div className="scroll-thin mt-3 overflow-x-auto">
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-muted-foreground">
              <th className="py-1.5 pr-3 font-semibold">Name</th>
              <th className="py-1.5 pr-3 font-semibold">Site</th>
              <th className="py-1.5 pr-3 font-semibold">Status</th>
              <th className="py-1.5 pr-3 font-semibold">Clients</th>
              <th className="py-1.5 pr-3 font-semibold">Neighbour</th>
              <th className="py-1.5 font-semibold">Radios</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row: AccessPointRow) => (
              <tr key={`${row.wlc}-${row.name}-${row.mac}`} className="border-b border-border/70">
                <td className="py-1.5 pr-3">
                  <button type="button" className="text-left font-medium text-primary" onClick={() => setOpen(row.name)}>
                    {row.name}
                  </button>
                  <span className="mt-0.5 block font-mono-data text-xs text-muted-foreground">{row.model || row.mac}</span>
                </td>
                <td className="py-1.5 pr-3">{row.netboxSite || row.site || '—'}</td>
                <td className="py-1.5 pr-3">{row.status}</td>
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
            ))}
          </tbody>
        </table>
      </div>
      <div className="mt-3 flex items-center justify-between text-sm">
        <button type="button" disabled={page <= 1} onClick={() => setPage((n) => Math.max(1, n - 1))} className="rounded-md border border-border px-3 py-1 disabled:opacity-40">Previous</button>
        <span className="text-muted-foreground">Page {page} of {pages}</span>
        <button type="button" disabled={page >= pages} onClick={() => setPage((n) => n + 1)} className="rounded-md border border-border px-3 py-1 disabled:opacity-40">Next</button>
      </div>
      {open ? <ApDetail row={selected} events={events} error={detail.error || ''} onClose={() => setOpen('')} /> : null}
    </section>
  );
}

function ApDetail({ row, events, error, onClose }: { row?: AccessPointRow; events: AccessPointEvent[]; error: string; onClose: () => void }) {
  return (
    <div className="mt-4 rounded-md border border-border p-3" aria-label="Access point detail">
      <div className="flex items-start justify-between gap-3">
        <h3 className="text-sm font-semibold">{row?.name || 'Access point'}</h3>
        <button type="button" onClick={onClose} className="text-xs text-muted-foreground">Close</button>
      </div>
      {error ? <p className="mt-2 text-sm text-destructive">{error}</p> : null}
      {!row ? <p className="mt-2 text-sm text-muted-foreground">Loading.</p> : (
        <div className="mt-3 grid gap-4 lg:grid-cols-2">
          <div className="text-sm">
            <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Inventory</h4>
            <dl className="mt-2 space-y-1">
              <Fact label="Model" value={row.model} />
              <Fact label="Serial" value={row.serial} />
              <Fact label="IP" value={row.ip} />
              <Fact label="MAC" value={row.mac} />
              <Fact label="Location" value={row.location} />
              <Fact label="IOS" value={row.ios} />
              <Fact label="Mode" value={row.mode} />
              <Fact label="NetBox site" value={row.netboxSite || row.site} />
              <Fact label="Switch" value={row.neighborSwitch ? `${row.neighborSwitch} ${row.neighborPort || ''}`.trim() : ''} />
            </dl>
          </div>
          <div className="text-sm">
            <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Radios and RRM</h4>
            {row.radios.length === 0 ? <p className="mt-2 text-muted-foreground">No radios.</p> : (
              <ul className="mt-2 space-y-2">
                {row.radios.map((radio) => (
                  <li key={radio.slot} className="rounded-md bg-muted/40 px-2 py-1.5 text-xs">
                    Slot {radio.slot || '—'} {radio.band ? `band ${radio.band}` : ''} channel {radio.channel ?? '—'}
                    {radio.width != null ? ` / ${radio.width} MHz` : ''} tx {radio.txPowerDbm ?? '—'} dBm
                    {' '}util {radio.utilization == null ? '—' : `${Math.round(radio.utilization * 100)}%`}
                    {' '}noise {radio.noise ?? '—'} interference {radio.interference ?? '—'}
                    {' '}clients {radio.clients ?? '—'} RSSI {radio.rssiAvg ?? '—'} SNR {radio.snrAvg ?? '—'}
                  </li>
                ))}
              </ul>
            )}
            <h4 className="mt-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Clients per SSID</h4>
            {(row.ssids || []).length === 0 ? <p className="mt-2 text-muted-foreground">No SSID counts.</p> : (
              <ul className="mt-2 space-y-1 text-xs">
                {(row.ssids || []).map((ssid) => (
                  <li key={`${ssid.ssid}-${ssid.radio}`}>{ssid.ssid || 'SSID'} band {ssid.band || '—'} radio {ssid.radio || '—'}: {ssid.clients ?? '—'}</li>
                ))}
              </ul>
            )}
            <h4 className="mt-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Events</h4>
            {events.length === 0 ? <p className="mt-2 text-muted-foreground">No oper, channel or tx-power changes in the last 6 hours.</p> : (
              <ul className="mt-2 space-y-1 text-xs">
                {events.map((event) => (
                  <li key={`${event.t}-${event.what}-${event.radio}`}>{new Date(event.t * 1000).toISOString()} {event.what} {event.radio ? `radio ${event.radio}` : ''} {String(event.from)} → {String(event.to)}</li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function Fact({ label, value }: { label: string; value?: string | null }) {
  return (
    <div className="flex justify-between gap-3 border-b border-border/50 py-0.5">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="font-mono-data text-xs">{value || '—'}</dd>
    </div>
  );
}
