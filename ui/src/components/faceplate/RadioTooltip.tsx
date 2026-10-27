'use client';

import React, { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import type { RadioInfo } from '@/lib/types';
import { STATE_COLOR, STATE_LABEL } from './palette';

interface Props {
  radio: RadioInfo;
  left: number;
  top: number;
}

export default function RadioTooltip({ radio, left, top }: Props) {
  const [container, setContainer] = useState<HTMLElement | null>(null);

  useEffect(() => {
    setContainer(document.body);
  }, []);

  const c = STATE_COLOR[radio.state];
  if (!container) return null;
  return createPortal(
    <div
      role="tooltip"
      style={{ left, top, zIndex: 2147483647 }}
      className="pointer-events-none fixed w-60 -translate-x-1/2 -translate-y-full rounded-lg border border-navy-3 bg-navy p-3 text-primary-foreground shadow-pop pop-in"
    >
      <div className="flex items-center justify-between gap-2">
        <span className="font-mono-data text-sm font-semibold">{radio.band} radio</span>
        <span className="inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-semibold" style={{ borderColor: c.fill, color: c.fill }}>
          {STATE_LABEL[radio.state]}
        </span>
      </div>
      <dl className="mt-2 space-y-1.5 text-xs">
        <div className="flex justify-between">
          <dt className="text-down">Channel</dt>
          <dd className="font-mono-data">{radio.channel}{radio.channelWidth ? ` · ${radio.channelWidth}` : ''}</dd>
        </div>
        <div className="flex justify-between">
          <dt className="text-down">Clients</dt>
          <dd className="font-mono-data">{radio.clients}</dd>
        </div>
        <div>
          <div className="mb-1 flex justify-between">
            <dt className="text-down">Utilisation</dt>
            <dd className="font-mono-data">{radio.utilisation}%</dd>
          </div>
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-navy-3">
            <div className="h-full rounded-full" style={{ width: `${Math.min(100, radio.utilisation)}%`, backgroundColor: radio.utilisation > 85 ? 'var(--destructive)' : radio.utilisation > 65 ? 'var(--warning)' : 'var(--success)' }} />
          </div>
        </div>
        {radio.txPower && (
          <div className="flex justify-between">
            <dt className="text-down">Tx power</dt>
            <dd className="font-mono-data">{radio.txPower}</dd>
          </div>
        )}
      </dl>
      <p className="mt-2 border-t border-navy-3 pt-1.5 text-[10px] text-down">Click for full radio details</p>
    </div>,
    container
  );
}
