'use client';

import React, { useEffect, useState } from 'react';
import RangeSelector from '@/components/charts/RangeSelector';
import TopPortsChart from '@/components/charts/TopPortsChart';
import CollapsiblePanel from '@/components/ui/CollapsiblePanel';
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
    <CollapsiblePanel
      title="Top ports by peak utilisation"
      titleId="topports-title"
      subtitle="Peak % of link speed in the selected window"
      headingLevel="h3"
      className="rounded-none border-x-0 border-y border-border bg-card shadow-card"
      bodyClassName="p-4 pt-0"
    >
      <div className="mb-3 flex justify-end">
        <RangeSelector value={range} onChange={setRange} customMin={customMin} onCustomMin={setCustomMin} label="Top ports" />
      </div>
      {data ? <TopPortsChart data={data} /> : <Skeleton className="h-60 w-full" />}
      <p className="mt-1 text-[11px] text-muted-foreground">Red above 85%, amber above 65%.</p>
    </CollapsiblePanel>
  );
}
