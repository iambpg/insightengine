import React from 'react';
import Icon from '@/components/ui/AppIcon';
import { Skeleton } from '@/components/ui/Skeleton';
import type { HealthCheck } from '@/lib/types';

const RES = {
  pass: { icon: 'CheckCircleIcon', label: 'Pass', cls: 'text-success' },
  warn: { icon: 'ExclamationTriangleIcon', label: 'Warn', cls: 'text-warning' },
  fail: { icon: 'XCircleIcon', label: 'Fail', cls: 'text-destructive' },
} as const;

export default function HealthChecks({ checks, runAt, running }: { checks: HealthCheck[] | null; runAt: string; running: boolean }) {
  const pass = checks?.filter((c) => c.result === 'pass').length ?? 0;
  const total = checks?.length ?? 0;
  return (
    <section className="h-full overflow-hidden rounded-lg border border-border bg-background shadow-card" aria-labelledby="hc-title">
      <header className="flex items-center justify-between border-b border-border px-4 py-2.5">
        <div>
          <h2 id="hc-title" className="text-base font-semibold">Automatic health check</h2>
          <p className="font-mono-data text-xs text-muted-foreground">{runAt ? `Last run ${runAt} UTC` : 'Running…'}</p>
        </div>
        {checks && (
          <span className={`rounded-full px-2.5 py-0.5 text-xs font-bold tabular ${pass === total ? 'bg-success/10 text-success' : 'bg-warning/15 text-foreground'}`}>
            {pass}/{total} passed
          </span>
        )}
      </header>
      <ul className={`divide-y divide-border transition-opacity ${running ? 'opacity-50' : ''}`}>
        {checks === null
          ? Array.from({ length: 5 }, (_, i) => (
              <li key={`hc-skel-${i + 1}`} className="px-4 py-2"><Skeleton className="h-4 w-full" /></li>
            ))
          : checks.map((c) => {
              const r = RES[c.result];
              return (
                <li key={c.id} className="flex items-start gap-3 px-4 py-2">
                  <Icon name={r.icon} size={18} variant="solid" className={`mt-0.5 shrink-0 ${r.cls}`} />
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium">{c.name}</p>
                    <p className="text-xs text-muted-foreground">{c.detail}</p>
                  </div>
                  <span className={`label-caps mt-1 ${r.cls}`}>{r.label}</span>
                </li>
              );
            })}
      </ul>
    </section>
  );
}