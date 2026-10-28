'use client';

import React, { useEffect, useState } from 'react';
import Icon from '@/components/ui/AppIcon';
import { Skeleton } from '@/components/ui/Skeleton';
import { api } from '@/lib/apiClient';
import { isMockMode } from '@/lib/apiMode';
import { reportLoadError } from '@/lib/loadError';
import type { DeviceHealth } from '@/lib/types';

interface Summary {
  total: number;
  healthy: number;
  warning: number;
  critical: number;
  unreachable: number;
  alerts: number;
}

interface Props {
  activeHealth: DeviceHealth | 'all';
  onPick: (h: DeviceHealth | 'all') => void;
}

const fmt = (n: number) => n.toLocaleString('en-US');

export default function HealthStrip({ activeHealth, onPick }: Props) {
  const [s, setS] = useState<Summary | null>(null);
  const [failed, setFailed] = useState<string | null>(null);

  useEffect(() => {
    api.getSummary().then(setS).catch((cause) => setFailed(reportLoadError(cause, 'the fleet summary')));
  }, []);

  if (failed) {
    return (
      <div role="alert" className="rounded-md border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
        {failed}
      </div>
    );
  }

  if (!s) {
    return (
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
        <Skeleton className="col-span-2 h-28 md:col-span-1" />
        {Array.from({ length: 4 }, (_, i) => (
          <Skeleton key={`hs-skel-${i + 1}`} className="h-28" />
        ))}
      </div>
    );
  }

  const pct = (n: number) => (s.total > 0 ? `${((n / s.total) * 100).toFixed(1)}%` : '0.0%');
  const mock = isMockMode();

  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5 2xl:gap-4">
      {/* hero: total devices with distribution bar */}
      <button
        type="button"
        onClick={() => onPick('all')}
        aria-pressed={activeHealth === 'all'}
        className={`col-span-2 rounded-lg border bg-navy p-4 text-left text-primary-foreground shadow-card transition-all duration-150 hover:-translate-y-0.5 md:col-span-1 ${
          activeHealth === 'all' ? 'border-cyan' : 'border-navy-3'
        }`}
      >
        <div className="flex items-center justify-between">
          <span className="label-caps text-down">All devices</span>
          <Icon name="ServerStackIcon" size={18} className="text-cyan" />
        </div>
        <p className="mt-2 text-3xl font-bold tabular">{fmt(s.total)}</p>
        <div className="mt-3 flex h-2 w-full overflow-hidden rounded-full bg-navy-3" role="img" aria-label={`Healthy ${pct(s.healthy)}, warning ${pct(s.warning)}, critical ${pct(s.critical)}, unreachable ${pct(s.unreachable)}`}>
          <span className="bg-success" style={{ width: pct(s.healthy) }} />
          <span className="bg-warning" style={{ width: pct(s.warning) }} />
          <span className="bg-destructive" style={{ width: pct(s.critical) }} />
          <span className="bg-down" style={{ width: pct(s.unreachable) }} />
        </div>
        <p className="mt-2 text-[11px] text-down">{mock ? `Across 2,014 sites · ${fmt(s.alerts)} alerts firing` : `${fmt(s.alerts)} open alerts`}</p>
      </button>

      <Tile label="Healthy" value={s.healthy} pct={pct(s.healthy)} tone="success" icon="CheckCircleIcon" note="Telemetry fresh, no faults" active={activeHealth === 'healthy'} onClick={() => onPick('healthy')} />
      <Tile label="Warning" value={s.warning} pct={pct(s.warning)} tone="warning" icon="ExclamationTriangleIcon" note="Errors or high utilisation" active={activeHealth === 'warning'} onClick={() => onPick('warning')} delta={mock ? '+118 vs yesterday' : undefined} />
      <Tile label="Critical" value={s.critical} pct={pct(s.critical)} tone="destructive" icon="XCircleIcon" note="Port, PSU or module fault" active={activeHealth === 'critical'} onClick={() => onPick('critical')} delta={mock ? '+37 vs yesterday' : undefined} alert />
      <Tile label="Unreachable" value={s.unreachable} pct={pct(s.unreachable)} tone="neutral" icon="SignalSlashIcon" note="No poll for 30+ minutes" active={activeHealth === 'unreachable'} onClick={() => onPick('unreachable')} delta={mock ? '−12 vs yesterday' : undefined} />
    </div>
  );
}

interface TileProps {
  label: string;
  value: number;
  pct: string;
  tone: 'success' | 'warning' | 'destructive' | 'neutral';
  icon: string;
  note: string;
  active: boolean;
  onClick: () => void;
  delta?: string;
  alert?: boolean;
}

const TILE_TONE: Record<TileProps['tone'], { wrap: string; icon: string; value: string }> = {
  success: { wrap: 'bg-success/10 border-success/30', icon: 'text-success', value: 'text-foreground' },
  warning: { wrap: 'bg-warning/10 border-warning/40', icon: 'text-warning', value: 'text-foreground' },
  destructive: { wrap: 'bg-destructive/10 border-destructive/30', icon: 'text-destructive', value: 'text-destructive' },
  neutral: { wrap: 'bg-muted border-border', icon: 'text-muted-foreground', value: 'text-foreground' },
};

function Tile({ label, value, pct, tone, icon, note, active, onClick, delta, alert }: TileProps) {
  const t = TILE_TONE[tone];
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={`rounded-lg border p-4 text-left shadow-card transition-all duration-150 hover:-translate-y-0.5 active:scale-[0.98] ${t.wrap} ${active ? 'ring-2 ring-ring' : ''}`}
    >
      <div className="flex items-center justify-between">
        <span className="label-caps text-muted-foreground">{label}</span>
        <Icon name={icon} size={18} variant="solid" className={t.icon} />
      </div>
      <p className={`mt-2 text-3xl font-bold tabular ${t.value}`}>{fmt(value)}</p>
      <div className="mt-1 flex items-center justify-between text-xs">
        <span className="font-mono-data text-muted-foreground">{pct} of fleet</span>
        {delta ? (
          <span className={`font-medium ${alert ? 'text-destructive' : 'text-muted-foreground'}`}>{delta}</span>
        ) : null}
      </div>
      <p className="mt-2 text-[11px] text-muted-foreground">{note}</p>
    </button>
  );
}