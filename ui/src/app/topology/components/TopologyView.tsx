'use client';

import React, { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import Icon from '@/components/ui/AppIcon';
import ExampleDataBanner from '@/components/ui/ExampleDataBanner';
import { HealthBadge } from '@/components/ui/Badge';
import { Skeleton } from '@/components/ui/Skeleton';
import { api } from '@/lib/apiClient';
import { reportLoadError } from '@/lib/loadError';
import { isMockMode } from '@/lib/apiMode';
import { FACEPLATE_SAMPLES } from '@/lib/mockData';
import type { DeviceDetailData, DeviceHealth, DeviceRow, PortInfo, SiteRow } from '@/lib/types';
import DeviceArt, { ArtDefs, type DeviceKind } from '@/app/topology/components/DeviceArt';
import TopologySiteList from '@/app/topology/components/TopologySiteList';

interface TopoNode {
  id: string;
  label: string;
  sub: string;
  kind: DeviceKind;
  health: DeviceHealth;
  x: number;
  y: number;
  current?: boolean;
  href?: string;
}

interface TopoLink {
  id: string;
  from: string;
  to: string;
  label: string;
  state: 'up' | 'warning' | 'fault';
}

const FORMS = Object.keys(FACEPLATE_SAMPLES);
const NODE_W = 128;
const NODE_H = 40;

const KIND_FORM: Partial<Record<DeviceKind, string>> = {
  switch: 'access-switch-48',
  stack: 'switch-stack',
  firewall: 'firewall',
  router: 'branch-router',
  controller: 'wireless-controller',
  ap: 'ceiling-ap',
  chassis: 'modular-chassis',
};

function hrefForKind(kind: DeviceKind): string | undefined {
  const f = KIND_FORM[kind];
  return f && FORMS.includes(f) ? `/device-detail?form=${f}` : undefined;
}

function hrefForForm(form: string, kind: DeviceKind): string | undefined {
  return FORMS.includes(form) ? `/device-detail?form=${form}` : hrefForKind(kind);
}

const STATE_STROKE: Record<TopoLink['state'], string> = {
  up: 'var(--success)',
  warning: 'var(--warning)',
  fault: 'var(--destructive)',
};

const HEALTH_STROKE: Record<DeviceHealth, string> = {
  healthy: 'var(--success)',
  warning: 'var(--warning)',
  critical: 'var(--destructive)',
  unreachable: 'var(--muted-foreground)',
};

function kindFor(role: string, name = ''): DeviceKind {
  const r = role.toLowerCase();
  const n = name.toLowerCase();
  if (r.includes('firewall') || n.startsWith('fw')) return 'firewall';
  if (r.includes('router') || n.startsWith('rtr')) return 'router';
  if (r.includes('access point') || n.startsWith('ap')) return 'ap';
  if (r.includes('wireless') || n.startsWith('wlc')) return 'controller';
  if (r.includes('stack') || n.startsWith('stk')) return 'stack';
  if (r.includes('chassis') || n.startsWith('chs')) return 'chassis';
  if (n.startsWith('isp') || n.startsWith('wan')) return 'cloud';
  return 'switch';
}

function portsOf(d: DeviceDetailData): PortInfo[] {
  const f = d.faceplate;
  if (f.members) return f.members.flatMap((m) => m.ports);
  if (f.modules) return f.modules.flatMap((m) => m.ports);
  return f.ports ?? [];
}

function buildDeviceTopology(d: DeviceDetailData) {
  const neighbours = new Map<string, { port: string; local: string; state: TopoLink['state'] }>();
  portsOf(d).forEach((p) => {
    if (p.neighbour && !neighbours.has(p.neighbour.device)) {
      neighbours.set(p.neighbour.device, {
        port: p.neighbour.port,
        local: p.name,
        state: p.state === 'fault' ? 'fault' : p.state === 'warning' ? 'warning' : 'up',
      });
    }
  });
  const list = Array.from(neighbours.entries()).slice(0, 6);
  const W = 900;
  const H = 380;
  const nodes: TopoNode[] = [
    { id: 'self', label: d.hostname, sub: d.mgmtIp, kind: kindFor(d.role, d.hostname), health: d.health, x: W / 2, y: H / 2, current: true, href: hrefForForm(d.faceplate.form_factor, kindFor(d.role, d.hostname)) },
  ];
  const links: TopoLink[] = [];
  list.forEach(([name, info], i) => {
    const angle = (Math.PI * 2 * i) / Math.max(list.length, 1) - Math.PI / 2;
    nodes.push({
      id: `n-${name}`,
      label: name,
      sub: info.port,
      kind: kindFor('', name),
      health: info.state === 'fault' ? 'critical' : info.state === 'warning' ? 'warning' : 'healthy',
      x: W / 2 + Math.cos(angle) * 320,
      y: H / 2 + Math.sin(angle) * 140,
      href: hrefForKind(kindFor('', name)),
    });
    links.push({ id: `l-${name}`, from: 'self', to: `n-${name}`, label: `${info.local} ↔ ${info.port}`, state: info.state });
  });
  return { nodes, links, W, H };
}

function stateOf(h: DeviceHealth): TopoLink['state'] {
  return h === 'critical' || h === 'unreachable' ? 'fault' : h === 'warning' ? 'warning' : 'up';
}

function buildSiteTopology(devices: DeviceRow[], currentHost?: string) {
  const W = 900;
  const find = (k: DeviceKind) => devices.filter((d) => kindFor(d.role, d.hostname) === k);
  const fw = find('firewall')[0];
  const rtr = find('router')[0];
  const wlc = find('controller')[0];
  const aps = find('ap');
  const stacks = find('stack');
  const switches = find('switch');
  const lower = [...stacks, ...switches];

  const nodes: TopoNode[] = [];
  const links: TopoLink[] = [];
  const mk = (d: DeviceRow, x: number, y: number, sub?: string): TopoNode => ({
    id: d.id,
    label: d.hostname,
    sub: sub ?? d.mgmtIp,
    kind: kindFor(d.role, d.hostname),
    health: d.health,
    x,
    y,
    current: currentHost ? d.hostname === currentHost : false,
    href: hrefForForm(d.formFactor, kindFor(d.role, d.hostname)),
  });

  nodes.push({ id: 'wan', label: 'ISP uplink', sub: 'WAN', kind: 'cloud', health: 'healthy', x: W / 2, y: 40 });
  let edgeId = 'wan';
  let y = 40;
  if (rtr) {
    y += 85;
    nodes.push(mk(rtr, W / 2, y));
    links.push({ id: 'e-wan-rtr', from: 'wan', to: rtr.id, label: 'WAN', state: stateOf(rtr.health) });
    edgeId = rtr.id;
  }
  if (fw) {
    y += 85;
    nodes.push(mk(fw, W / 2, y));
    links.push({ id: 'e-fw', from: edgeId, to: fw.id, label: 'Te0/1', state: stateOf(fw.health) });
    edgeId = fw.id;
  }
  const coreY = y + 95;
  const distId = edgeId;
  const rowY = coreY;
  const lowerNodes = [...lower.slice(0, 4)];
  const sideItems: DeviceRow[] = [];
  if (wlc) sideItems.push(wlc);
  const total = lowerNodes.length + sideItems.length;
  const gap = total > 0 ? Math.min(210, (W - 160) / Math.max(total, 1)) : 0;
  const startX = W / 2 - ((total - 1) * gap) / 2;
  [...lowerNodes, ...sideItems].forEach((d, i) => {
    nodes.push(mk(d, startX + i * gap, rowY));
    links.push({ id: `e-${d.id}`, from: distId, to: d.id, label: `Te1/0/${i + 1}`, state: stateOf(d.health) });
  });
  const apY = rowY + 95;
  const apList = aps.slice(0, 4);
  const apGap = apList.length > 0 ? Math.min(180, (W - 160) / apList.length) : 0;
  const apStart = W / 2 - ((apList.length - 1) * apGap) / 2;
  const apParent = wlc ? wlc.id : lowerNodes[0]?.id ?? distId;
  apList.forEach((d, i) => {
    nodes.push(mk(d, apStart + i * apGap, apY));
    links.push({ id: `e-${d.id}`, from: apParent, to: d.id, label: `Gi1/0/${i + 10}`, state: stateOf(d.health) });
  });
  const H = (apList.length > 0 ? apY : rowY) + 60;
  return { nodes, links, W, H };
}

function Diagram({ nodes, links, W, H, title }: { nodes: TopoNode[]; links: TopoLink[]; W: number; H: number; title: string }) {
  const [hover, setHover] = useState<string | null>(null);
  const pos = useMemo(() => {
    const m = new Map<string, TopoNode>();
    nodes.forEach((n) => m.set(n.id, n));
    return m;
  }, [nodes]);

  return (
    <div className="scroll-thin overflow-x-auto bg-gradient-to-b from-secondary to-background p-3">
      <svg role="img" aria-label={title} viewBox={`0 0 ${W} ${H}`} className="mx-auto block min-w-[720px] w-full" style={{ maxWidth: 1100 }}>
        <ArtDefs />
        {links.map((l) => {
          const a = pos.get(l.from);
          const b = pos.get(l.to);
          if (!a || !b) return null;
          const mx = (a.x + b.x) / 2;
          const my = (a.y + b.y) / 2;
          const active = hover === l.id || hover === l.from || hover === l.to;
          return (
            <g key={l.id}>
              <line
                x1={a.x}
                y1={a.y}
                x2={b.x}
                y2={b.y}
                stroke={STATE_STROKE[l.state]}
                strokeWidth={active ? 3.5 : 2}
                strokeDasharray={l.state === 'fault' ? '6 4' : undefined}
                opacity={hover && !active ? 0.35 : 1}
              />
              <rect x={mx - 30} y={my - 16} width="60" height="13" rx="3" fill="var(--card)" opacity="0.9" />
              <text x={mx} y={my - 6} textAnchor="middle" fontSize="9.5" fill="var(--muted-foreground)" className="font-mono-data">
                {l.label.length > 14 ? `${l.label.slice(0, 13)}…` : l.label}
              </text>
            </g>
          );
        })}
        {nodes.map((n) => {
          const dim = hover && hover !== n.id && !links.some((l) => (l.from === n.id || l.to === n.id) && (l.from === hover || l.to === hover));
          const ringW = n.kind === 'cloud' ? 90 : NODE_W + 10;
          const inner = (
            <g
              onMouseEnter={() => setHover(n.id)}
              onMouseLeave={() => setHover(null)}
              opacity={dim ? 0.45 : 1}
              className={n.href ? 'cursor-pointer' : undefined}
            >
              <rect
                x={n.x - ringW / 2 - 4}
                y={n.y - NODE_H / 2 - 16}
                width={ringW + 8}
                height={NODE_H + 54 + (n.kind === 'chassis' ? 12 : 0)}
                fill="transparent"
              />
              {n.kind !== 'cloud' && (
                <rect
                  x={n.x - ringW / 2}
                  y={n.y - NODE_H / 2 - 5}
                  width={ringW}
                  height={NODE_H + 10 + (n.kind === 'chassis' ? 6 : 0)}
                  rx="8"
                  fill="none"
                  stroke={n.current ? 'var(--primary)' : HEALTH_STROKE[n.health]}
                  strokeWidth={n.current ? 2.5 : 1.2}
                  strokeDasharray={n.current ? undefined : '3 3'}
                  opacity={n.current ? 1 : 0.7}
                />
              )}
              <DeviceArt kind={n.kind} x={n.x - NODE_W / 2} y={n.y - NODE_H / 2} w={NODE_W} h={NODE_H} />
              <circle cx={n.x + ringW / 2 - 4} cy={n.y - NODE_H / 2 - 1} r="5" fill={HEALTH_STROKE[n.health]} stroke="var(--card)" strokeWidth="1.5" />
              <text x={n.x} y={n.y + NODE_H / 2 + (n.kind === 'chassis' ? 22 : 17)} textAnchor="middle" fontSize="11" fontWeight="600" fill="var(--foreground)" className="font-mono-data">
                {n.label.length > 20 ? `${n.label.slice(0, 19)}…` : n.label}
              </text>
              <text x={n.x} y={n.y + NODE_H / 2 + (n.kind === 'chassis' ? 33 : 28)} textAnchor="middle" fontSize="9.5" fill="var(--muted-foreground)">
                {n.sub.length > 24 ? `${n.sub.slice(0, 23)}…` : n.sub}
              </text>
              {n.current && (
                <text x={n.x} y={n.y - NODE_H / 2 - 10} textAnchor="middle" fontSize="8.5" fontWeight="700" fill="var(--primary)">
                  THIS DEVICE
                </text>
              )}
            </g>
          );
          return n.href ? (
            <Link key={n.id} href={n.href} aria-label={`Open ${n.label} faceplate`}>
              {inner}
            </Link>
          ) : (
            <g key={n.id}>{inner}</g>
          );
        })}
      </svg>
    </div>
  );
}

function Legend() {
  const items: { label: string; color: string; dashed?: boolean }[] = [
    { label: 'Link up', color: 'var(--success)' },
    { label: 'Degraded', color: 'var(--warning)' },
    { label: 'Fault', color: 'var(--destructive)', dashed: true },
  ];
  return (
    <ul className="flex flex-wrap items-center gap-4 text-xs text-muted-foreground" aria-label="Legend">
      <li className="inline-flex items-center gap-1.5 font-medium text-foreground">
        <Icon name="CursorArrowRaysIcon" size={14} />Click a device to open its faceplate
      </li>
      {items.map((i) => (
        <li key={`lg-${i.label}`} className="inline-flex items-center gap-1.5">
          <svg width="22" height="6" aria-hidden="true">
            <line x1="0" y1="3" x2="22" y2="3" stroke={i.color} strokeWidth="2" strokeDasharray={i.dashed ? '5 3' : undefined} />
          </svg>
          {i.label}
        </li>
      ))}
    </ul>
  );
}

function ErrorBox({ text, onRetry }: { text: string; onRetry: () => void }) {
  return (
    <div role="alert" className="flex items-center justify-between gap-3 rounded-md border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
      <span className="flex items-center gap-2"><Icon name="ExclamationCircleIcon" size={18} />{text}</span>
      <button type="button" onClick={onRetry} className="rounded-md border border-destructive/40 px-3 py-1 text-xs font-semibold">Retry</button>
    </div>
  );
}

function DeviceTopologyPage({ form, deviceKey }: { form: string; deviceKey: string }) {
  const [device, setDevice] = useState<DeviceDetailData | null>(null);
  const [siteDevices, setSiteDevices] = useState<DeviceRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setDevice(null);
    setSiteDevices(null);
    setError(null);
    api
      .getDevice(deviceKey)
      .then((d) => {
        if (cancelled) return;
        setDevice(d);
        const siteKey = isMockMode() ? 3 : d.siteId;
        if (!siteKey) {
          setSiteDevices([]);
          return;
        }
        api
          .listSiteDevices(siteKey)
          .then((rows) => !cancelled && setSiteDevices(rows))
          .catch((cause) => !cancelled && setError(reportLoadError(cause, 'the topology')));
      })
      .catch((cause) => !cancelled && setError(reportLoadError(cause, 'the topology')));
    return () => {
      cancelled = true;
    };
  }, [deviceKey, reload]);

  const devTopo = useMemo(() => (device ? buildDeviceTopology(device) : null), [device]);
  const siteTopo = useMemo(() => {
    if (!device || !siteDevices) return null;
    const merged: DeviceRow[] = siteDevices.map((s) => ({ ...s }));
    const idx = merged.findIndex((s) => s.formFactor === form);
    if (idx >= 0) merged[idx] = { ...merged[idx], hostname: device.hostname, mgmtIp: device.mgmtIp, health: device.health };
    return buildSiteTopology(merged, device.hostname);
  }, [device, siteDevices, form]);

  if (error) {
    return <div className="px-3 sm:px-4"><ErrorBox text={error} onRetry={() => setReload((n) => n + 1)} /></div>;
  }

  return (
    <div className="space-y-3 px-3 sm:px-4">
      <nav aria-label="Breadcrumb" className="flex items-center gap-1.5 px-1 text-xs text-muted-foreground">
        <Link href="/" className="hover:text-foreground hover:underline">Devices</Link>
        <Icon name="ChevronRightIcon" size={12} />
        <Link href={isMockMode() ? `/device-detail?form=${form}` : `/device-detail?id=${encodeURIComponent(device?.id || deviceKey)}&form=${form}`} className="font-mono-data hover:text-foreground hover:underline">{device?.hostname ?? '…'}</Link>
        <Icon name="ChevronRightIcon" size={12} />
        <span className="text-foreground">Topology</span>
      </nav>

      <header className="rounded-none border-x-0 border-y border-border bg-card p-4 shadow-card">
        {device ? (
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex flex-wrap items-center gap-3">
              <h1 className="font-mono-data text-xl font-semibold tracking-tight">{device.hostname}</h1>
              <HealthBadge health={device.health} />
              <span className="font-mono-data text-xs text-muted-foreground">{device.mgmtIp} · {device.modelFamily}</span>
              <span className="font-mono-data text-xs text-muted-foreground">Serial {device.serialMasked}</span>
            </div>
            <Link
              href={isMockMode() ? `/device-detail?form=${form}` : `/device-detail?id=${encodeURIComponent(device?.id || deviceKey)}&form=${form}`}
              className="inline-flex items-center gap-1.5 rounded-md border border-border bg-card px-3 py-2 text-sm font-medium transition-all hover:bg-muted active:scale-95"
            >
              <Icon name="ArrowLeftIcon" size={16} />Back to device
            </Link>
          </div>
        ) : (
          <Skeleton className="h-8 w-96" />
        )}
      </header>

      <section className="rounded-none border-x-0 border-y border-border bg-card shadow-card" aria-labelledby="dev-topo-title">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-4 py-2.5">
          <div>
            <h2 id="dev-topo-title" className="text-base font-semibold">Device topology</h2>
            <p className="text-xs text-muted-foreground">Direct neighbours of this device, learned from LLDP on its ports.</p>
          </div>
          {devTopo && <span className="rounded-full bg-muted px-2 py-0.5 text-xs font-medium tabular text-muted-foreground">{devTopo.links.length} neighbours</span>}
        </div>
        {devTopo ? (
          devTopo.links.length > 0 ? (
            <Diagram nodes={devTopo.nodes} links={devTopo.links} W={devTopo.W} H={devTopo.H} title="Device topology diagram" />
          ) : (
            <p className="p-6 text-sm text-muted-foreground">No neighbours were discovered on this device.</p>
          )
        ) : (
          <div className="p-4"><Skeleton className="h-64 w-full" /></div>
        )}
        <div className="border-t border-border px-4 py-2"><Legend /></div>
      </section>

      <section className="rounded-none border-x-0 border-y border-border bg-card shadow-card" aria-labelledby="site-topo-title">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-4 py-2.5">
          <div>
            <h2 id="site-topo-title" className="text-base font-semibold">Site topology</h2>
            <p className="text-xs text-muted-foreground">
              {device ? (
                <>How this device connects into <Link href="/site-view" className="font-medium hover:text-primary hover:underline">{device.site}</Link>.</>
              ) : (
                'Loading site…'
              )}
            </p>
          </div>
          {siteTopo && <span className="rounded-full bg-muted px-2 py-0.5 text-xs font-medium tabular text-muted-foreground">{siteTopo.nodes.length} nodes</span>}
        </div>
        {siteTopo ? (
          <Diagram nodes={siteTopo.nodes} links={siteTopo.links} W={siteTopo.W} H={siteTopo.H} title="Site topology diagram" />
        ) : (
          <div className="p-4"><Skeleton className="h-72 w-full" /></div>
        )}
        <div className="border-t border-border px-4 py-2"><Legend /></div>
      </section>

      {isMockMode() ? <ExampleDataBanner text="Topology links are simulated example data. No live discovery is run." /> : null}
    </div>
  );
}

function SiteTopologyPage({ site, onBack }: { site: SiteRow; onBack: () => void }) {
  const [devices, setDevices] = useState<DeviceRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setDevices(null);
    setError(null);
    api
      .listSiteDevices(site.id)
      .then((d) => !cancelled && setDevices(d))
      .catch((cause) => !cancelled && setError(reportLoadError(cause, 'the topology for this site')));
    return () => {
      cancelled = true;
    };
  }, [site.id, reload]);

  const topo = useMemo(() => (devices ? buildSiteTopology(devices) : null), [devices]);

  return (
    <div className="space-y-3 px-3 sm:px-4">
      <nav aria-label="Breadcrumb" className="flex items-center gap-1.5 px-1 text-xs text-muted-foreground">
        <button type="button" onClick={onBack} className="hover:text-foreground hover:underline">Topology</button>
        <Icon name="ChevronRightIcon" size={12} />
        <span className="text-foreground">{site.name}</span>
      </nav>

      <header className="rounded-none border-x-0 border-y border-border bg-card p-4 shadow-card">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-xl font-semibold tracking-tight">{site.name}</h1>
            <HealthBadge health={site.health} />
            <span className="text-xs text-muted-foreground">{site.region} · {site.deviceCount} devices</span>
          </div>
          <button
            type="button"
            onClick={onBack}
            className="inline-flex items-center gap-1.5 rounded-md border border-border bg-card px-3 py-2 text-sm font-medium transition-all hover:bg-muted active:scale-95"
          >
            <Icon name="ArrowLeftIcon" size={16} />All sites
          </button>
        </div>
      </header>

      <section className="rounded-none border-x-0 border-y border-border bg-card shadow-card" aria-labelledby="site-only-title">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-4 py-2.5">
          <div>
            <h2 id="site-only-title" className="text-base font-semibold">Site topology</h2>
            <p className="text-xs text-muted-foreground">How the devices at this site connect to each other.</p>
          </div>
          {topo && <span className="rounded-full bg-muted px-2 py-0.5 text-xs font-medium tabular text-muted-foreground">{topo.nodes.length} nodes</span>}
        </div>
        {error ? (
          <div className="p-4"><ErrorBox text={error} onRetry={() => setReload((n) => n + 1)} /></div>
        ) : topo ? (
          <Diagram nodes={topo.nodes} links={topo.links} W={topo.W} H={topo.H} title={`Topology of ${site.name}`} />
        ) : (
          <div className="p-4"><Skeleton className="h-72 w-full" /></div>
        )}
        <div className="border-t border-border px-4 py-2"><Legend /></div>
      </section>

      {isMockMode() ? <ExampleDataBanner text="Topology links are simulated example data. No live discovery is run." /> : null}
    </div>
  );
}

export default function TopologyView() {
  const searchParams = useSearchParams();
  const q = searchParams?.get('form') ?? null;
  const form = q && FORMS.includes(q) ? q : null;
  const id = searchParams?.get('id');
  const [site, setSite] = useState<SiteRow | null>(null);

  if (!isMockMode() && id) return <DeviceTopologyPage form={form ?? 'switch-stack'} deviceKey={id} />;
  if (form) return <DeviceTopologyPage form={form} deviceKey={form} />;
  if (site) return <SiteTopologyPage site={site} onBack={() => setSite(null)} />;
  return (
    <div className="px-3 sm:px-4">
      <TopologySiteList onPick={setSite} />
    </div>
  );
}
