'use client';

import React, { useMemo, useState } from 'react';
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceArea,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

export interface SeriesDef {
  key: string;
  label: string;
  color: string;
}

interface Props {
  data: Record<string, number | string | null>[];
  series: SeriesDef[];
  kind: 'area' | 'line' | 'bar';
  unit: string;
  height?: number;
  yMax?: number;
  gradientId: string;
  stacked?: boolean;
}

interface TipProps {
  active?: boolean;
  payload?: { name: string; value: number | null; color: string }[];
  label?: string;
  unit: string;
}

function Tip({ active, payload, label, unit }: TipProps) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg border border-border bg-card px-3 py-2 text-xs shadow-pop">
      <p className="mb-1 font-mono-data font-semibold">{label}</p>
      {payload.map((p) => (
        <p key={`tip-${p.name}`} className="flex items-center gap-2">
          <span className="inline-block h-2 w-2 rounded-full" style={{ backgroundColor: p.color }} />
          <span className="text-muted-foreground">{p.name}</span>
          <span className="ml-auto font-mono-data font-semibold">{p.value === null || p.value === undefined ? 'no data' : `${p.value} ${unit}`}</span>
        </p>
      ))}
    </div>
  );
}

// Recharts is browser-only; this file is a client component and is imported dynamically with ssr:false by its parent.
export default function ZoomableChart({ data, series, kind, unit, height = 220, yMax, gradientId, stacked }: Props) {
  const [left, setLeft] = useState<string | null>(null);
  const [right, setRight] = useState<string | null>(null);
  const [zoom, setZoom] = useState<{ from: number; to: number } | null>(null);

  const view = useMemo(() => {
    if (!zoom) return data;
    return data.slice(zoom.from, zoom.to + 1);
  }, [data, zoom]);

  const idxOf = (label: string) => data.findIndex((d) => d.label === label);

  const finish = () => {
    if (left && right && left !== right) {
      const a = idxOf(left);
      const b = idxOf(right);
      const from = Math.min(a, b);
      const to = Math.max(a, b);
      if (to - from >= 2) setZoom({ from: zoom ? zoom.from + from : from, to: zoom ? zoom.from + to : to });
    }
    setLeft(null);
    setRight(null);
  };

  const common = {
    data: view,
    margin: { top: 8, right: 8, left: -12, bottom: 0 },
    onMouseDown: (e: { activeLabel?: string | number }) => e?.activeLabel !== undefined && setLeft(String(e.activeLabel)),
    onMouseMove: (e: { activeLabel?: string | number }) => left && e?.activeLabel !== undefined && setRight(String(e.activeLabel)),
    onMouseUp: finish,
  };

  const axes = (
    <>
      <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
      <XAxis dataKey="label" tick={{ fontSize: 11, fill: 'var(--muted-foreground)' }} tickLine={false} axisLine={{ stroke: 'var(--border)' }} minTickGap={36} />
      <YAxis tick={{ fontSize: 11, fill: 'var(--muted-foreground)' }} tickLine={false} axisLine={false} domain={[0, yMax ?? 'auto']} width={44} />
      <Tooltip content={<Tip unit={unit} />} />
      <Legend iconType="circle" wrapperStyle={{ fontSize: 12 }} />
      {left && right ? <ReferenceArea x1={left} x2={right} fill="var(--accent)" fillOpacity={0.2} stroke="var(--accent)" /> : null}
    </>
  );

  return (
    <div className="relative select-none">
      {zoom && (
        <button
          type="button"
          onClick={() => setZoom(null)}
          className="absolute right-0 top-[-34px] z-10 inline-flex items-center gap-1 rounded-md border border-border bg-card px-2 py-1 text-xs font-medium text-foreground transition-all hover:bg-muted active:scale-95"
        >
          Reset zoom
        </button>
      )}
      <ResponsiveContainer width="100%" height={height}>
        {kind === 'area' ? (
          <AreaChart {...common}>
            <defs>
              {series.map((s) => (
                <linearGradient key={`${gradientId}-${s.key}`} id={`${gradientId}-${s.key}`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={s.color} stopOpacity={0.4} />
                  <stop offset="100%" stopColor={s.color} stopOpacity={0.02} />
                </linearGradient>
              ))}
            </defs>
            {axes}
            {series.map((s) => (
              <Area key={s.key} type="monotone" dataKey={s.key} name={s.label} stroke={s.color} strokeWidth={2} fill={`url(#${gradientId}-${s.key})`} connectNulls={false} stackId={stacked ? 'a' : undefined} isAnimationActive={false} />
            ))}
          </AreaChart>
        ) : kind === 'line' ? (
          <LineChart {...common}>
            {axes}
            {series.map((s) => (
              <Line key={s.key} type="monotone" dataKey={s.key} name={s.label} stroke={s.color} strokeWidth={2} dot={false} connectNulls={false} isAnimationActive={false} />
            ))}
          </LineChart>
        ) : (
          <BarChart {...common}>
            {axes}
            {series.map((s) => (
              <Bar key={s.key} dataKey={s.key} name={s.label} fill={s.color} radius={[3, 3, 0, 0]} isAnimationActive={false} />
            ))}
          </BarChart>
        )}
      </ResponsiveContainer>
      <p className="mt-1 text-[11px] text-muted-foreground">
        {zoom ? 'Zoomed view — drag again to zoom further, or reset.' : 'Drag across the chart to zoom into an area.'}
      </p>
    </div>
  );
}