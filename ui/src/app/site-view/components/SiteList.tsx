'use client';

import React from 'react';
import Icon from '@/components/ui/AppIcon';
import EmptyState from '@/components/ui/EmptyState';
import { HealthBadge } from '@/components/ui/Badge';
import { Skeleton } from '@/components/ui/Skeleton';
import type { SiteRow } from '@/lib/types';

interface Props {
  rows: SiteRow[] | null;
  error: string | null;
  onRetry: () => void;
  activeId: string | null;
  onPick: (s: SiteRow) => void;
  onClear: () => void;
}

export default function SiteList({ rows, error, onRetry, activeId, onPick, onClear }: Props) {
  if (error) {
    return (
      <div role="alert" className="m-3 flex items-center justify-between gap-3 rounded-md border border-destructive/30 bg-destructive/10 px-3 py-3 text-sm text-destructive">
        <span>{error}</span>
        <button type="button" onClick={onRetry} className="rounded-md border border-destructive/40 px-2 py-1 text-xs font-semibold">Retry</button>
      </div>
    );
  }
  if (rows === null) {
    return (
      <div className="space-y-px p-3">
        {Array.from({ length: 8 }, (_, i) => (
          <Skeleton key={`site-skel-${i + 1}`} className="mb-2 h-14 w-full" />
        ))}
      </div>
    );
  }
  if (rows.length === 0) {
    return <EmptyState icon="BuildingOffice2Icon" title="No sites match" description="No site matches your search, region or health filter." actionLabel="Clear filters" onAction={onClear} />;
  }
  return (
    <ul className="scroll-thin max-h-[560px] flex-1 divide-y divide-border overflow-y-auto fade-in">
      {rows.map((s) => {
        const on = s.id === activeId;
        return (
          <li key={s.id}>
            <button
              type="button"
              onClick={() => onPick(s)}
              aria-current={on ? 'true' : undefined}
              className={`flex w-full items-start gap-3 px-4 py-3 text-left transition-colors hover:bg-accent/10 ${on ? 'bg-accent/15 shadow-[inset_3px_0_0_var(--accent)]' : ''}`}
            >
              <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground">
                <Icon name="BuildingOffice2Icon" size={16} />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-semibold">{s.name}</span>
                <span className="mt-0.5 flex flex-wrap items-center gap-x-2 text-xs text-muted-foreground">
                  <span>{s.region}</span>
                  <span className="font-mono-data tabular">{s.deviceCount} devices</span>
                  {s.alerts > 0 && <span className="font-semibold text-destructive">▲ {s.alerts} alerts</span>}
                </span>
              </span>
              <HealthBadge health={s.health} />
            </button>
          </li>
        );
      })}
    </ul>
  );
}