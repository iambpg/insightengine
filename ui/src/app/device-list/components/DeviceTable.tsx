'use client';

import React, { useState } from 'react';
import Link from 'next/link';
import Icon from '@/components/ui/AppIcon';
import EmptyState from '@/components/ui/EmptyState';
import { HealthBadge } from '@/components/ui/Badge';
import { TableSkeleton } from '@/components/ui/Skeleton';
import type { DeviceRow } from '@/lib/types';
import type { ColumnKey } from './ColumnMenu';
import PortBar from './PortBar';
import HoverPreview from './HoverPreview';

interface Props {
  rows: DeviceRow[] | null;
  error: string | null;
  onRetry: () => void;
  visible: ColumnKey[];
  selected: string[];
  onSelect: (ids: string[]) => void;
  sortKey: keyof DeviceRow;
  sortDir: 'asc' | 'desc';
  onSort: (k: keyof DeviceRow) => void;
  onClear: () => void;
}

const HEAD: { col: ColumnKey; label: string; sort?: keyof DeviceRow; align?: 'right' }[] = [
  { col: 'health', label: 'Health', sort: 'health' },
  { col: 'hostname', label: 'Hostname', sort: 'hostname' },
  { col: 'role', label: 'Role', sort: 'role' },
  { col: 'site', label: 'Site', sort: 'site' },
  { col: 'mgmtIp', label: 'Management IP', sort: 'mgmtIp' },
  { col: 'modelFamily', label: 'Model family', sort: 'modelFamily' },
  { col: 'ports', label: 'Ports up / total', sort: 'portsUp' },
  { col: 'faults', label: 'Warn / fault', sort: 'portsFault' },
  { col: 'uptime', label: 'Uptime' },
  { col: 'lastPoll', label: 'Last poll' },
];

export default function DeviceTable({ rows, error, onRetry, visible, selected, onSelect, sortKey, sortDir, onSort, onClear }: Props) {
  const [hoverId, setHoverId] = useState<string | null>(null);
  const show = (c: ColumnKey) => visible.includes(c);
  const allOn = !!rows && rows.length > 0 && rows.every((r) => selected.includes(r.id));

  if (error) {
    return (
      <div role="alert" className="m-4 flex items-center justify-between gap-3 rounded-md border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
        <span className="flex items-center gap-2"><Icon name="ExclamationCircleIcon" size={18} />{error}</span>
        <button type="button" onClick={onRetry} className="rounded-md border border-destructive/40 px-3 py-1 text-xs font-semibold hover:bg-destructive/10">Retry</button>
      </div>
    );
  }

  if (rows === null) return <TableSkeleton rows={10} cols={8} />;

  if (rows.length === 0) {
    return (
      <EmptyState
        icon="ServerStackIcon"
        title="No devices match these filters"
        description="No device has a hostname, IP or site matching your search and filters. Clear them to see the full fleet."
        actionLabel="Clear all filters"
        onAction={onClear}
      />
    );
  }

  return (
    <div className="scroll-thin overflow-x-auto">
      <table className="w-full min-w-[1080px] border-collapse text-sm">
        <thead>
          <tr className="border-b border-border bg-muted/60 text-left">
            <th scope="col" className="w-10 px-4 py-2.5">
              <input
                type="checkbox"
                aria-label="Select all devices on this page"
                checked={allOn}
                onChange={() => onSelect(allOn ? [] : rows.map((r) => r.id))}
                className="h-4 w-4 accent-[var(--primary)]"
              />
            </th>
            {HEAD.filter((h) => show(h.col)).map((h) => {
              const active = h.sort === sortKey;
              return (
                <th
                  key={`th-${h.col}`}
                  scope="col"
                  aria-sort={active ? (sortDir === 'asc' ? 'ascending' : 'descending') : 'none'}
                  className="px-3 py-2.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground"
                >
                  {h.sort ? (
                    <button type="button" onClick={() => onSort(h.sort!)} className={`inline-flex items-center gap-1 transition-colors hover:text-foreground ${active ? 'text-foreground' : ''}`}>
                      {h.label}
                      <Icon name={active ? (sortDir === 'asc' ? 'ArrowUpIcon' : 'ArrowDownIcon') : 'ArrowsUpDownIcon'} size={12} />
                    </button>
                  ) : (
                    h.label
                  )}
                </th>
              );
            })}
            <th scope="col" className="w-24 px-3 py-2.5"><span className="sr-only">Actions</span></th>
          </tr>
        </thead>
        <tbody className="fade-in">
          {rows.map((r) => {
            const on = selected.includes(r.id);
            return (
              <tr key={r.id} className={`group border-b border-border transition-colors even:bg-muted/20 hover:bg-accent/10 ${on ? 'bg-accent/15' : ''}`}>
                <td className="px-4 py-2.5">
                  <input
                    type="checkbox"
                    aria-label={`Select ${r.hostname}`}
                    checked={on}
                    onChange={() => onSelect(on ? selected.filter((s) => s !== r.id) : [...selected, r.id])}
                    className="h-4 w-4 accent-[var(--primary)]"
                  />
                </td>
                {show('health') && <td className="px-3 py-2.5"><HealthBadge health={r.health} /></td>}
                {show('hostname') && (
                  <td className="relative px-3 py-2.5" onMouseEnter={() => setHoverId(r.id)} onMouseLeave={() => setHoverId(null)}>
                    <Link href={`/device-detail?form=${r.formFactor}`} className="font-mono-data font-semibold text-foreground underline-offset-2 hover:text-primary hover:underline">
                      {r.hostname}
                    </Link>
                    {hoverId === r.id && <HoverPreview row={r} />}
                  </td>
                )}
                {show('role') && <td className="px-3 py-2.5 text-muted-foreground">{r.role}</td>}
                {show('site') && (
                  <td className="max-w-[180px] truncate px-3 py-2.5">
                    <Link href="/site-view" className="hover:text-primary hover:underline" title={r.site}>{r.site}</Link>
                  </td>
                )}
                {show('mgmtIp') && <td className="px-3 py-2.5 font-mono-data text-xs">{r.mgmtIp}</td>}
                {show('modelFamily') && <td className="px-3 py-2.5 text-muted-foreground">{r.modelFamily}</td>}
                {show('ports') && <td className="px-3 py-2.5">{r.health === 'unreachable' ? <span className="text-muted-foreground">no data</span> : <PortBar row={r} />}</td>}
                {show('faults') && (
                  <td className="px-3 py-2.5 font-mono-data text-xs tabular">
                    <span className={r.portsWarn > 0 ? 'font-semibold text-warning-foreground' : 'text-muted-foreground'}>
                      {r.portsWarn > 0 ? '▲ ' : ''}{r.portsWarn}
                    </span>
                    <span className="mx-1 text-muted-foreground">/</span>
                    <span className={r.portsFault > 0 ? 'font-semibold text-destructive' : 'text-muted-foreground'}>
                      {r.portsFault > 0 ? '✕ ' : ''}{r.portsFault}
                    </span>
                  </td>
                )}
                {show('uptime') && <td className="px-3 py-2.5 font-mono-data text-xs tabular text-muted-foreground">{r.uptime}</td>}
                {show('lastPoll') && (
                  <td className={`px-3 py-2.5 font-mono-data text-xs tabular ${r.health === 'unreachable' ? 'font-semibold text-destructive' : 'text-muted-foreground'}`}>
                    {r.lastPoll}
                  </td>
                )}
                <td className="px-3 py-2.5">
                  <div className="flex items-center justify-end gap-1 opacity-0 transition-opacity focus-within:opacity-100 group-hover:opacity-100">
                    <RowAction href={`/device-detail?form=${r.formFactor}`} icon="EyeIcon" label="Open device" />
                    <RowAction href="/site-view" icon="BuildingOffice2Icon" label="Open site" />
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function RowAction({ href, icon, label }: { href: string; icon: string; label: string }) {
  return (
    <span className="group/tip relative">
      <Link href={href} aria-label={label} className="flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground transition-all hover:bg-muted hover:text-foreground active:scale-95">
        <Icon name={icon} size={15} />
      </Link>
      <span role="tooltip" className="pointer-events-none absolute -top-8 right-0 whitespace-nowrap rounded-md bg-navy px-2 py-1 text-[11px] text-primary-foreground opacity-0 shadow-pop transition-opacity group-hover/tip:opacity-100">
        {label}
      </span>
    </span>
  );
}