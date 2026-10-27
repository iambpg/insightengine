'use client';

import React from 'react';
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';

interface Props {
  data: { name: string; util: number }[];
  height?: number;
}

export default function TopPortsChart({ data, height = 240 }: Props) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} layout="vertical" margin={{ top: 4, right: 16, left: 8, bottom: 0 }}>
        <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" horizontal={false} />
        <XAxis type="number" domain={[0, 100]} tick={{ fontSize: 11, fill: 'var(--muted-foreground)' }} tickLine={false} axisLine={false} unit="%" />
        <YAxis type="category" dataKey="name" tick={{ fontSize: 11, fill: 'var(--foreground)' }} tickLine={false} axisLine={false} width={64} />
        <Tooltip
          cursor={{ fill: 'var(--muted)' }}
          content={({ active, payload }) =>
            active && payload?.length ? (
              <div className="rounded-lg border border-border bg-card px-3 py-2 text-xs shadow-pop">
                <p className="font-mono-data font-semibold">{String(payload[0].payload.name)}</p>
                <p className="text-muted-foreground">{String(payload[0].value)}% utilised</p>
              </div>
            ) : null
          }
        />
        <Bar dataKey="util" radius={[0, 3, 3, 0]} isAnimationActive={false}>
          {data.map((d) => (
            <Cell key={`cell-${d.name}`} fill={d.util > 85 ? 'var(--destructive)' : d.util > 65 ? 'var(--warning)' : 'var(--teal)'} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}