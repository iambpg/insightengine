'use client';

import React from 'react';
import Icon from '@/components/ui/AppIcon';
import { PortStateBadge } from '@/components/ui/Badge';
import GraphPanel from '@/components/charts/GraphPanel';
import { api } from '@/lib/apiClient';
import type { PortInfo } from '@/lib/types';

const STATE_TEXT: Record<string, string> = {
  up: 'Link up, passing traffic',
  down: 'Link down, no carrier detected',
  warning: 'Link up with warnings, check utilisation or errors',
  fault: 'Port fault, link unstable or failed',
  disabled: 'Administratively disabled',
};

function hashNum(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
  return h;
}

function parseMbps(speed: string): number {
  const m = /([\d.]+)\s*([GMgm])/.exec(speed ?? '');
  if (!m) return 0;
  const n = parseFloat(m[1]);
  return m[2].toLowerCase() === 'g' ? n * 1000 : n;
}

function fmtRate(mbps: number): string {
  return mbps >= 1000 ? `${(mbps / 1000).toFixed(2)} Gbps` : `${mbps.toFixed(1)} Mbps`;
}

function mediaFor(type: string): string {
  if (type === 'RJ45') return 'Copper, Cat6 twisted pair';
  if (type === 'SFP') return 'Fibre / SFP transceiver';
  if (type === 'SFP+') return 'Fibre / SFP+ transceiver';
  if (type === 'QSFP') return 'Fibre / QSFP transceiver';
  return type;
}

function neighbourKind(name: string): { label: string; icon: string } {
  const n = name.toLowerCase();
  if (n.includes('ap')) return { label: 'Access point', icon: 'WifiIcon' };
  if (n.includes('fw') || n.includes('firewall')) return { label: 'Firewall', icon: 'ShieldCheckIcon' };
  if (n.includes('rtr') || n.includes('router') || n.includes('br')) return { label: 'Router', icon: 'ArrowsRightLeftIcon' };
  if (n.includes('wlc') || n.includes('ctrl')) return { label: 'Wireless controller', icon: 'SignalIcon' };
  if (n.includes('core') || n.includes('dist') || n.includes('sw') || n.includes('chassis')) return { label: 'Switch', icon: 'ServerIcon' };
  return { label: 'Network device', icon: 'CubeIcon' };
}

export default function PortSidePanel({ port, onClose }: { port: PortInfo; onClose: () => void }) {
  const isLive = port.state === 'up' || port.state === 'warning';
  const speedMbps = parseMbps(port.speed);
  const seed = hashNum(port.id);
  const rx = isLive ? (speedMbps * port.utilisation) / 100 : 0;
  const tx = isLive ? rx * (0.35 + (seed % 50) / 100) : 0;
  const pktsIn = isLive ? 200 + (seed % 900) : 0;
  const pktsOut = isLive ? 150 + ((seed >> 3) % 800) : 0;
  const duplex = isLive ? 'Full' : 'n/a';
  const lastChange = isLive ? `${1 + (seed % 40)} d ${seed % 24} h ago` : `${1 + (seed % 55)} min ago`;
  const vlan = port.state === 'disabled' ? 'n/a' : 10 + (seed % 5) * 10;
  const nb = port.neighbour;
  const kind = nb ? neighbourKind(nb.device) : null;
  const errTone = port.errors > 100 ? 'bad' : port.errors > 0 ? 'warn' : undefined;

  return (
    <aside className="h-full space-y-4 p-4" aria-label={`Port ${port.name} details`}>
      <header className="flex items-start justify-between gap-3">
        <div>
          <p className="label-caps text-muted-foreground">Selected port</p>
          <h3 className="font-mono-data text-xl font-semibold">{port.name}</h3>
          <div className="mt-1.5 flex items-center gap-2">
            <PortStateBadge state={port.state} />
            <span className="font-mono-data text-xs text-muted-foreground">{port.type} · {port.speed}</span>
          </div>
        </div>
        <button type="button" onClick={onClose} aria-label="Close port panel" className="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground">
          <Icon name="XMarkIcon" size={18} />
        </button>
      </header>

      <p className="rounded-md border border-border bg-muted/50 px-3 py-2 text-xs text-muted-foreground">
        {STATE_TEXT[port.state] ?? 'Status unknown'}
        {port.label ? <span className="font-mono-data text-foreground"> · {port.label}</span> : null}
      </p>

      <section aria-label="Connected device" className="rounded-md border border-border bg-background p-3">
        <h4 className="label-caps text-muted-foreground">Connected to</h4>
        {nb && kind ? (
          <div className="mt-2 flex items-start gap-3">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
              <Icon name={kind.icon as any} size={18} />
            </span>
            <div className="min-w-0">
              <p className="truncate font-mono-data text-sm font-semibold" title={nb.device}>{nb.device}</p>
              <p className="text-xs text-muted-foreground">{kind.label} · remote port <span className="font-mono-data text-foreground">{nb.port}</span></p>
              <p className="mt-1 text-xs text-muted-foreground">Discovered via LLDP</p>
            </div>
          </div>
        ) : (
          <p className="mt-2 flex items-center gap-2 text-sm text-muted-foreground">
            <Icon name="MinusCircleIcon" size={16} />
            {port.state === 'disabled' ? 'Port is disabled, nothing is connected.' : 'No neighbour seen on this port.'}
          </p>
        )}
      </section>

      <dl className="grid grid-cols-2 gap-2.5 text-sm">
        <Stat label="Utilisation" value={`${port.utilisation}%`} />
        <Stat label="Errors" value={port.errors.toLocaleString('en-US')} tone={errTone} />
        <Stat label="Traffic in" value={fmtRate(rx)} mono />
        <Stat label="Traffic out" value={fmtRate(tx)} mono />
        <Stat label="Packets in" value={`${pktsIn.toLocaleString('en-US')} kpps`} mono />
        <Stat label="Packets out" value={`${pktsOut.toLocaleString('en-US')} kpps`} mono />
        <Stat label="Media" value={mediaFor(port.type)} mono />
        <Stat label="Duplex" value={duplex} mono />
        <Stat label="VLAN" value={String(vlan)} mono />
        <Stat label="PoE" value={port.poe ? 'Enabled' : 'n/a'} />
        <Stat label="Last change" value={lastChange} mono />
        <Stat label="Admin state" value={port.state === 'disabled' ? 'Disabled' : 'Enabled'} />
      </dl>
      <p className="text-[11px] text-muted-foreground">Example data: extra link details are illustrative until a backend is connected.</p>
    </aside>
  );
}

export function PortThroughputGraph({ port }: { port: PortInfo }) {
  return (
    <GraphPanel
      id={`port-${port.id}`}
      title={`Port throughput · ${port.name}`}
      subtitle="Mbps in / out"
      unit="Mbps"
      kind="area"
      height={220}
      series={[
        { key: 'inBps', label: 'In', color: 'var(--teal)' },
        { key: 'outBps', label: 'Out', color: 'var(--cyan)' },
      ]}
      deps={port.id}
      fetcher={async (range, customMin) => (await api.getPortSeries(port.id, range, customMin)) as unknown as Record<string, number | string | null>[]}
    />
  );
}

function Stat({ label, value, mono, tone }: { label: string; value: string; mono?: boolean; tone?: 'bad' | 'warn' }) {
  return (
    <div className="rounded-md border border-border bg-background p-2.5">
      <dt className="label-caps text-muted-foreground">{label}</dt>
      <dd className={`mt-0.5 truncate ${mono ? 'font-mono-data text-xs' : 'text-base font-semibold tabular'} ${tone === 'bad' ? 'text-destructive' : tone === 'warn' ? 'text-warning-foreground' : ''}`} title={value}>
        {value}
      </dd>
    </div>
  );
}