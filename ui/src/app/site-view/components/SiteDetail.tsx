'use client';

import React, { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import EmptyState from '@/components/ui/EmptyState';
import { HealthBadge } from '@/components/ui/Badge';
import { Skeleton } from '@/components/ui/Skeleton';
import { api } from '@/lib/apiClient';
import { reportLoadError } from '@/lib/loadError';
import { devicePath } from '@/lib/apiMode';
import type { AlertItem, DeviceRow, SiteRow } from '@/lib/types';
import { describeSite, type LaneState, type ProblemView } from './siteCondition';
import SiteActivity from './SiteActivity';
import SiteSla from './SiteSla';
import InspectNote from '@/components/ui/InspectNote';
import type { SiteBriefing } from '@/lib/types';

const STATE_TONE: Record<LaneState, string> = {
  working: 'bg-success/10 text-success',
  attention: 'bg-warning/15 text-foreground',
  down: 'bg-destructive/10 text-destructive',
  absent: 'bg-muted text-muted-foreground',
};

export default function SiteDetail({ site, loading = false }: { site: SiteRow | null; loading?: boolean }) {
  const [devices, setDevices] = useState<DeviceRow[] | null>(null);
  const [alerts, setAlerts] = useState<AlertItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [alertsError, setAlertsError] = useState<string | null>(null);
  const [briefing, setBriefing] = useState<SiteBriefing | null>(null);
  const [briefingError, setBriefingError] = useState<string | null>(null);
  const [briefingLoading, setBriefingLoading] = useState(true);
  const [briefingUpdated, setBriefingUpdated] = useState<Date | null>(null);

  useEffect(() => {
    if (!site) return undefined;
    let cancelled = false;
    const load = (first: boolean) => {
      if (first) {
        setDevices(null);
        setAlerts(null);
        setBriefing(null);
        setError(null);
        setAlertsError(null);
        setBriefingError(null);
        setBriefingLoading(true);
      }
      api
        .listSiteDevices(site.id)
        .then((rows) => {
          if (!cancelled) setDevices(rows);
        })
        .catch((cause) => {
          if (!cancelled) setError(reportLoadError(cause, 'devices for this site'));
        });
      api
        .listAlerts()
        .then((rows) => {
          if (!cancelled) setAlerts(rows);
        })
        .catch((cause) => {
          if (!cancelled) setAlertsError(reportLoadError(cause, 'alerts for this site'));
        });
      api
        .getSiteBriefing(site.id, 'custom', 240)
        .then((body) => {
          if (cancelled) return;
          setBriefing(body);
          setBriefingError(null);
          setBriefingUpdated(new Date());
        })
        .catch((cause) => {
          if (!cancelled) setBriefingError(reportLoadError(cause, 'the site account'));
        })
        .finally(() => {
          if (!cancelled && first) setBriefingLoading(false);
        });
    };
    load(true);
    const timer = window.setInterval(() => load(false), 30_000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [site]);

  const story = useMemo(
    () => (site && devices ? describeSite(site, devices, alerts ?? []) : null),
    [site, devices, alerts],
  );

  if (!site) {
    if (loading) {
      return (
        <section role="status" className="rounded-none border-x-0 border-y border-border bg-card p-5 shadow-card">
          <p className="sr-only">Loading site</p>
          <Skeleton className="h-36 w-full" />
        </section>
      );
    }
    return (
      <section className="rounded-none border-x-0 border-y border-border bg-card shadow-card">
        <EmptyState icon="BuildingOffice2Icon" title="Pick a site" description="Choose a site on the left to see whether it is working and what is wrong." />
      </section>
    );
  }

  return (
    <section className="space-y-4" aria-label={`Condition of ${site.name}`}>
      <header className="rounded-none border-x-0 border-y border-border bg-card p-5 shadow-card">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-xl font-semibold">{site.name}</h2>
            {story ? (
              <>
                <h3 className="mt-1 text-base font-semibold">{story.verdict.heading}</h3>
                <p className="mt-1 max-w-3xl text-sm text-muted-foreground">{story.verdict.detail}</p>
              </>
            ) : null}
          </div>
          {site.deviceCount > 0 ? <HealthBadge health={site.health} /> : null}
        </div>
        <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-6">
          <Fact label="Region" value={site.region || '—'} />
          <Fact label="Description" value={site.description || 'No description recorded'} />
          <Fact label="Address" value={site.address || 'No address recorded'} />
          <Fact label="Devices" value={String(site.deviceCount)} />
          <Fact label="Last discovery" value={site.lastDiscovery || '—'} />
          <MapPin site={site} />
        </div>
      </header>

      {error ? (
        <div role="alert" className="rounded-md border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">{error}</div>
      ) : story === null ? (
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
          {Array.from({ length: 3 }, (_, i) => (
            <Skeleton key={`site-panel-${i + 1}`} className="h-36 w-full" />
          ))}
        </div>
      ) : (
        <>
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
            {story.lanes.map((lane) => (
              <article key={lane.id} className="rounded-md border border-border bg-card p-4 shadow-card" aria-label={lane.title}>
                <div className="flex items-start justify-between gap-3">
                  <h3 className="text-sm font-semibold">{lane.title}</h3>
                  {lane.notes.length > 0 ? (
                    <InspectNote
                      label={`${lane.title} ${lane.status}`}
                      title={lane.title}
                      tone={lane.state === 'down' ? 'critical' : 'warning'}
                      items={lane.notes}
                    >
                      <span className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-medium ${STATE_TONE[lane.state]}`}>{lane.status}</span>
                    </InspectNote>
                  ) : (
                    <span className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-medium ${STATE_TONE[lane.state]}`}>{lane.status}</span>
                  )}
                </div>
                <p className="mt-3 text-sm leading-6 text-muted-foreground">{lane.detail}</p>
              </article>
            ))}
          </div>

          <SiteSla siteId={site.id} />

          <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
            <article className="rounded-md border border-border bg-card p-4 shadow-card" aria-label="What's wrong">
              <h3 className="text-sm font-semibold">What&apos;s wrong</h3>
              {alertsError ? <p className="mt-2 text-sm text-destructive">{alertsError}</p> : null}
              {story.problems.length === 0 ? (
                <p className="mt-3 text-sm text-muted-foreground">Nothing is wrong in the readings for this site.</p>
              ) : (
                <ul className="mt-3 space-y-3">
                  {story.problems.map((problem) => (
                    <ProblemRow key={problem.id} problem={problem} />
                  ))}
                </ul>
              )}
            </article>

            <SiteActivity data={briefing} error={briefingError} loading={briefingLoading} updated={briefingUpdated} />
          </div>
        </>
      )}
    </section>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex h-[4.75rem] flex-col justify-between overflow-hidden rounded-md border border-border bg-muted/30 px-3 py-2">
      <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className="line-clamp-2 text-sm leading-5 text-foreground">{value}</p>
    </div>
  );
}

function MapPin({ site }: { site: SiteRow }) {
  const query = site.latitude != null && site.longitude != null
    ? `${site.latitude},${site.longitude}`
    : [site.address, site.city, site.region].filter(Boolean).join(', ');
  const href = site.address || (site.latitude != null && site.longitude != null)
    ? `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(query)}`
    : '';
  const body = (
    <>
      <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">Map</p>
      <p className="flex items-center gap-1.5 text-sm leading-5">
        <svg viewBox="0 0 24 24" className="h-4 w-4 shrink-0" aria-hidden="true" fill="currentColor">
          <path d="M12 2a7 7 0 0 0-7 7c0 5.25 7 13 7 13s7-7.75 7-13a7 7 0 0 0-7-7zm0 9.5a2.5 2.5 0 1 1 0-5 2.5 2.5 0 0 1 0 5z" />
        </svg>
        {href ? 'Open in Google Maps' : 'No address to pin'}
      </p>
    </>
  );
  const className = 'flex h-[4.75rem] flex-col justify-between overflow-hidden rounded-md border border-border bg-muted/30 px-3 py-2';
  if (!href) return <div className={className}>{body}</div>;
  return (
    <a href={href} target="_blank" rel="noreferrer" className={`${className} hover:border-primary hover:text-primary`} aria-label={`Open ${site.name} on Google Maps`}>
      {body}
    </a>
  );
}

function ProblemRow({ problem }: { problem: ProblemView }) {
  return (
    <li className="border-b border-border/70 pb-3 last:border-0 last:pb-0">
      <InspectNote
        label={problem.title}
        tone={problem.id.startsWith('unreachable') || problem.id.startsWith('health') ? 'critical' : 'warning'}
        items={problem.devices.length > 0
          ? problem.devices.map((device) => ({
            title: device.hostname,
            detail: problem.detail,
            href: devicePath(device.id, device.formFactor),
          }))
          : [{ title: problem.title, detail: problem.detail }]}
      />
      {problem.detail ? <p className="mt-0.5 text-xs text-muted-foreground">{problem.detail}</p> : null}
      {problem.devices.length > 0 ? (
        <p className="mt-1 flex flex-wrap gap-x-3 gap-y-1">
          {problem.devices.map((device) => (
            <Link key={device.id} href={devicePath(device.id, device.formFactor)} className="font-mono-data text-xs font-semibold hover:text-primary hover:underline">
              {device.hostname}
            </Link>
          ))}
        </p>
      ) : null}
    </li>
  );
}
