'use client';

import React, { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import Icon from '@/components/ui/AppIcon';
import EmptyState from '@/components/ui/EmptyState';
import { HealthBadge } from '@/components/ui/Badge';
import { Skeleton } from '@/components/ui/Skeleton';
import Faceplate from '@/components/faceplate/Faceplate';
import { api } from '@/lib/apiClient';
import { devicePath } from '@/lib/apiMode';
import { buildFaceplateFor } from '@/lib/mockData';
import type { DeviceRow, SiteRow } from '@/lib/types';

export default function SiteDetail({ site }: { site: SiteRow | null }) {
  const [devices, setDevices] = useState<DeviceRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!site) return;
    let cancelled = false;
    setDevices(null);
    setError(null);
    api
      .listSiteDevices(site.id)
      .then((d) => !cancelled && setDevices(d))
      .catch(() => !cancelled && setError('Failed to load devices for this site.'));
    return () => {
      cancelled = true;
    };
  }, [site]);

  const counts = useMemo(() => {
    const c = { healthy: 0, warning: 0, critical: 0, unreachable: 0 };
    devices?.forEach((d) => {
      c[d.health] += 1;
    });
    return c;
  }, [devices]);

  if (!site) {
    return (
      <section className="rounded-none border-x-0 border-y border-border bg-card shadow-card">
        <EmptyState icon="BuildingOffice2Icon" title="Pick a site" description="Choose a site on the left to see its switches drawn as faceplates with live port state." />
      </section>
    );
  }

  return (
    <section className="space-y-4" aria-label={`Devices at ${site.name}`}>
      <header className="rounded-none border-x-0 border-y border-border bg-card p-5 shadow-card">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="label-caps text-muted-foreground">{site.region}</p>
            <h2 className="mt-0.5 text-xl font-semibold">{site.name}</h2>
            <p className="mt-1 text-xs text-muted-foreground">Last discovery run <span className="font-mono-data text-foreground">{site.lastDiscovery}</span></p>
          </div>
          <HealthBadge health={site.health} />
        </div>
        <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
          <MiniStat label="Healthy" value={counts.healthy} tone="success" icon="CheckCircleIcon" />
          <MiniStat label="Warning" value={counts.warning} tone="warning" icon="ExclamationTriangleIcon" />
          <MiniStat label="Critical" value={counts.critical} tone="destructive" icon="XCircleIcon" />
          <MiniStat label="Unreachable" value={counts.unreachable} tone="neutral" icon="SignalSlashIcon" />
        </div>
      </header>

      {error ? (
        <div role="alert" className="rounded-md border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">{error}</div>
      ) : devices === null ? (
        <div className="space-y-3">
          {Array.from({ length: 3 }, (_, i) => (
            <Skeleton key={`sd-skel-${i + 1}`} className="h-36 w-full" />
          ))}
        </div>
      ) : (
        <ul className="grid grid-cols-1 gap-3 2xl:grid-cols-2">
          {devices.map((d) => (
            <li key={d.id} className="rounded-lg border border-border bg-card p-4 shadow-card transition-all duration-150 hover:-translate-y-0.5 hover:shadow-pop">
              <div className="mb-3 flex items-center justify-between gap-3">
                <div className="min-w-0">
                  <Link href={devicePath(d.id, d.formFactor)} className="block truncate font-mono-data text-sm font-semibold hover:text-primary hover:underline">{d.hostname}</Link>
                  <p className="text-xs text-muted-foreground">{d.role} · <span className="font-mono-data">{d.mgmtIp}</span></p>
                </div>
                <HealthBadge health={d.health} />
              </div>
              <div className="rounded-md bg-gradient-to-b from-secondary to-background p-2">
                <Faceplate device={buildFaceplateFor(d.formFactor)} compact />
              </div>
              <div className="mt-2 flex items-center justify-between text-xs text-muted-foreground">
                <span className="font-mono-data tabular">{d.portsUp}/{d.portsTotal} ports up</span>
                <span className={d.portsFault > 0 ? 'font-semibold text-destructive' : ''}>{d.portsFault > 0 ? `✕ ${d.portsFault} faulted` : `polled ${d.lastPoll}`}</span>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

const TONE = {
  success: 'bg-success/10 text-success',
  warning: 'bg-warning/15 text-foreground',
  destructive: 'bg-destructive/10 text-destructive',
  neutral: 'bg-muted text-muted-foreground',
} as const;

function MiniStat({ label, value, tone, icon }: { label: string; value: number; tone: keyof typeof TONE; icon: string }) {
  return (
    <div className={`flex items-center gap-3 rounded-md px-3 py-2 ${TONE[tone]}`}>
      <Icon name={icon} size={18} variant="solid" />
      <div>
        <p className="text-xl font-bold leading-none tabular">{value}</p>
        <p className="mt-0.5 text-[11px] font-medium">{label}</p>
      </div>
    </div>
  );
}