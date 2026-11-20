'use client';

import React, { useMemo, useState } from 'react';
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ReferenceArea,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { epochMs, formatTick, formatWhen, timeZoneName } from '@/lib/clock';

export interface SeriesDef {
  key: string;
  label: string;
  color: string;
  dash?: string;
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
  legend?: boolean;
  /** What the lines measure, shown under the time axis. */
  subject?: string;
  /** Preset window, such as "Last 5 minutes". Hidden once the user drags a shorter stretch. */
  windowLabel?: string;
}

interface ChartPoint extends Record<string, number | string | null> {
  x: number;
}

interface ChartMouse {
  activeTooltipIndex?: number | string;
}

function pointIndex(event?: ChartMouse): number | null {
  const raw = event?.activeTooltipIndex;
  const index = typeof raw === 'number' ? raw : Number(raw);
  return Number.isInteger(index) && index >= 0 ? index : null;
}

function reading(value: number | string | null | undefined, unit: string): string {
  if (value === null || value === undefined || value === '') return 'no data';
  return unit ? `${value} ${unit}` : String(value);
}

function Tip({
  active,
  payload,
  unit,
}: {
  active?: boolean;
  payload?: { name: string; value: number | null; color: string; payload?: ChartPoint }[];
  unit: string;
}) {
  if (!active || !payload?.length) return null;
  const row = payload[0]?.payload;
  const ms = epochMs(row?.t);
  const when = ms != null ? formatWhen(ms) : String(row?.label ?? '');
  return (
    <div className="rounded-lg border border-border bg-card px-3 py-2 text-xs shadow-pop">
      <p className="mb-1 font-mono-data font-semibold">{when}</p>
      {payload.map((item) => (
        <p key={`tip-${item.name}`} className="flex items-center gap-2">
          <span className="inline-block h-2 w-2 rounded-full" style={{ backgroundColor: item.color }} />
          <span className="text-muted-foreground">{item.name}</span>
          <span className="ml-auto font-mono-data font-semibold">{reading(item.value, unit)}</span>
        </p>
      ))}
    </div>
  );
}

// Recharts is browser-only; this file is a client component and is imported dynamically with ssr:false by its parent.
export default function ZoomableChart({
  data,
  series,
  kind,
  unit,
  height = 220,
  yMax,
  gradientId,
  stacked,
  legend = true,
  subject,
  windowLabel,
}: Props) {
  const [anchor, setAnchor] = useState<number | null>(null);
  const [hover, setHover] = useState<number | null>(null);
  const [zoom, setZoom] = useState<{ from: number; to: number } | null>(null);

  const points = useMemo<ChartPoint[]>(
    () => data.map((row, index) => ({ ...row, x: epochMs(row.t) ?? index })),
    [data],
  );
  const view = useMemo(() => (zoom ? points.slice(zoom.from, zoom.to + 1) : points), [points, zoom]);
  const timed = view.some((row) => epochMs(row.t) != null);
  const span = timed && view.length > 1 ? Number(view[view.length - 1].x) - Number(view[0].x) : 0;
  const from = timed ? formatTick(Number(view[0]?.x ?? 0), span || 1) : String(view[0]?.label ?? '');
  const to = timed ? formatTick(Number(view[view.length - 1]?.x ?? 0), span || 1) : String(view[view.length - 1]?.label ?? '');
  const zone = timed ? timeZoneName(new Date(Number(view[view.length - 1]?.x ?? Date.now()))) : '';

  const finish = () => {
    if (anchor !== null && hover !== null && anchor !== hover) {
      const fromIndex = Math.min(anchor, hover);
      const toIndex = Math.max(anchor, hover);
      if (toIndex - fromIndex >= 2) {
        setZoom({
          from: zoom ? zoom.from + fromIndex : fromIndex,
          to: zoom ? zoom.from + toIndex : toIndex,
        });
      }
    }
    setAnchor(null);
    setHover(null);
  };

  const common = {
    data: view,
    margin: { top: 8, right: 12, left: 8, bottom: 0 },
    onMouseDown: (event: ChartMouse) => {
      const index = pointIndex(event);
      if (index !== null) setAnchor(index);
    },
    onMouseMove: (event: ChartMouse) => {
      if (anchor === null) return;
      const index = pointIndex(event);
      if (index !== null) setHover(index);
    },
    onMouseUp: finish,
    onMouseLeave: () => {
      if (anchor !== null) finish();
    },
  };

  const band = anchor !== null && hover !== null ? [view[anchor], view[hover]] : null;

  const axes = (
    <>
      <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
      <XAxis
        dataKey="x"
        tick={{ fontSize: 11, fill: 'var(--muted-foreground)' }}
        tickLine={false}
        axisLine={{ stroke: 'var(--border)' }}
        minTickGap={28}
        tickFormatter={(value: number) => (timed ? formatTick(Number(value), span || 1) : String(view.find((row) => row.x === value)?.label ?? ''))}
      />
      <YAxis
        tick={{ fontSize: 11, fill: 'var(--muted-foreground)' }}
        tickLine={false}
        axisLine={false}
        domain={[0, yMax ?? 'auto']}
        width={64}
        label={{ value: unit, angle: -90, position: 'insideLeft', style: { fontSize: 11, fill: 'var(--muted-foreground)' } }}
      />
      <Tooltip content={<Tip unit={unit} />} />
      {band ? (
        <ReferenceArea x1={band[0]?.x} x2={band[1]?.x} fill="var(--accent)" fillOpacity={0.2} stroke="var(--accent)" />
      ) : null}
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
              {series.map((item) => (
                <linearGradient key={`${gradientId}-${item.key}`} id={`${gradientId}-${item.key}`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={item.color} stopOpacity={0.4} />
                  <stop offset="100%" stopColor={item.color} stopOpacity={0.02} />
                </linearGradient>
              ))}
            </defs>
            {axes}
            {series.map((item) => (
              <Area key={item.key} type="monotone" dataKey={item.key} name={item.label} stroke={item.color} strokeWidth={2} fill={`url(#${gradientId}-${item.key})`} connectNulls={false} stackId={stacked ? 'a' : undefined} isAnimationActive={false} />
            ))}
          </AreaChart>
        ) : kind === 'line' ? (
          <LineChart {...common}>
            {axes}
            {series.map((item) => (
              <Line key={item.key} type="monotone" dataKey={item.key} name={item.label} stroke={item.color} strokeWidth={2} strokeDasharray={item.dash} dot={false} connectNulls={false} isAnimationActive={false} />
            ))}
          </LineChart>
        ) : (
          <BarChart {...common}>
            {axes}
            {series.map((item) => (
              <Bar key={item.key} dataKey={item.key} name={item.label} fill={item.color} radius={[3, 3, 0, 0]} isAnimationActive={false} />
            ))}
          </BarChart>
        )}
      </ResponsiveContainer>
      {view.length > 0 ? (
        <div className="mt-2 space-y-1">
          <p data-testid="chart-window" className="font-mono-data text-xs text-foreground">
            <span className="font-sans font-medium">{zoom ? 'Selected' : windowLabel || 'Showing'}</span>
            {' · '}
            {from} – {to}
            {zone ? ` ${zone}` : ''}
          </p>
          {subject ? <p className="text-xs text-muted-foreground">{subject}</p> : null}
          {legend ? (
            <ul className="flex flex-wrap gap-x-4 gap-y-1" aria-label="Series on this graph">
              {series.map((item) => {
                const latest = [...view].reverse().find((row) => row[item.key] !== null && row[item.key] !== undefined);
                return (
                  <li key={item.key} className="flex items-center gap-1.5 text-xs">
                    <span className="inline-block h-2 w-2 rounded-full" style={{ backgroundColor: item.color }} />
                    <span>{item.label}</span>
                    <span className="font-mono-data font-semibold">{reading(latest?.[item.key], unit)}</span>
                  </li>
                );
              })}
            </ul>
          ) : null}
          <p className="text-[11px] text-muted-foreground">
            {zoom
              ? 'These times are the stretch you dragged. Reset zoom to see the whole range again.'
              : 'Drag across the graph to inspect a shorter time. The right edge is the current time.'}
          </p>
        </div>
      ) : null}
    </div>
  );
}
