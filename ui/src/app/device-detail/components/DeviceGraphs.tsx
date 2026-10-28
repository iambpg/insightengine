'use client';

import React from 'react';
import dynamic from 'next/dynamic';
import GraphPanel from '@/components/charts/GraphPanel';
import { Skeleton } from '@/components/ui/Skeleton';
import { api } from '@/lib/apiClient';
import { isMockMode } from '@/lib/apiMode';

const TopPortsPanel = dynamic(() => import('./TopPortsPanel'), {
  ssr: false,
  loading: () => <Skeleton className="h-72 w-full" />,
});

type Rec = Record<string, number | string | null>[];

export default function DeviceGraphs({ deviceId }: { deviceId: string }) {
  const throughputId = (seed: number) => (isMockMode() ? seed : deviceId);
  const resourceId = isMockMode() ? 5 : deviceId;
  return (
    <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
      <GraphPanel
        id="agg-throughput"
        title="Aggregate throughput"
        subtitle="All uplinks combined, Mbps"
        unit="Mbps"
        kind="area"
        series={[
          { key: 'inBps', label: 'Inbound', color: 'var(--teal)' },
          { key: 'outBps', label: 'Outbound', color: 'var(--cyan)' },
        ]}
        deps={deviceId}
        fetcher={async (r, c) => (await api.getThroughput(r, throughputId(11), c)) as unknown as Rec}
      />
      <GraphPanel
        id="err-rate"
        title="Errors and discards"
        subtitle="Frames per minute across all ports"
        unit="err/min"
        kind="line"
        series={[{ key: 'errors', label: 'Errors', color: 'var(--destructive)' }]}
        deps={deviceId}
        fetcher={async (r, c) => (await api.getThroughput(r, throughputId(29), c)) as unknown as Rec}
      />
      <TopPortsPanel deviceId={deviceId} />
      <GraphPanel
        id="resources"
        title="CPU, memory and temperature"
        subtitle="Control plane load and chassis temperature"
        unit=""
        kind="line"
        series={[
          { key: 'cpu', label: 'CPU %', color: 'var(--primary)' },
          { key: 'mem', label: 'Memory %', color: 'var(--info)' },
          { key: 'temp', label: 'Temp °C', color: 'var(--warning)' },
        ]}
        yMax={100}
        deps={deviceId}
        fetcher={async (r) => (await api.getResources(r, resourceId)) as unknown as Rec}
      />
    </div>
  );
}