import React from 'react';

export function Skeleton({ className = '' }: { className?: string }) {
  return <div className={`animate-pulse rounded-md bg-muted ${className}`} />;
}

export function TableSkeleton({ rows = 10, cols = 8 }: { rows?: number; cols?: number }) {
  return (
    <div className="divide-y divide-border">
      {Array.from({ length: rows }, (_, r) => (
        <div key={`skel-row-${r + 1}`} className="flex items-center gap-4 px-4 py-3.5">
          {Array.from({ length: cols }, (_, c) => (
            <Skeleton key={`skel-cell-${r + 1}-${c + 1}`} className={`h-4 ${c === 1 ? 'w-40' : 'flex-1'}`} />
          ))}
        </div>
      ))}
    </div>
  );
}