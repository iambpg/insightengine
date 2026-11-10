'use client';

import React from 'react';
import Link from 'next/link';
import Icon from '@/components/ui/AppIcon';
import { PortStateBadge } from '@/components/ui/Badge';
import GraphPanel from '@/components/charts/GraphPanel';
import { api } from '@/lib/apiClient';
import { devicePath, isMockMode } from '@/lib/apiMode';
import type { PortInfo, PortNeighbour } from '@/lib/types';
import { portNameLine } from '@/components/faceplate/portText';

const STATE_TEXT: Record<string, string> = {
  up: 'Link up, passing traffic',
  down: 'Link down, no carrier detected',
  warning: 'At least 20 input errors in 5 minutes, or utilisation is high',
  fault: 'At least 50 input errors in 5 minutes',
  disabled: 'Administratively disabled. Nothing is faulty.',
  'not-connected': 'Admin state is enabled and nothing is connected.',
  unknown: 'No SNMP oper state for this port yet',
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

function neighbourKind(name: string, role?: string): { label: string; icon: string } {
  const n = `${role || ''} ${name}`.toLowerCase();
  if (n.includes('access point') || /\bap\b/.test(n) || n.includes('-ap')) return { label: 'Access point', icon: 'WifiIcon' };
  if (n.includes('sdwan') || n.includes('sd-wan')) return { label: 'SD-WAN', icon: 'ArrowsRightLeftIcon' };
  if (n.includes('firewall') || n.includes('fortigate') || n.includes('palo')) return { label: 'Firewall', icon: 'ShieldCheckIcon' };
  if (n.includes('router')) return { label: 'Router', icon: 'ArrowsRightLeftIcon' };
  if (n.includes('wireless') || n.includes('wlc')) return { label: 'Wireless controller', icon: 'SignalIcon' };
  if (n.includes('switch') || n.includes('chassis')) return { label: 'Switch', icon: 'ServerIcon' };
  return { label: role || 'Network device', icon: 'CubeIcon' };
}

/** A neighbour opens its device page only when that device is one we monitor. */
function neighbourHref(neighbour: PortNeighbour): string {
  const id = (neighbour.deviceId || '').trim();
  if (!id) return '';
  return devicePath(id, neighbour.formFactor || 'generic');
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
  const kind = nb ? neighbourKind(nb.device, nb.role) : null;
  const neighbourLink = nb ? neighbourHref(nb) : '';
  const errTone = port.errors >= 50 ? 'bad' : port.errors >= 20 ? 'warn' : undefined;

  return (
    <aside className="h-full space-y-4 p-4" aria-label={`Port ${port.name} details`}>
      <header className="flex items-start justify-between gap-3">
        <div>
          <p className="label-caps text-muted-foreground">Selected port</p>
          <h3 className="font-mono-data text-xl font-semibold break-all">{portNameLine(port)}</h3>
          <p className="mt-1 text-sm text-muted-foreground">
            Description <span className="font-mono-data text-foreground">{port.description || '—'}</span>
          </p>
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
              {neighbourLink ? (
                <Link href={neighbourLink} className="block truncate font-mono-data text-sm font-semibold text-primary hover:underline" title={`Open ${nb.device}`}>
                  {nb.device}
                </Link>
              ) : (
                <p className="truncate font-mono-data text-sm font-semibold" title={nb.device}>{nb.device}</p>
              )}
              <p className="text-xs text-muted-foreground">{kind.label} · remote port <span className="font-mono-data text-foreground">{nb.port}</span></p>
              <p className="mt-1 text-xs text-muted-foreground">Discovered via LLDP</p>
            </div>
          </div>
        ) : (
          <p className="mt-2 flex items-center gap-2 text-sm text-muted-foreground">
            <Icon name="MinusCircleIcon" size={16} />
            {port.state === 'disabled'
              ? 'Administratively disabled. Nothing is faulty.'
              : port.state === 'not-connected'
                ? 'Nothing is connected to this port.'
                : 'No neighbour seen on this port.'}
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

export function PortThroughputGraph({ port, deviceId }: { port: PortInfo; deviceId?: string }) {
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
      fetcher={async (range, customMin) =>
        (await api.getPortSeries(port.id, range, customMin, isMockMode() ? undefined : deviceId)) as unknown as Record<
          string,
          number | string | null
        >[]
      }
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