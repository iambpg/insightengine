'use client';

import React from 'react';
import type { RangeKey } from '@/lib/mockData';

interface Props {
  value: RangeKey;
  onChange: (r: RangeKey) => void;
  customMin: number;
  onCustomMin: (m: number) => void;
  label: string;
}

const OPTIONS: { key: RangeKey; label: string }[] = [
  { key: '1h', label: '1h' },
  { key: '6h', label: '6h' },
  { key: '24h', label: '24h' },
  { key: '7d', label: '7d' },
  { key: 'custom', label: 'Custom' },
];

export default function RangeSelector({ value, onChange, customMin, onCustomMin, label }: Props) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <div role="radiogroup" aria-label={`${label} time range`} className="inline-flex rounded-md border border-border bg-muted p-0.5">
        {OPTIONS.map((o) => (
          <button
            key={`${label}-${o.key}`}
            type="button"
            role="radio"
            aria-checked={value === o.key}
            onClick={() => onChange(o.key)}
            className={`rounded px-2.5 py-1 text-xs font-medium transition-all duration-150 active:scale-95 ${
              value === o.key ? 'bg-card text-foreground shadow-card' : 'text-muted-foreground hover:text-foreground'
            }`}
          >
            {o.label}
          </button>
        ))}
      </div>
      {value === 'custom' && (
        <label className="flex items-center gap-1.5 text-xs text-muted-foreground slide-up">
          Last
          <select
            value={customMin}
            onChange={(e) => onCustomMin(Number(e.target.value))}
            className="rounded-md border border-input bg-card px-1.5 py-1 text-xs text-foreground"
          >
            <option value={30}>30 min</option>
            <option value={180}>3 h</option>
            <option value={720}>12 h</option>
            <option value={2880}>2 days</option>
            <option value={14400}>10 days</option>
          </select>
        </label>
      )}
    </div>
  );
}