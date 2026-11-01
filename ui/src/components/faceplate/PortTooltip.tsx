'use client';

import React, { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import type { PortInfo } from '@/lib/types';
import { PORT_STATE_META } from '@/components/ui/Badge';
import Icon from '@/components/ui/AppIcon';
import { STATE_COLOR } from './palette';

interface Props {
  port: PortInfo;
  left: number;
  top: number;
}

function fmtBps(bps: number | undefined): string {
  if (bps === undefined || Number.isNaN(bps)) return '—';
  const abs = Math.abs(bps);
  if (abs >= 1e9) return `${(bps / 1e9).toFixed(2)} Gbps`;
  if (abs >= 1e6) return `${(bps / 1e6).toFixed(2)} Mbps`;
  if (abs >= 1e3) return `${(bps / 1e3).toFixed(1)} kbps`;
  return `${Math.round(bps)} bps`;
}

export default function PortTooltip({ port, left, top }: Props) {
  const [container, setContainer] = useState<HTMLElement | null>(null);

  useEffect(() => {
    setContainer(document.body);
  }, []);

  const meta = PORT_STATE_META[port.state];
  const c = STATE_COLOR[port.state];
  if (!container) return null;
  return createPortal(
    <div
      role="tooltip"
      style={{ left, top, zIndex: 2147483647 }}
      className="pointer-events-none fixed w-60 -translate-x-1/2 -translate-y-full rounded-lg border border-navy-3 bg-navy p-3 text-primary-foreground shadow-pop pop-in"
    >
      <div className="flex items-center justify-between gap-2">
        <span className="font-mono-data text-sm font-semibold">{port.name}</span>
        <span className="inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-semibold" style={{ borderColor: c.fill, color: c.fill }}>
          <Icon name={meta.icon} size={11} variant="solid" />
          {meta.label}
        </span>
      </div>
      <dl className="mt-2 space-y-1.5 text-xs">
        <div className="flex justify-between">
          <dt className="text-down">Speed</dt>
          <dd className="font-mono-data">{port.speed}</dd>
        </div>
        <div className="flex justify-between">
          <dt className="text-down">In</dt>
          <dd className="font-mono-data">{fmtBps(port.inBps)}</dd>
        </div>
        <div className="flex justify-between">
          <dt className="text-down">Out</dt>
          <dd className="font-mono-data">{fmtBps(port.outBps)}</dd>
        </div>
        <div>
          <div className="mb-1 flex justify-between">
            <dt className="text-down">Utilisation</dt>
            <dd className="font-mono-data">{port.utilisation}%</dd>
          </div>
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-navy-3">
            <div className="h-full rounded-full" style={{ width: `${Math.min(100, port.utilisation)}%`, backgroundColor: port.utilisation > 85 ? 'var(--destructive)' : port.utilisation > 65 ? 'var(--warning)' : 'var(--success)' }} />
          </div>
        </div>
        <div className="flex justify-between">
          <dt className="text-down">Errors</dt>
          <dd className={`font-mono-data ${port.errors > 100 ? 'text-destructive' : port.errors > 0 ? 'text-warning' : ''}`}>{port.errors.toLocaleString('en-US')}</dd>
        </div>
        <div className="flex justify-between gap-3">
          <dt className="text-down">Neighbour</dt>
          <dd className="truncate text-right font-mono-data">{port.neighbour ? `${port.neighbour.device} · ${port.neighbour.port}${port.neighbour.source ? ` · ${port.neighbour.source}` : ''}` : 'none seen'}</dd>
        </div>
      </dl>
      <p className="mt-2 border-t border-navy-3 pt-1.5 text-[10px] text-down">Click to open port graph</p>
    </div>,
    container
  );
}