'use client';

import React, { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import Icon from '@/components/ui/AppIcon';
import ExampleDataBanner from '@/components/ui/ExampleDataBanner';
import { HealthBadge } from '@/components/ui/Badge';
import { Skeleton } from '@/components/ui/Skeleton';
import { api } from '@/lib/apiClient';
import { reportLoadError } from '@/lib/loadError';
import { isMockMode } from '@/lib/apiMode';
import { deviceHealthPath } from '@/lib/deviceHealthPath';
import { useKeyedLoad } from '@/lib/useKeyedLoad';
import { usePageQuery } from '@/lib/usePageQuery';
import { FACEPLATE_SAMPLES } from '@/lib/mockData';
import type { DeviceDetailData, DeviceHealth, DeviceRow, SiteRow } from '@/lib/types';
import DeviceArt, { ArtDefs } from '@/app/topology/components/DeviceArt';
import TopologySiteList from '@/app/topology/components/TopologySiteList';
import { buildDeviceTopology, buildHierarchyTopology, buildSiteTopology, deviceNodeHref, type TopoLink, type TopoNode } from '@/app/topology/components/topologyLinks';
import type { HierarchyReport } from '@/lib/types';

const FORMS = Object.keys(FACEPLATE_SAMPLES);
const NODE_W = 128;
const NODE_H = 40;

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
              {n.healthHref ? null : (
                <circle cx={n.x + ringW / 2 - 4} cy={n.y - NODE_H / 2 - 1} r="5" fill={HEALTH_STROKE[n.health]} stroke="var(--card)" strokeWidth="1.5" />
              )}
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
          const dot = (
            <circle cx={n.x + ringW / 2 - 4} cy={n.y - NODE_H / 2 - 1} r="8" fill={HEALTH_STROKE[n.health]} stroke="var(--card)" strokeWidth="1.5" />
          );
          const body = n.href ? (
            <Link key={n.id} href={n.href} aria-label={`Open ${n.label} faceplate`}>
              {inner}
            </Link>
          ) : (
            <g key={n.id}>{inner}</g>
          );
          return (
            <g key={`node-${n.id}`}>
              {body}
              {n.healthHref ? (
                <Link href={n.healthHref} aria-label={`Open health for ${n.label}`}>
                  {dot}
                </Link>
              ) : null}
            </g>
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
  const [reload, setReload] = useState(0);
  const loaded = useKeyedLoad(deviceKey, true, reload, 'the topology', async (key) => {
    const device = await api.getDevice(key);
    const siteKey = isMockMode() ? 3 : device.siteId;
    const siteDevices = siteKey ? await api.listSiteDevices(siteKey) : [];
    const tree = await api.getHierarchy().catch(() => null);
    return { device, siteDevices, tree };
  });
  const device = loaded.data?.device ?? null;
  const siteDevices = loaded.data?.siteDevices ?? null;
  const tree = loaded.data?.tree ?? null;
  const error = loaded.error;

  const live = !isMockMode();
  const healthById = useMemo(() => {
    const map: Record<string, DeviceRow['health']> = {};
    for (const row of siteDevices ?? []) map[row.id] = row.health;
    if (device?.id) map[device.id] = device.health;
    return map;
  }, [siteDevices, device]);
  const devTopo = useMemo(() => {
    if (device && tree?.nodes?.length) {
      const laid = buildHierarchyTopology(tree.nodes, live, { focusId: device.id, currentHostname: device.hostname, healthById });
      if (laid) return laid;
    }
    return device ? buildDeviceTopology(device, siteDevices ?? [], live) : null;
  }, [device, siteDevices, tree, live, healthById]);
  const siteTopo = useMemo(() => {
    if (!device || !siteDevices) return null;
    if (tree?.nodes?.length) {
      const laid = buildHierarchyTopology(tree.nodes, live, {
        onlyIds: siteDevices.map((row) => row.id),
        currentHostname: device.hostname,
        healthById,
      });
      if (laid) return laid;
    }
    const merged: DeviceRow[] = siteDevices.map((s) => ({ ...s }));
    const idx = merged.findIndex((s) => (device.id ? s.id === device.id : s.formFactor === form));
    if (idx >= 0) merged[idx] = { ...merged[idx], hostname: device.hostname, mgmtIp: device.mgmtIp, health: device.health, formFactor: device.faceplate.form_factor };
    return buildSiteTopology(merged, live, device.hostname);
  }, [device, siteDevices, form, live, tree, healthById]);

  if (error) {
    return <div className="px-3 sm:px-4"><ErrorBox text={error} onRetry={() => setReload((n) => n + 1)} /></div>;
  }

  return (
    <div className="space-y-3 px-3 sm:px-4">
      <nav aria-label="Breadcrumb" className="flex items-center gap-1.5 px-1 text-xs text-muted-foreground">
        <Link href="/" className="hover:text-foreground hover:underline">Devices</Link>
        <Icon name="ChevronRightIcon" size={12} />
        <Link href={deviceNodeHref(!isMockMode(), device?.id || deviceKey, form) || '/'} className="font-mono-data hover:text-foreground hover:underline">{device?.hostname ?? '…'}</Link>
        <Icon name="ChevronRightIcon" size={12} />
        <span className="text-foreground">Topology</span>
      </nav>

      <header className="rounded-none border-x-0 border-y border-border bg-card p-4 shadow-card">
        {device ? (
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex flex-wrap items-center gap-3">
              <h1 className="font-mono-data text-xl font-semibold tracking-tight">{device.hostname}</h1>
              <HealthBadge health={device.health} href={deviceHealthPath(device.id || deviceKey, device.faceplate.form_factor, device.health)} />
              <span className="font-mono-data text-xs text-muted-foreground">{device.mgmtIp} · {device.modelFamily}</span>
              <span className="font-mono-data text-xs text-muted-foreground">Serial {device.serialMasked}</span>
            </div>
            <Link
              href={deviceNodeHref(!isMockMode(), device?.id || deviceKey, form) || '/'}
              className="inline-flex items-center gap-1.5 rounded-md border border-border bg-card px-3 py-2 text-sm font-medium transition-all hover:bg-muted active:scale-95"
            >
              <Icon name="ArrowLeftIcon" size={16} />Back to device
            </Link>
          </div>
        ) : (
          <div>
            <p role="status" className="sr-only">Loading device</p>
            <Skeleton className="h-8 w-96" />
          </div>
        )}
      </header>

      <section className="rounded-none border-x-0 border-y border-border bg-card shadow-card" aria-labelledby="dev-topo-title">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-4 py-2.5">
          <div>
            <h2 id="dev-topo-title" className="text-base font-semibold">Device topology</h2>
            <p className="text-xs text-muted-foreground">
              {tree?.nodes?.length ? 'Parent above and children below, from CDP and LLDP.' : 'Direct neighbours of this device, learned from LLDP on its ports.'}
            </p>
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
  const [tree, setTree] = useState<HierarchyReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setDevices(null);
    setTree(null);
    setError(null);
    api
      .listSiteDevices(site.id)
      .then(async (d) => {
        if (cancelled) return;
        setDevices(d);
        const hierarchy = await api.getHierarchy().catch(() => null);
        if (!cancelled) setTree(hierarchy);
      })
      .catch((cause) => !cancelled && setError(reportLoadError(cause, 'the topology for this site')));
    return () => {
      cancelled = true;
    };
  }, [site.id, reload]);

  const topo = useMemo(() => {
    if (!devices) return null;
    const live = !isMockMode();
    if (tree?.nodes?.length) {
      const healthById: Record<string, DeviceRow['health']> = {};
      for (const row of devices) healthById[row.id] = row.health;
      const laid = buildHierarchyTopology(tree.nodes, live, { onlyIds: devices.map((row) => row.id), healthById });
      if (laid) return laid;
    }
    return buildSiteTopology(devices, live);
  }, [devices, tree]);

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
  const { ready, params } = usePageQuery('/topology');
  const q = params.get('form');
  const form = q && FORMS.includes(q) ? q : null;
  const id = params.get('id');
  const [site, setSite] = useState<SiteRow | null>(null);

  if (!ready) {
    return (
      <div className="px-3 sm:px-4 py-4" role="status">
        <p className="sr-only">Loading topology</p>
        <Skeleton className="h-72 w-full" />
      </div>
    );
  }

  if (!isMockMode() && id) return <DeviceTopologyPage form={form ?? 'generic'} deviceKey={id} />;
  if (isMockMode() && form) return <DeviceTopologyPage form={form} deviceKey={form} />;
  if (site) return <SiteTopologyPage site={site} onBack={() => setSite(null)} />;
  return (
    <div className="px-3 sm:px-4">
      <TopologySiteList onPick={setSite} />
    </div>
  );
}
