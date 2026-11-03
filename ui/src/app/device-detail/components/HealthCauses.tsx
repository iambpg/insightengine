'use client';

import React from 'react';
import type { DeviceHealth, HealthCause } from '@/lib/types';

export type HealthFilter = 'all' | 'critical' | 'warning' | 'info';

const CHIPS: { key: HealthFilter; label: string }[] = [
  { key: 'all', label: 'All' },
  { key: 'critical', label: 'Critical' },
  { key: 'warning', label: 'Warning' },
  { key: 'info', label: 'Info' },
];

const TONE: Record<HealthCause['severity'], string> = {
  critical: 'border-destructive/30 bg-destructive/5 text-destructive',
  warning: 'border-warning/40 bg-warning/10 text-warning-foreground',
  info: 'border-info/30 bg-info/5 text-info',
};

export default function HealthCauses({
  items,
  health,
  filter,
  onFilter,
}: {
  items: HealthCause[];
  health: DeviceHealth;
  filter: HealthFilter;
  onFilter: (next: HealthFilter) => void;
}) {
  const visible = filter === 'all' ? items : items.filter((item) => item.severity === filter);
  return (
    <section id="health" tabIndex={-1} data-health={health} className="rounded-none border-x-0 border-y border-border bg-card shadow-card outline-none" aria-labelledby="health-causes-title">
      <header className="flex flex-wrap items-end justify-between gap-3 border-b border-border px-4 py-2.5">
        <div>
          <h2 id="health-causes-title" className="text-base font-semibold">Health</h2>
          <p className="text-xs text-muted-foreground">Every item that sets this device&apos;s health badge.</p>
        </div>
        <div className="flex flex-wrap gap-1.5" role="toolbar" aria-label="Health severity">
          {CHIPS.map((chip) => {
            const count = chip.key === 'all' ? items.length : items.filter((item) => item.severity === chip.key).length;
            const on = filter === chip.key;
            return (
              <button
                key={chip.key}
                type="button"
                aria-pressed={on}
                onClick={() => onFilter(chip.key)}
                className={`rounded-full border px-2.5 py-1 text-xs font-semibold ${on ? 'border-primary bg-primary/10 text-foreground' : 'border-border text-muted-foreground hover:bg-muted'}`}
              >
                {chip.label} <span className="tabular">{count}</span>
              </button>
            );
          })}
        </div>
      </header>
      <div className="p-3">
        {visible.length === 0 ? (
          <p className="px-1 py-6 text-center text-sm text-muted-foreground">
            {items.length === 0 ? 'No issues — healthy' : `No ${filter} issues.`}
          </p>
        ) : (
          <ul className="space-y-1.5">
            {visible.map((item) => (
              <li key={item.id} className={`rounded-md border px-3 py-2 ${TONE[item.severity]}`}>
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <p className="text-sm font-semibold text-foreground">{item.title}</p>
                  <span className="label-caps">{item.severity}</span>
                </div>
                {item.detail ? <p className="mt-0.5 text-sm text-muted-foreground">{item.detail}</p> : null}
                <dl className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
                  <div><dt className="inline">Value </dt><dd className="inline font-mono-data text-foreground">{item.value || '—'}</dd></div>
                  <div><dt className="inline">Threshold </dt><dd className="inline font-mono-data text-foreground">{item.threshold || '—'}</dd></div>
                  <div><dt className="inline">Source </dt><dd className="inline">{item.source || '—'}</dd></div>
                  <div><dt className="inline">Since </dt><dd className="inline font-mono-data">{item.since || '—'}</dd></div>
                  <div><dt className="inline">Target </dt><dd className="inline font-mono-data">{item.target || '—'}</dd></div>
                </dl>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
