'use client';

import React, { useMemo } from 'react';
import Faceplate from '@/components/faceplate/Faceplate';
import { buildFaceplateFor } from '@/lib/mockData';
import type { DeviceRow } from '@/lib/types';

// Small floating faceplate preview shown when hovering a hostname in the table.
export default function HoverPreview({ row }: { row: DeviceRow }) {
  const device = useMemo(() => buildFaceplateFor(row.formFactor), [row.formFactor]);
  return (
    <div className="pop-in pointer-events-none absolute left-0 top-full z-40 mt-2 w-[360px] rounded-lg border border-border bg-card p-3 shadow-pop" role="tooltip">
      <p className="mb-2 flex items-center justify-between text-xs">
        <span className="font-mono-data font-semibold">{row.hostname}</span>
        <span className="text-muted-foreground">{row.modelFamily}</span>
      </p>
      <div className="rounded-md bg-background p-2">
        <Faceplate device={device} compact />
      </div>
      <p className="mt-2 text-[11px] text-muted-foreground">Preview only — open the device for live port detail.</p>
    </div>
  );
}