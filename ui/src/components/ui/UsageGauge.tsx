import React from 'react';

export default function UsageGauge({ label, value, size = 'md' }: { label: string; value?: number | null; size?: 'md' | 'lg' }) {
  const amount = value == null ? 0 : Math.max(0, Math.min(100, value));
  const free = value == null ? null : 100 - amount;
  const tone = value == null ? 'stroke-muted-foreground/40' : value >= 90 ? 'stroke-destructive' : value >= 75 ? 'stroke-warning' : 'stroke-success';
  const shown = value == null ? '—' : `${value}%`;
  const freeText = free == null ? '—' : `${free}%`;
  const large = size === 'lg';
  const frame = large ? 'h-32 w-32' : 'h-20 w-20';
  return (
    <div className={`flex flex-col items-center text-center ${large ? 'w-32' : 'min-w-[4.75rem]'}`} aria-label={`${label} used ${shown}, free ${freeText}`}>
      <div className={`relative ${frame}`}>
        <svg viewBox="0 0 36 36" className={`${frame} -rotate-90`} aria-hidden="true">
          <circle cx="18" cy="18" r="14" fill="none" className="stroke-muted" strokeWidth={large ? 4 : 5} />
          {amount > 0 ? (
            <circle
              cx="18"
              cy="18"
              r="14"
              fill="none"
              className={tone}
              strokeWidth={large ? 4 : 5}
              strokeDasharray={`${amount} ${100 - amount}`}
              pathLength="100"
            />
          ) : null}
        </svg>
        <p className={`absolute inset-0 flex items-center justify-center font-semibold tabular ${large ? 'text-lg' : 'text-sm'}`}>{shown}</p>
      </div>
      <p className={`mt-1 uppercase tracking-wide text-muted-foreground ${large ? 'text-xs font-medium' : 'text-[10px]'}`}>{label}</p>
      <p className={`leading-tight text-muted-foreground ${large ? 'text-xs' : 'text-[10px]'}`}>Used {shown}</p>
      <p className={`leading-tight text-muted-foreground ${large ? 'text-xs' : 'text-[10px]'}`}>Free {freeText}</p>
    </div>
  );
}
