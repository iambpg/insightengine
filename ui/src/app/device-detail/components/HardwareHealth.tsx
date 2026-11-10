import React from 'react';
import Icon from '@/components/ui/AppIcon';
import CollapsiblePanel from '@/components/ui/CollapsiblePanel';
import { Skeleton } from '@/components/ui/Skeleton';
import type { HardwareItem } from '@/lib/types';

const ST = {
  ok: { label: 'OK', cls: 'text-success', dot: 'bg-success' },
  warn: { label: 'Warn', cls: 'text-warning', dot: 'bg-warning' },
  fail: { label: 'Fail', cls: 'text-destructive', dot: 'bg-destructive' },
} as const;

const KIND_ICON: Record<HardwareItem['kind'], string> = {
  power: 'BoltIcon',
  fan: 'ArrowPathIcon',
  temp: 'FireIcon',
  cpu: 'CpuChipIcon',
  memory: 'CircleStackIcon',
  storage: 'ServerIcon',
};

function hardwareSubtitle(items: HardwareItem[] | null): string {
  if (!items) return 'CPU, memory, power and cooling';
  const environment = items.some((item) => item.kind === 'power' || item.kind === 'fan' || item.kind === 'temp');
  return environment ? 'CPU, memory, power and cooling' : 'CPU and memory';
}

export default function HardwareHealth({ items }: { items: HardwareItem[] | null }) {
  const ok = items?.filter((i) => i.status === 'ok').length ?? 0;
  const total = items?.length ?? 0;
  return (
    <CollapsiblePanel
      title="Hardware health"
      titleId="hw-title"
      subtitle={hardwareSubtitle(items)}
      className="flex h-full min-h-0 flex-col overflow-hidden rounded-lg border border-border bg-background shadow-card"
      bodyClassName="scroll-thin min-h-0 flex-1 overflow-y-auto"
      meta={
        items ? (
          <span className={`rounded-full px-2.5 py-0.5 text-xs font-bold tabular ${ok === total ? 'bg-success/10 text-success' : 'bg-warning/15 text-foreground'}`}>
            {ok}/{total} OK
          </span>
        ) : null
      }
    >
      <ul className="divide-y divide-border">
        {items === null
          ? Array.from({ length: 6 }, (_, i) => (
              <li key={`hw-skel-${i + 1}`} className="px-4 py-2"><Skeleton className="h-4 w-full" /></li>
            ))
          : items.map((h) => {
              const s = ST[h.status];
              return (
                <li key={h.id} className="flex items-start gap-3 px-4 py-2">
                  <Icon name={(KIND_ICON[h.kind] ?? 'CubeIcon') as any} size={18} className="mt-0.5 shrink-0 text-muted-foreground" />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center justify-between gap-2">
                      <p className="text-sm font-medium">{h.name}</p>
                      <span className="font-mono-data text-sm font-semibold tabular">{h.value}</span>
                    </div>
                    <p className="truncate text-xs text-muted-foreground" title={h.detail}>{h.detail}</p>
                  </div>
                  <span className={`label-caps mt-1 inline-flex items-center gap-1 ${s.cls}`}>
                    <span className={`h-1.5 w-1.5 rounded-full ${s.dot}`} aria-hidden="true" />
                    {s.label}
                  </span>
                </li>
              );
            })}
      </ul>
    </CollapsiblePanel>
  );
}
