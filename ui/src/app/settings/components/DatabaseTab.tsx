import React from 'react';
import Icon from '@/components/ui/AppIcon';
import Badge from '@/components/ui/Badge';
import { DB_TABLES } from '@/lib/mockData';

const CONN = [
  { label: 'Engine', value: 'PostgreSQL 16.4 (time-series extension)' },
  { label: 'Host', value: 'db-primary.insight.internal:5432' },
  { label: 'Database', value: 'insightengine' },
  { label: 'Replica lag', value: '0.4 s' },
  { label: 'Connections', value: '38 of 200 in use' },
  { label: 'Retention', value: 'Raw samples 35 days · rollups 13 months' },
];

export default function DatabaseTab() {
  return (
    <div className="space-y-5">
      <div role="note" className="flex items-start gap-3 rounded-lg border border-info/30 bg-info/5 px-4 py-3 text-sm">
        <Icon name="LockClosedIcon" size={18} variant="solid" className="mt-0.5 shrink-0 text-info" />
        <p>
          <span className="font-semibold">Read-only view.</span> This tab shows connection facts and table statistics. Credentials, schema changes and queries are not available from the UI.
        </p>
      </div>

      <section className="rounded-none border-x-0 border-y border-border bg-card shadow-card" aria-labelledby="conn-title">
        <header className="flex items-center justify-between border-b border-border px-5 py-3">
          <h2 id="conn-title" className="text-base font-semibold">Connection</h2>
          <Badge tone="success" icon="CheckCircleIcon">Connected</Badge>
        </header>
        <dl className="grid grid-cols-1 gap-x-8 gap-y-4 p-5 sm:grid-cols-2 xl:grid-cols-3">
          {CONN?.map((c) => (
            <div key={c?.label}>
              <dt className="label-caps text-muted-foreground">{c?.label}</dt>
              <dd className="mt-0.5 font-mono-data text-sm">{c?.value}</dd>
            </div>
          ))}
        </dl>
      </section>

      <section className="rounded-none border-x-0 border-y border-border bg-card shadow-card" aria-labelledby="tables-title">
        <header className="border-b border-border px-5 py-3">
          <h2 id="tables-title" className="text-base font-semibold">Tables</h2>
          <p className="text-xs text-muted-foreground">Row counts and on-disk size, refreshed every minute.</p>
        </header>
        <div className="scroll-thin overflow-x-auto">
          <table className="w-full min-w-[620px] text-sm">
            <thead>
              <tr className="border-b border-border bg-muted/60 text-left text-xs uppercase tracking-wide text-muted-foreground">
                <th scope="col" className="px-5 py-2.5">Table</th>
                <th scope="col" className="px-3 py-2.5 text-right">Rows</th>
                <th scope="col" className="px-3 py-2.5 text-right">Size</th>
                <th scope="col" className="px-3 py-2.5">Last write (UTC)</th>
                <th scope="col" className="px-3 py-2.5">Access</th>
              </tr>
            </thead>
            <tbody>
              {DB_TABLES?.map((t) => (
                <tr key={t?.name} className="border-b border-border even:bg-muted/20 hover:bg-accent/10">
                  <td className="px-5 py-2.5 font-mono-data font-semibold">{t?.name}</td>
                  <td className="px-3 py-2.5 text-right font-mono-data text-xs tabular">{t?.rows?.toLocaleString('en-US')}</td>
                  <td className="px-3 py-2.5 text-right font-mono-data text-xs tabular">{t?.size}</td>
                  <td className="px-3 py-2.5 font-mono-data text-xs text-muted-foreground">{t?.updated}</td>
                  <td className="px-3 py-2.5">
                    <Badge tone="neutral" icon="LockClosedIcon">Read-only</Badge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}