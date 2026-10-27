import React from 'react';
import Icon from '@/components/ui/AppIcon';
import EmptyState from '@/components/ui/EmptyState';
import { Skeleton } from '@/components/ui/Skeleton';
import type { IssueItem } from '@/lib/types';

const SEV = {
  critical: { icon: 'XCircleIcon', label: 'Critical', wrap: 'border-destructive/30 bg-destructive/5', text: 'text-destructive' },
  warning: { icon: 'ExclamationTriangleIcon', label: 'Warning', wrap: 'border-warning/40 bg-warning/10', text: 'text-warning-foreground' },
  info: { icon: 'InformationCircleIcon', label: 'Info', wrap: 'border-info/30 bg-info/5', text: 'text-info' },
} as const;

export default function IssuesPanel({ issues }: { issues: IssueItem[] | null }) {
  return (
    <section className="h-full rounded-lg border border-border bg-background shadow-card" aria-labelledby="issues-title">
      <header className="flex items-center justify-between border-b border-border px-4 py-2.5">
        <h2 id="issues-title" className="text-base font-semibold">What is wrong</h2>
        {issues && (
          <span className="rounded-full bg-muted px-2 py-0.5 text-xs font-medium tabular text-muted-foreground">{issues.length} open</span>
        )}
      </header>
      <div className="p-3">
        {issues === null ? (
          <div className="space-y-2">
            <Skeleton className="h-16 w-full" />
            <Skeleton className="h-16 w-full" />
          </div>
        ) : issues.length === 0 ? (
          <EmptyState icon="CheckBadgeIcon" title="Nothing is wrong" description="No open issues on this device. Ports, power and telemetry are all within thresholds." />
        ) : (
          <ul className="space-y-1.5">
            {issues.map((i) => {
              const s = SEV[i.severity];
              return (
                <li key={i.id} className={`flex gap-3 rounded-md border p-2.5 ${s.wrap}`}>
                  <Icon name={s.icon} size={20} variant="solid" className={`mt-0.5 shrink-0 ${s.text}`} />
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
                      <p className="text-sm font-semibold">{i.title}</p>
                      <span className={`label-caps ${s.text}`}>{s.label}</span>
                    </div>
                    <p className="mt-0.5 text-sm text-muted-foreground">{i.detail}</p>
                    <p className="mt-1 flex flex-wrap items-center gap-x-3 text-xs text-muted-foreground">
                      <span className="font-mono-data">{i.target}</span>
                      <span>since {i.since}</span>
                    </p>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </section>
  );
}