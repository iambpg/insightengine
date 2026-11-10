'use client';

import React, { useState } from 'react';
import CollapsiblePanel from '@/components/ui/CollapsiblePanel';
import { portNameLine } from '@/components/faceplate/portText';
import { namesMatch } from '@/components/faceplate/library/ifname';
import type { DeviceHealth, HealthCause, PortInfo } from '@/lib/types';

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

const SOURCE_LABEL: Record<string, string> = {
  prometheus: 'Prometheus',
  alertmanager: 'Alertmanager',
  telegraf: 'the wireless controller',
};

function badgeLine(effect?: HealthCause['effect']): string {
  if (effect === 'unreachable') return 'The device is unreachable because of this.';
  if (effect === 'critical') return 'The device health is critical because of this.';
  if (effect === 'warning') return 'The device health is a warning because of this.';
  if (effect === 'healthy') return 'The device health stays healthy.';
  return '';
}

/** Plain explanation of why this item is on the list. */
export function causeCopy(item: HealthCause): string {
  const lead = (item.detail || item.title || '').trim();
  const sentence = lead.endsWith('.') ? lead : `${lead}.`;
  const reading = `The reading is ${item.value || '—'} and the threshold is ${item.threshold || '—'}.`;
  const source = SOURCE_LABEL[item.source] || item.source || 'the device';
  const since = item.since && item.since !== '—' ? `, since ${item.since}` : '';
  const from = `This comes from ${source}${since}.`;
  return [sentence, reading, from, badgeLine(item.effect)].filter(Boolean).join(' ');
}

function portFor(item: HealthCause, ports: PortInfo[]): PortInfo | undefined {
  const target = (item.target || '').trim();
  if (!target) return undefined;
  return ports.find((port) => namesMatch(port.name, target) || (port.names || []).some((name) => namesMatch(name, target)));
}

export default function HealthCauses({
  items,
  health,
  filter,
  onFilter,
  ports,
  onSelectPort,
}: {
  items: HealthCause[] | null;
  health: DeviceHealth;
  filter: HealthFilter;
  onFilter: (next: HealthFilter) => void;
  ports?: PortInfo[];
  onSelectPort?: (port: PortInfo) => void;
}) {
  const [open, setOpen] = useState(true);
  const [openId, setOpenId] = useState<string | null>(null);
  const rows = items ?? [];
  const visible = filter === 'all' ? rows : rows.filter((item) => item.severity === filter);
  return (
    <CollapsiblePanel
      title="What is wrong"
      titleId="issues-title"
      open={open}
      onOpenChange={setOpen}
      className="flex h-full min-h-0 flex-col overflow-hidden rounded-lg border border-border bg-background shadow-card outline-none"
      bodyClassName="scroll-thin min-h-0 flex-1 overflow-y-auto"
      actions={
        open ? (
          <div className="flex flex-wrap gap-1.5" role="toolbar" aria-label="Health severity">
            {CHIPS.map((chip) => {
              const count = chip.key === 'all' ? rows.length : rows.filter((item) => item.severity === chip.key).length;
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
        ) : null
      }
    >
      <div id="health" tabIndex={-1} data-health={health} className="p-3 outline-none">
        {visible.length === 0 ? (
          <p className="px-1 py-6 text-center text-sm text-muted-foreground">
            {items === null ? 'Loading…' : rows.length === 0 ? 'No issues — healthy' : `No ${filter} issues.`}
          </p>
        ) : (
          <ul className="space-y-1.5">
            {visible.map((item) => {
              const expanded = openId === item.id;
              const port = portFor(item, ports || []);
              return (
                <li key={item.id} className={`rounded-md border ${TONE[item.severity]}`}>
                  <button
                    type="button"
                    aria-expanded={expanded}
                    onClick={() => setOpenId(expanded ? null : item.id)}
                    className="w-full px-3 py-2 text-left"
                  >
                    <div className="flex flex-wrap items-baseline justify-between gap-2">
                      <p className="text-sm font-semibold text-foreground">{item.title}</p>
                      <span className="label-caps">{item.severity}</span>
                    </div>
                    {item.detail ? <p className="mt-0.5 text-sm text-muted-foreground">{item.detail}</p> : null}
                    <p className="mt-1 font-mono-data text-xs text-foreground">
                      {item.value || '—'} <span className="text-muted-foreground">· threshold {item.threshold || '—'}</span>
                    </p>
                  </button>
                  {expanded ? (
                    <div className="border-t border-current/15 px-3 py-2">
                      <p className="label-caps text-muted-foreground">Cause</p>
                      <p className="mt-1 text-sm text-foreground">{causeCopy(item)}</p>
                      {port && onSelectPort ? (
                        <button
                          type="button"
                          onClick={() => onSelectPort(port)}
                          className="mt-2 text-sm font-semibold text-primary hover:underline"
                        >
                          Open {portNameLine(port)}
                        </button>
                      ) : null}
                    </div>
                  ) : null}
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </CollapsiblePanel>
  );
}
