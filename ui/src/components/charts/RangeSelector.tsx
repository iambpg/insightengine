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
  { key: '5m', label: '5m' },
  { key: '15m', label: '15m' },
  { key: '1h', label: '1h' },
  { key: '6h', label: '6h' },
  { key: '24h', label: '24h' },
  { key: '7d', label: '7d' },
  { key: 'custom', label: 'Custom' },
];

export function rangeWindowLabel(value: RangeKey, customMin: number): string {
  if (value === '5m') return 'Last 5 minutes';
  if (value === '15m') return 'Last 15 minutes';
  if (value === '1h') return 'Last hour';
  if (value === '6h') return 'Last 6 hours';
  if (value === '24h') return 'Last 24 hours';
  if (value === '7d') return 'Last 7 days';
  if (customMin < 60) return `Last ${customMin} minutes`;
  const hours = Math.max(1, Math.round(customMin / 60));
  if (hours < 48) return hours === 1 ? 'Last hour' : `Last ${hours} hours`;
  const days = Math.max(1, Math.round(hours / 24));
  return days === 1 ? 'Last day' : `Last ${days} days`;
}

export default function RangeSelector({ value, onChange, customMin, onCustomMin, label }: Props) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <div role="radiogroup" aria-label={`${label} time range`} className="inline-flex max-w-full flex-wrap rounded-md border border-border bg-muted p-0.5">
        {OPTIONS.map((option) => (
          <button
            key={`${label}-${option.key}`}
            type="button"
            role="radio"
            aria-checked={value === option.key}
            onClick={() => onChange(option.key)}
            className={`rounded px-2.5 py-1 text-xs font-medium transition-all duration-150 active:scale-95 ${
              value === option.key ? 'bg-card text-foreground shadow-card' : 'text-muted-foreground hover:text-foreground'
            }`}
          >
            {option.label}
          </button>
        ))}
      </div>
      {value === 'custom' && (
        <label className="flex items-center gap-1.5 text-xs text-muted-foreground slide-up">
          Last
          <select
            value={customMin}
            onChange={(event) => onCustomMin(Number(event.target.value))}
            className="rounded-md border border-input bg-card px-1.5 py-1 text-xs text-foreground"
          >
            <option value={5}>5 min</option>
            <option value={15}>15 min</option>
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
