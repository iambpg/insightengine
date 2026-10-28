'use client';

import React, { useEffect, useState } from 'react';
import RangeSelector from '@/components/charts/RangeSelector';
import TopPortsChart from '@/components/charts/TopPortsChart';
import { Skeleton } from '@/components/ui/Skeleton';
import { api } from '@/lib/apiClient';
import { isMockMode } from '@/lib/apiMode';
import type { RangeKey } from '@/lib/mockData';

// Top ports by utilisation. Bars do not support time zoom, but the panel still owns its own range selector.
export default function TopPortsPanel({ deviceId }: { deviceId: string }) {
  const [range, setRange] = useState<RangeKey>('24h');
  const [customMin, setCustomMin] = useState(180);
  const [data, setData] = useState<{ name: string; util: number }[] | null>(null);

  useEffect(() => {
    setData(null);
    const seed = isMockMode()
      ? { '1h': 1, '6h': 2, '24h': 3, '7d': 4, custom: 5 }[range] + customMin
      : deviceId;
    api.getTopPorts(seed, range, customMin).then(setData);
  }, [range, customMin, deviceId]);

  return (
    <section className="rounded-none border-x-0 border-y border-border bg-card p-4 shadow-card" aria-labelledby="topports-title">
      <header className="mb-1 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 id="topports-title" className="text-sm font-semibold">Top ports by peak utilisation</h3>
          <p className="text-xs text-muted-foreground">Peak % of link speed in the selected window</p>
        </div>
        <RangeSelector value={range} onChange={setRange} customMin={customMin} onCustomMin={setCustomMin} label="Top ports" />
      </header>
      {data ? <TopPortsChart data={data} /> : <Skeleton className="h-60 w-full" />}
      <p className="mt-1 text-[11px] text-muted-foreground">Red above 85%, amber above 65%.</p>
    </section>
  );
}