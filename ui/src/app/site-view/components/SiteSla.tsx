'use client';

import React, { useEffect, useMemo, useState } from 'react';
import dynamic from 'next/dynamic';
import { Skeleton } from '@/components/ui/Skeleton';
import { api } from '@/lib/apiClient';
import { reportLoadError } from '@/lib/loadError';
import type { SeriesDef } from '@/components/charts/ZoomableChart';
import type { SiteSlaSeries } from '@/lib/types';

const ZoomableChart = dynamic(() => import('@/components/charts/ZoomableChart'), {
  ssr: false,
  loading: () => <Skeleton className="h-[180px] w-full" />,
});

const LINK_COLORS = ['#1d4ed8', '#0f766e', '#b45309', '#7c3aed', '#be123c', '#0369a1', '#65a30d', '#c2410c'];

function linkColor(index: number): string {
  return LINK_COLORS[index % LINK_COLORS.length];
}

function limitLabel(inMbps: number | null | undefined, outMbps: number | null | undefined): string {
  if (inMbps == null && outMbps == null) return 'No limiter is set';
  if (inMbps != null && outMbps != null && inMbps !== outMbps) return `${inMbps} in / ${outMbps} out Mbps`;
  return `${inMbps ?? outMbps} Mbps`;
}

const SAMPLE_MS = 5000;

function clockLabel(stamp: number): string {
  return new Date(stamp * 1000).toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  });
}

export default function SiteSla({ siteId }: { siteId: string }) {
  const [sla, setSla] = useState<SiteSlaSeries | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    let cancelled = false;
    let busy = false;
    const load = () => {
      if (busy) return;
      busy = true;
      api
        .getSiteSla(siteId)
        .then((body) => {
          if (cancelled) return;
          setSla(body);
          setError(null);
          setNow(new Date());
        })
        .catch((cause) => {
          if (!cancelled) setError(reportLoadError(cause, 'the WAN graph'));
        })
        .finally(() => {
          busy = false;
        });
    };
    load();
    const timer = window.setInterval(load, SAMPLE_MS);
    const clock = window.setInterval(() => setNow(new Date()), 1000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
      window.clearInterval(clock);
    };
  }, [siteId]);

  const links = sla?.links ?? [];
  const chart = useMemo(() => {
    const rows = new Map<number, Record<string, number | string | null>>();
    const series: SeriesDef[] = [];
    let peak = 0;
    links.forEach((link, index) => {
      const color = linkColor(index);
      const inKey = `${link.name} in`;
      const outKey = `${link.name} out`;
      series.push({ key: inKey, label: `${link.name} in`, color });
      series.push({ key: outKey, label: `${link.name} out`, color, dash: '6 3' });
      const sameLimit = link.inMbps != null && link.inMbps === link.outMbps ? link.inMbps : null;
      const limitKey = sameLimit != null ? `${link.name} limit` : '';
      if (sameLimit != null) series.push({ key: limitKey, label: `${link.name} limit`, color, dash: '2 2' });
      peak = Math.max(peak, link.inMbps ?? 0, link.outMbps ?? 0);
      for (const point of link.points) {
        const row = rows.get(point.t) ?? { label: clockLabel(point.t) };
        row[inKey] = point.inMbps;
        row[outKey] = point.outMbps;
        if (sameLimit != null) row[limitKey] = sameLimit;
        rows.set(point.t, row);
        peak = Math.max(peak, point.inMbps, point.outMbps);
      }
    });
    return {
      data: [...rows.entries()].sort((left, right) => left[0] - right[0]).map(([, row]) => row),
      series,
      yMax: peak > 0 ? Math.ceil(peak * 1.1) : undefined,
    };
  }, [links]);
  const clock = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });

  return (
    <article className="rounded-md border border-border bg-card p-4 shadow-card" aria-label="Performance SLA">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm font-semibold">Performance SLA</h3>
        <p className="font-mono-data text-xs text-muted-foreground">
          <span className="mr-2 inline-flex items-center gap-1.5 font-sans font-medium text-success">
            <span className="h-2 w-2 rounded-full bg-success" aria-hidden="true" />
            Live · {clock}
          </span>
          {links.length === 0 ? 'No limiter is set · ' : ''}
          last 3 minutes · a point every 5 seconds
        </p>
      </div>
      {error ? <p role="alert" className="mt-3 text-sm text-destructive">{error}</p> : null}
      {sla === null && !error ? (
        <Skeleton className="mt-3 h-[180px] w-full" />
      ) : chart.data.length === 0 ? (
        <p className="mt-3 text-sm text-muted-foreground">{sla?.note || 'No WAN throughput sample arrived in this window.'}</p>
      ) : (
        <div className="mt-2 flex items-stretch gap-4">
          <div className="min-w-0 flex-1">
            <ZoomableChart data={chart.data} series={chart.series} unit="Mbps" kind="line" height={180} yMax={chart.yMax} gradientId="site-wan-sla" legend={false} />
          </div>
          <aside className="w-44 shrink-0 border-l border-border pl-3" aria-label="Link colours">
            <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">Links</p>
            <ul className="mt-2 space-y-3">
              {links.map((link, index) => (
                <li key={link.name} className="flex gap-2">
                  <span className="mt-1 h-2.5 w-2.5 shrink-0 rounded-full" style={{ backgroundColor: linkColor(index) }} aria-hidden="true" />
                  <span>
                    <span className="block text-sm font-semibold text-foreground">{link.name}</span>
                    <span className="block text-[11px] text-muted-foreground">{limitLabel(link.inMbps, link.outMbps)}</span>
                  </span>
                </li>
              ))}
            </ul>
            <p className="mt-3 text-[10px] leading-4 text-muted-foreground">Solid is traffic in. Dashed is traffic out. Dotted is that link&apos;s limiter.</p>
          </aside>
        </div>
      )}
    </article>
  );
}
