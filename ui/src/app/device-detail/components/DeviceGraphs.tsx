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

export default function DeviceGraphs({ deviceId, profile }: { deviceId: string; profile?: string }) {
  const throughputId = (seed: number) => (isMockMode() ? seed : deviceId);
  const resourceId = isMockMode() ? 5 : deviceId;
  return (
    <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
      <GraphPanel
        id="agg-throughput"
        title="Aggregate throughput"
        subtitle="Traffic in and out of the uplinks, in megabits per second."
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
        subtitle="Input errors and discarded frames per minute, across every port."
        unit="/min"
        kind="line"
        series={[
          { key: 'errors', label: 'Errors', color: 'var(--destructive)' },
          { key: 'discards', label: 'Discards', color: 'var(--warning)' },
        ]}
        deps={deviceId}
        fetcher={async (r, c) => (await api.getThroughput(r, throughputId(29), c)) as unknown as Rec}
      />
      <TopPortsPanel deviceId={deviceId} />
      <GraphPanel
        id="resources"
        title={profile === 'ios-basic' ? 'CPU and memory' : 'CPU, memory and temperature'}
        subtitle={profile === 'ios-basic' ? 'Control-plane CPU and memory in use, as a percent of the device.' : 'Control-plane CPU and memory as a percent. Temperature is degrees Celsius on the same scale.'}
        unit={profile === 'ios-basic' ? '%' : ''}
        kind="line"
        series={profile === 'ios-basic'
          ? [
              { key: 'cpu', label: 'CPU', color: 'var(--primary)' },
              { key: 'mem', label: 'Memory', color: 'var(--info)' },
            ]
          : [
              { key: 'cpu', label: 'CPU %', color: 'var(--primary)' },
              { key: 'mem', label: 'Memory %', color: 'var(--info)' },
              { key: 'temp', label: 'Temp °C', color: 'var(--warning)' },
            ]}
        yMax={100}
        deps={deviceId}
        fetcher={async (r, c) => (await api.getResources(r, resourceId, c)) as unknown as Rec}
      />
    </div>
  );
}