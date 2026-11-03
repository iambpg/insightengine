'use client';

import React, { useState } from 'react';
import Icon from '@/components/ui/AppIcon';
import EmptyState from '@/components/ui/EmptyState';
import ExampleDataBanner from '@/components/ui/ExampleDataBanner';
import { Skeleton } from '@/components/ui/Skeleton';
import { api } from '@/lib/apiClient';
import { useKeyedLoad } from '@/lib/useKeyedLoad';
import type { ExperienceSection, ExperienceSummary } from '@/lib/liveApi';

const CARDS: { key: keyof Pick<ExperienceSummary, 'wlc' | 'sdwan' | 'vbs' | 'thirdParties'>; title: string; icon: string }[] = [
  { key: 'wlc', title: 'WLC experience', icon: 'SignalIcon' },
  { key: 'sdwan', title: 'SD-WAN tunnels', icon: 'ArrowsRightLeftIcon' },
  { key: 'vbs', title: 'VBS SLA', icon: 'ClockIcon' },
  { key: 'thirdParties', title: 'Third parties and banks', icon: 'BuildingLibraryIcon' },
];

export default function ServiceExperienceView() {
  const [attempt, setAttempt] = useState(0);
  const loaded = useKeyedLoad<ExperienceSummary>('experience', true, attempt, 'service experience', () => api.getExperience());

  if (loaded.error) {
    return (
      <div role="alert" className="flex items-center justify-between gap-3 rounded-md border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
        <span>{loaded.error}</span>
        <button type="button" onClick={() => setAttempt((n) => n + 1)} className="rounded-md border border-destructive/40 px-3 py-1 text-xs font-semibold">Retry</button>
      </div>
    );
  }

  const data = loaded.data;

  return (
    <div className="space-y-4">
      <header className="px-4 pt-2">
        <h1 className="text-xl font-semibold tracking-tight">Service Experience</h1>
        <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
          Wireless client quality, SD-WAN tunnels, IP SLA to each site VBS server, and blackbox probes for third parties and banks.
          Generated device config is paste-only. Nothing is pushed.
        </p>
      </header>
      {data?.isExampleData ? <ExampleDataBanner /> : null}
      {data?.degraded && data.degraded.length > 0 ? (
        <p className="mx-4 rounded-md border border-warning/40 bg-warning/10 px-3 py-2 text-sm">{data.degraded.join(' ')}</p>
      ) : null}
      {!data ? (
        <div className="grid gap-3 px-4 md:grid-cols-2">
          <Skeleton className="h-40" />
          <Skeleton className="h-40" />
        </div>
      ) : (
        <div className="grid gap-3 px-4 md:grid-cols-2">
          {CARDS.map((card) => (
            <Section key={card.key} title={card.title} icon={card.icon} section={data[card.key]} />
          ))}
        </div>
      )}
      <p className="px-4 pb-6 text-xs text-muted-foreground">
        Grafana dashboard <span className="font-medium">Service Experience</span> is provisioned from the same metrics.
        Setup steps are in <span className="font-mono-data">docs/service-experience.md</span>.
      </p>
    </div>
  );
}

function Section({ title, icon, section }: { title: string; icon: string; section: ExperienceSection }) {
  if (!section.configured) {
    return (
      <section className="rounded-md border border-border bg-card shadow-card">
        <EmptyState icon={icon} title={title} description={section.reason || 'not configured'} />
      </section>
    );
  }
  const rows = rowsFor(section);
  return (
    <section className="rounded-md border border-border bg-card p-4 shadow-card">
      <h2 className="flex items-center gap-2 text-sm font-semibold">
        <Icon name={icon} size={16} />
        {title}
      </h2>
      {section.note ? <p className="mt-1 text-xs text-muted-foreground">{section.note}</p> : null}
      {rows.length === 0 ? (
        <p className="mt-3 text-sm text-muted-foreground">Configured in NetBox. No samples yet.</p>
      ) : (
        <ul className="mt-3 space-y-1 text-sm">
          {rows.map((row) => (
            <li key={row.key} className="flex items-center justify-between gap-3 border-b border-border/60 py-1">
              <span className="truncate font-medium">{row.label}</span>
              <span className="font-mono-data text-xs text-muted-foreground">{row.value}</span>
            </li>
          ))}
        </ul>
      )}
      <p className="mt-3 text-xs text-muted-foreground">
        IP SLA and the telemetry subscription are on the device page, with a copy button. Nothing is pushed.
      </p>
    </section>
  );
}

function rowsFor(section: ExperienceSection): { key: string; label: string; value: string }[] {
  const radios = section.radios || [];
  if (radios.length) {
    return radios.slice(0, 8).map((row, index) => ({
      key: `r-${index}-${row.ap || ''}`,
      label: `${row.ap || 'AP'} radio ${row.radio || ''}`,
      value: row.rssi_avg ? `${row.rssi_avg} dBm` : String(row.value || ''),
    }));
  }
  const tunnels = section.tunnels || [];
  if (tunnels.length) {
    return tunnels.slice(0, 8).map((row, index) => ({
      key: `t-${index}`,
      label: `${row.local_color || '?'} → ${row.remote_color || '?'}`,
      value: row.value ? `loss ${row.value}` : '',
    }));
  }
  const sites = section.sites || [];
  if (sites.length) {
    return sites.slice(0, 8).map((row, index) => ({
      key: `s-${index}`,
      label: String(row.name || 'site'),
      value: String(row.vbsServerIp || ''),
    }));
  }
  const targets = section.targets || [];
  if (targets.length) {
    return targets.slice(0, 8).map((row, index) => ({
      key: `p-${index}`,
      label: String(row.name || 'target'),
      value: `${row.kind || ''} ${row.probe || ''}`.trim(),
    }));
  }
  const controllers = section.controllers || section.routers || [];
  return controllers.slice(0, 8).map((row, index) => ({
    key: `c-${index}`,
    label: String(row.name || ''),
    value: String(row.transport || row.platform || ''),
  }));
}
