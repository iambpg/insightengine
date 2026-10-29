'use client';

import React, { useEffect, useState } from 'react';
import dynamic from 'next/dynamic';
import RangeSelector from '@/components/charts/RangeSelector';
import { Skeleton } from '@/components/ui/Skeleton';
import Icon from '@/components/ui/AppIcon';
import type { RangeKey } from '@/lib/mockData';
import { reportLoadError } from '@/lib/loadError';
import type { SeriesDef } from '@/components/charts/ZoomableChart';

const ZoomableChart = dynamic(() => import('@/components/charts/ZoomableChart'), {
  ssr: false,
  loading: () => <Skeleton className="h-[220px] w-full" />,
});

interface Props {
  id: string;
  title: string;
  subtitle: string;
  unit: string;
  kind: 'area' | 'line' | 'bar';
  series: SeriesDef[];
  yMax?: number;
  fetcher: (range: RangeKey, customMin: number) => Promise<Record<string, number | string | null>[]>;
  deps?: string;
  height?: number;
}

// Every graph panel owns its own time-range selector and zoom state.
export default function GraphPanel({ id, title, subtitle, unit, kind, series, yMax, fetcher, deps = '', height = 220 }: Props) {
  const [range, setRange] = useState<RangeKey>('24h');
  const [customMin, setCustomMin] = useState(180);
  const [data, setData] = useState<Record<string, number | string | null>[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setData(null);
    setError(null);
    fetcher(range, customMin)
      .then((d) => !cancelled && setData(d))
      .catch((cause) => !cancelled && setError(reportLoadError(cause, title.toLowerCase())));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [range, customMin, deps, tick]);

  const hasGap = data?.some((d) => series.every((s) => d[s.key] === null));

  return (
    <section className="rounded-lg border border-border bg-card p-4 shadow-card" aria-labelledby={`${id}-title`}>
      <header className="mb-3 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 id={`${id}-title`} className="text-sm font-semibold">{title}</h3>
          <p className="text-xs text-muted-foreground">{subtitle}</p>
        </div>
        <RangeSelector value={range} onChange={setRange} customMin={customMin} onCustomMin={setCustomMin} label={title} />
      </header>
      <div className="mt-1">
        {error ? (
          <div role="alert" className="flex items-center justify-between gap-3 rounded-md border border-destructive/30 bg-destructive/10 px-3 py-3 text-sm text-destructive">
            <span className="flex items-center gap-2"><Icon name="ExclamationCircleIcon" size={16} />{error}</span>
            <button type="button" onClick={() => setTick((t) => t + 1)} className="rounded-md border border-destructive/40 px-2 py-1 text-xs font-medium hover:bg-destructive/10">Retry</button>
          </div>
        ) : data === null ? (
          <Skeleton className="w-full" />
        ) : (
          <ZoomableChart data={data} series={series} kind={kind} unit={unit} yMax={yMax} gradientId={`${id}-grad`} height={height} />
        )}
      </div>
      {hasGap && (
        <p className="mt-1 flex items-center gap-1.5 text-[11px] text-warning-foreground">
          <Icon name="ExclamationTriangleIcon" size={12} /> Gap in the series: telemetry was not received for a short period.
        </p>
      )}
    </section>
  );
}