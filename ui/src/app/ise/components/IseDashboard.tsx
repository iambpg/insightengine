'use client';

import React, { useCallback, useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import Link from 'next/link';
import Icon from '@/components/ui/AppIcon';
import { api } from '@/lib/apiClient';
import { isApiError } from '@/lib/apiError';
import UsageGauge from '@/components/ui/UsageGauge';
import { ServiceDrawer, ServiceTooltip, serviceBrief, type ServiceCheckOps } from './ServiceCheck';

type Service = { name: string; running?: boolean };

type Node = {
  hostname: string;
  fqdn?: string;
  ip?: string;
  status?: string;
  healthy?: boolean;
  group?: string;
  roles?: string[];
  cpu?: number | null;
  memory?: number | null;
  diskRoot?: number | null;
  diskOpt?: number | null;
  services?: Service[];
  issues?: string[];
  ntp?: boolean | null;
  directory?: boolean | null;
};

type SessionRow = { user?: string; mac?: string; client?: string; nas?: string; server?: string };
type CountRow = { name: string; count?: number | null };
type DependencyRow = { name: string; status?: string; detail?: string };
type Attention = { name: string; days?: number; date?: string };
type Dependency = { name: string; status?: string; detail?: string; rows?: DependencyRow[]; attention?: Attention[] };
type Alarm = { name: string; severity?: string };

type Operations = {
  configured?: boolean;
  message?: string;
  sessions?: { active?: number | null; windowMinutes?: number; recent?: number | null; rows?: SessionRow[]; message?: string };
  inventory?: CountRow[];
  directories?: { name?: string; domain?: string }[];
  dependencies?: Dependency[];
  alarms?: { available?: boolean; message?: string; rows?: Alarm[] };
};

type Health = {
  configured?: boolean;
  ok?: boolean;
  message?: string;
  version?: string;
  activeSessions?: number | null;
  nodes?: Node[];
};

function count(nodes: Node[], group: string, healthyOnly = false): number {
  return nodes.filter((node) => node.group === group && (!healthyOnly || node.healthy)).length;
}

export default function IseDashboard() {
  const [data, setData] = useState<Health | null>(null);
  const [ops, setOps] = useState<Operations | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    setLoading(true);
    setError('');
    Promise.all([
      api.netbridgeGet('/ise/health'),
      api.netbridgeGet('/ise/operations').catch(() => null),
    ])
      .then(([health, operations]) => {
        setData(health as Health);
        setOps(operations as Operations | null);
      })
      .catch((cause) => setError(isApiError(cause) ? cause.message : 'ISE could not be loaded.'))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const nodes = data?.nodes ?? [];
  const main = nodes.filter((node) => node.group === 'main');
  const policy = nodes.filter((node) => node.group !== 'main');
  const healthy = nodes.filter((node) => node.healthy).length;

  if (!loading && data && data.configured === false) {
    return (
      <div className="px-4">
        <h1 className="text-2xl font-semibold tracking-tight">ISE</h1>
        <p className="mt-3 max-w-2xl rounded-md border border-border bg-card px-4 py-3 text-sm">
          {data.message || 'Add the ISE URL, username, and password in Settings → Vault.'}{' '}
          <Link href="/settings" className="font-semibold text-primary underline">
            Open Vault
          </Link>
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-5 px-4">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">ISE</h1>
          <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
            Sessions, configuration inventory, node health, and the DNS, time, directory, reachability, and certificate checks. Click a node for the full reading.
          </p>
        </div>
        <button type="button" onClick={load} className="rounded-md border border-border bg-card px-3 py-1.5 text-sm">
          Refresh
        </button>
      </header>

      {error ? <p role="alert" className="rounded-md border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">{error}</p> : null}
      {data?.message ? <p className="rounded-md border border-warning/40 bg-warning/10 px-4 py-3 text-sm">{data.message}</p> : null}

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Stat label="Active sessions" value={loading ? '…' : data?.activeSessions ?? '—'} note="Authentications ISE is holding" />
        <Stat label="ISE version" value={loading ? '…' : data?.version || '—'} note="Monitoring node" />
        <Stat
          label="Nodes healthy"
          value={loading ? '…' : nodes.length ? `${healthy} of ${nodes.length}` : '—'}
          note="Connected to the deployment"
        />
        <Stat
          label="Policy nodes"
          value={loading ? '…' : nodes.length ? `${count(nodes, 'policy', true)} of ${count(nodes, 'policy')}` : '—'}
          note="Session and device administration"
        />
      </div>

      <Dependencies ops={ops} nodes={nodes} loading={loading} />
      <Sessions ops={ops} loading={loading} />
      <Inventory ops={ops} loading={loading} />

      <section aria-label="Node health" className="space-y-5">
        <div>
          <h2 className="text-base font-semibold">Node health</h2>
          <p className="text-sm text-muted-foreground">
            CPU, memory, disk, application services, and deployment issues from SNMP and the deployment API.
            {ops?.alarms?.available ? '' : ` ${ops?.alarms?.message || ''}`.trimEnd()}
          </p>
          {(ops?.alarms?.rows || []).length > 0 ? (
            <ul className="mt-2 space-y-1">
              {(ops?.alarms?.rows || []).map((alarm) => (
                <li key={alarm.name} className="text-sm text-warning">{alarm.severity ? `${alarm.severity}: ` : ''}{alarm.name}</li>
              ))}
            </ul>
          ) : null}
        </div>
        <NodeGroup title="Main nodes" note="Administration and monitoring." nodes={main} loading={loading} ops={ops} />
        <NodeGroup title="Policy nodes" note="The nodes that handle authentications." nodes={policy} loading={loading} ops={ops} />
      </section>
    </div>
  );
}

function sessionMessage(message?: string): string {
  if (!message || message.includes('pass or fail')) return '';
  return message;
}

function shown(value?: number | null): string {
  if (value == null || Number.isNaN(value)) return '—';
  return value.toLocaleString('en-US');
}

function Sessions({ ops, loading }: { ops: Operations | null; loading: boolean }) {
  const sessions = ops?.sessions;
  const rows = sessions?.rows || [];
  return (
    <section aria-label="Sessions" className="space-y-3">
      <div>
        <h2 className="text-base font-semibold">Sessions</h2>
        <p className="text-sm text-muted-foreground">Active sessions, plus authentications from the last {sessions?.windowMinutes || 30} minutes.</p>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <Stat label="Active now" value={loading ? '…' : shown(sessions?.active)} note="Sessions ISE is holding" />
        <Stat label="Last 30 minutes" value={loading ? '…' : shown(sessions?.recent)} note="Authentications returned by the monitoring API" />
      </div>
      {sessionMessage(sessions?.message) ? <p className="text-sm text-muted-foreground">{sessionMessage(sessions?.message)}</p> : null}
      {!loading && rows.length === 0 ? <p className="text-sm text-muted-foreground">No session rows in this window.</p> : null}
      {rows.length > 0 ? (
        <div className="overflow-x-auto rounded-md border border-border bg-card">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-muted-foreground">
                <th className="px-3 py-2 font-medium">User</th>
                <th className="px-3 py-2 font-medium">Client</th>
                <th className="px-3 py-2 font-medium">Switch</th>
                <th className="px-3 py-2 font-medium">Policy node</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row, index) => (
                <tr key={`${row.user || ''}-${row.mac || ''}-${index}`} className="border-b border-border last:border-0">
                  <td className="px-3 py-2">{row.user || '—'}</td>
                  <td className="px-3 py-2 font-mono-data text-xs">{row.client || row.mac || '—'}</td>
                  <td className="px-3 py-2 font-mono-data text-xs">{row.nas || '—'}</td>
                  <td className="px-3 py-2">{row.server || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </section>
  );
}

function Inventory({ ops, loading }: { ops: Operations | null; loading: boolean }) {
  const rows = ops?.inventory || [];
  return (
    <section aria-label="Configuration and inventory" className="space-y-3">
      <div>
        <h2 className="text-base font-semibold">Configuration and inventory</h2>
        <p className="text-sm text-muted-foreground">Counts from the configuration API. Endpoint records are not downloaded.</p>
      </div>
      {loading ? <p className="text-sm text-muted-foreground">Loading inventory…</p> : null}
      {!loading && rows.length === 0 ? <p className="text-sm text-muted-foreground">No inventory counts were returned.</p> : null}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {rows.map((row) => (
          <div key={row.name} className="rounded-md border border-border bg-card p-4 shadow-card">
            <p className="text-xs uppercase tracking-wide text-muted-foreground">{row.name}</p>
            <p className="mt-1 text-2xl font-semibold tabular">{shown(row.count)}</p>
          </div>
        ))}
      </div>
    </section>
  );
}

function tally(nodes: Node[], key: 'ntp' | 'directory'): { known: number; up: number } {
  const known = nodes.filter((node) => typeof node[key] === 'boolean');
  return { known: known.length, up: known.filter((node) => node[key]).length };
}

function nodeLines(nodes: Node[], key: 'ntp' | 'directory', running: string, stopped: string): DependencyRow[] {
  return nodes.map((node) => {
    const value = node[key];
    if (typeof value !== 'boolean') {
      return { name: node.hostname, status: 'unknown', detail: 'Not read from this node.' };
    }
    return { name: node.hostname, status: value ? 'ok' : 'warning', detail: value ? running : stopped };
  });
}

function Dependencies({ ops, nodes, loading }: { ops: Operations | null; nodes: Node[]; loading: boolean }) {
  const [selected, setSelected] = useState<string>('');
  const supplied = Object.fromEntries((ops?.dependencies || []).map((row) => [row.name, row]));
  const ntp = tally(nodes, 'ntp');
  const directory = tally(nodes, 'directory');
  const ad = supplied['Active Directory'];
  const client = directory.known === 0
    ? 'The directory client was not read from the nodes.'
    : `The directory client is running on ${directory.up} of ${directory.known} nodes.`;
  const rows: Dependency[] = [
    supplied.DNS || { name: 'DNS', status: 'unknown', detail: loading ? 'Checking DNS…' : 'DNS was not checked.' },
    {
      name: 'NTP',
      status: ntp.known === 0 ? 'unknown' : ntp.up === ntp.known ? 'ok' : 'warning',
      detail: ntp.known === 0 ? 'NTP was not read from the nodes.' : `NTP client is running on ${ntp.up} of ${ntp.known} nodes.`,
      rows: nodeLines(nodes, 'ntp', 'NTP client is running.', 'NTP client is not running.'),
    },
    {
      name: 'Active Directory',
      status: ad?.status === 'warning' || ad?.status === 'unknown' ? ad.status : directory.known && directory.up < directory.known ? 'warning' : ad?.status || 'unknown',
      detail: [ad?.detail, client].filter(Boolean).join(' '),
      rows: nodeLines(nodes, 'directory', 'Directory client is running.', 'Directory client is not running.'),
    },
    supplied.Reachability || { name: 'Reachability', status: 'unknown', detail: loading ? 'Checking reachability…' : 'Reachability was not checked.' },
    supplied.Certificates || { name: 'Certificates', status: 'unknown', detail: loading ? 'Checking certificates…' : 'Certificates were not checked.' },
  ];
  const open = rows.find((row) => row.name === selected) || null;
  return (
    <section aria-label="Dependencies" className="space-y-3">
      <div>
        <h2 className="text-base font-semibold">Dependencies</h2>
        <p className="text-sm text-muted-foreground">Click a check to open it. DNS and reachability are checked from InsightEngine. NTP and the directory client come from each node.</p>
      </div>
      <div className="grid gap-3 lg:grid-cols-2">
        {rows.map((row) => (
          <button
            key={row.name}
            type="button"
            aria-label={`Open ${row.name}`}
            onClick={() => setSelected(row.name)}
            className={`flex w-full items-start justify-between gap-3 rounded-md border bg-card p-4 text-left shadow-card transition-colors hover:border-primary ${selected === row.name ? 'border-primary' : 'border-border'}`}
          >
            <div>
              <h3 className="text-sm font-semibold">{row.name}</h3>
              <p className="mt-1 text-sm text-muted-foreground">{row.detail}</p>
            </div>
            <Status status={row.status || 'unknown'} />
          </button>
        ))}
      </div>
      {open ? <DependencyDrawer row={open} directories={ops?.directories || []} onClose={() => setSelected('')} /> : null}
    </section>
  );
}

function DependencyDrawer({ row, directories, onClose }: { row: Dependency; directories: { name?: string; domain?: string }[]; onClose: () => void }) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);
  const lines = drawerLines(row);
  if (typeof document === 'undefined') return null;
  return createPortal(
    <>
      <button type="button" aria-label="Close dependency" className="fixed inset-0 z-[80] bg-black/20" onClick={onClose} />
      <div className="drawer-in-left fixed inset-y-0 left-0 z-[90] flex w-full max-w-[420px] flex-col overflow-y-auto border-r border-border bg-card shadow-2xl" role="dialog" aria-modal="false" aria-label={row.name}>
        <header className="flex items-start justify-between gap-3 p-4">
          <div>
            <p className="text-xs uppercase tracking-wide text-muted-foreground">Dependency</p>
            <h2 className="text-xl font-semibold">{row.name}</h2>
          </div>
          <button type="button" onClick={onClose} aria-label="Close dependency panel" className="rounded-md p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground">
            <Icon name="XMarkIcon" size={18} />
          </button>
        </header>
        <div className="space-y-4 px-4 pb-6">
          <div className="flex items-start justify-between gap-3">
            <p className="text-sm text-muted-foreground">{row.detail}</p>
            <Status status={row.status || 'unknown'} />
          </div>
          {row.name === 'Active Directory' && directories.length > 0 ? (
            <ul className="space-y-2">
              {directories.map((directory) => (
                <li key={`${directory.name}-${directory.domain}`} className="rounded-md border border-border px-3 py-2 text-sm">
                  <span className="font-medium">{directory.name || 'Directory'}</span>
                  {directory.domain ? <span className="text-muted-foreground"> · {directory.domain}</span> : null}
                </li>
              ))}
            </ul>
          ) : null}
          {lines.length === 0 ? <p className="text-sm text-muted-foreground">No further detail for this check.</p> : (
            <ul className="space-y-2">
              {lines.map((line) => (
                <li key={`${line.name}-${line.detail}`} className="flex items-start justify-between gap-3 rounded-md border border-border px-3 py-2">
                  <div>
                    <p className="text-sm font-medium">{line.name}</p>
                    <p className="text-sm text-muted-foreground">{line.detail}</p>
                  </div>
                  <Status status={line.status || 'unknown'} />
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </>,
    document.body,
  );
}

function drawerLines(row: Dependency): DependencyRow[] {
  if (row.name === 'Certificates') {
    return (row.attention || []).map((item) => ({
      name: item.name,
      status: 'warning',
      detail: item.days != null && item.days < 0
        ? `Expired ${Math.abs(item.days)} days ago${item.date ? ` · ${item.date}` : ''}`
        : `Expires in ${item.days ?? '—'} days${item.date ? ` · ${item.date}` : ''}`,
    }));
  }
  return row.rows || [];
}

function Status({ status }: { status: string }) {
  const ok = status === 'ok';
  const warning = status === 'warning';
  const label = ok ? 'OK' : warning ? 'Check' : 'Unknown';
  const tone = ok ? 'bg-success/10 text-success' : warning ? 'bg-warning/15 text-foreground' : 'bg-muted text-muted-foreground';
  return <span className={`inline-flex shrink-0 rounded-full px-2.5 py-0.5 text-xs font-semibold ${tone}`}>{label}</span>;
}

function NodePanel({ node, ops }: { node: Node; ops: Operations | null }) {
  const [open, setOpen] = useState(false);
  const [hover, setHover] = useState<{ name: string; anchor: DOMRect } | null>(null);
  const [selected, setSelected] = useState('');
  const serviceOps: ServiceCheckOps = {
    sessions: ops?.sessions,
    directories: ops?.directories,
    dependencies: ops?.dependencies,
    alarms: ops?.alarms,
  };
  const hovered = hover ? serviceBrief(hover.name, (node.services || []).find((service) => service.name === hover.name)?.running, node, serviceOps) : null;
  const chosen = selected ? serviceBrief(selected, (node.services || []).find((service) => service.name === selected)?.running, node, serviceOps) : null;
  return (
    <article className="overflow-hidden rounded-md border border-border bg-card shadow-card">
      <div className="flex items-start justify-between gap-3 p-4">
        <button
          type="button"
          aria-expanded={open}
          aria-label={`${open ? 'Collapse' : 'Expand'} ${node.hostname}`}
          onClick={() => setOpen((value) => !value)}
          className="flex min-w-0 flex-1 items-start gap-3 text-left"
        >
          <Icon name={open ? 'ChevronDownIcon' : 'ChevronRightIcon'} size={18} className="mt-0.5 shrink-0" />
          <span className="min-w-0">
            <h3 className="text-base font-semibold">{node.hostname}</h3>
            <p className="font-mono-data text-xs text-muted-foreground">{node.ip || node.fqdn || 'No address'}</p>
            <ul className="mt-2 flex flex-wrap gap-1.5">
              {(node.roles || []).map((role) => (
                <li key={role} className="rounded-md bg-muted px-2 py-0.5 text-xs">{role}</li>
              ))}
            </ul>
          </span>
        </button>
        <div className="flex shrink-0 items-center gap-2">
          <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-semibold ${node.healthy ? 'bg-success/10 text-success' : 'bg-warning/15 text-foreground'}`}>
            <span className={`h-2 w-2 rounded-full ${node.healthy ? 'bg-success' : 'bg-warning'}`} />
            {node.healthy ? 'Healthy' : node.status || 'Unknown'}
          </span>
          <Link href={`/ise/${encodeURIComponent(node.hostname)}`} aria-label={`Open ${node.hostname}`} className="text-sm font-medium text-primary">
            Details
          </Link>
        </div>
      </div>
      {open ? (
        <div className="grid grid-cols-[auto_minmax(0,1fr)_minmax(0,1fr)] border-t border-border">
          <section aria-label={`${node.hostname} gauges`} className="flex flex-col border-r border-border p-3">
            <h4 className="text-sm font-medium uppercase tracking-wide text-muted-foreground">Gauges</h4>
            <div className="mt-3 flex flex-nowrap items-start gap-2">
              <UsageGauge size="lg" label="CPU" value={node.cpu} />
              <UsageGauge size="lg" label="Memory" value={node.memory} />
              <UsageGauge size="lg" label="Disk /" value={node.diskRoot} />
              <UsageGauge size="lg" label="Disk /opt" value={node.diskOpt} />
            </div>
          </section>
          <section aria-label={`${node.hostname} application services`} className="flex flex-col border-r border-border p-3">
            <h4 className="text-sm font-medium uppercase tracking-wide text-muted-foreground">Application services</h4>
            {(node.services || []).length === 0 ? (
              <p className="mt-3 text-sm text-muted-foreground">No service status</p>
            ) : (
              <ul className="mt-3 flex flex-wrap content-start gap-1.5">
                {(node.services || []).map((service) => (
                  <li key={service.name}>
                    <button
                      type="button"
                      aria-label={`Open ${service.name} on ${node.hostname}`}
                      onMouseEnter={(event) => setHover({ name: service.name, anchor: event.currentTarget.getBoundingClientRect() })}
                      onMouseLeave={() => setHover(null)}
                      onFocus={(event) => setHover({ name: service.name, anchor: event.currentTarget.getBoundingClientRect() })}
                      onBlur={() => setHover(null)}
                      onClick={() => {
                        setHover(null);
                        setSelected(service.name);
                      }}
                      className={`rounded-md border px-2.5 py-1 text-base font-semibold leading-tight hover:border-primary ${service.running === false ? 'bg-warning/15 text-foreground' : 'bg-success/10 text-success'} ${selected === service.name ? 'border-primary' : service.running === false ? 'border-warning/40' : 'border-success/30'}`}
                    >
                      {service.name}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </section>
          <section aria-label={`${node.hostname} deployment issues`} className="flex flex-col p-3">
            <h4 className="text-sm font-medium uppercase tracking-wide text-muted-foreground">Deployment issues</h4>
            {(node.issues || []).length === 0 ? (
              <p className="mt-3 text-base text-muted-foreground">No deployment issues</p>
            ) : (
              <ul className="mt-3 space-y-2">
                {(node.issues || []).map((issue) => (
                  <li key={issue} className="text-base text-warning">{issue}</li>
                ))}
              </ul>
            )}
          </section>
        </div>
      ) : null}
      {hovered && hover ? <ServiceTooltip brief={hovered} anchor={hover.anchor} /> : null}
      {chosen ? <ServiceDrawer brief={chosen} node={node} onClose={() => setSelected('')} /> : null}
    </article>
  );
}

function Stat({ label, value, note }: { label: string; value: string | number; note: string }) {
  return (
    <div className="rounded-md border border-border bg-card p-4 shadow-card">
      <p className="text-xs uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className="mt-1 text-2xl font-semibold tabular">{value}</p>
      <p className="mt-1 text-xs text-muted-foreground">{note}</p>
    </div>
  );
}

function NodeGroup({ title, note, nodes, loading, ops }: { title: string; note: string; nodes: Node[]; loading: boolean; ops: Operations | null }) {
  return (
    <section aria-label={title} className="space-y-3">
      <div>
        <h2 className="text-base font-semibold">{title}</h2>
        <p className="text-sm text-muted-foreground">{note}</p>
      </div>
      {loading ? <p className="text-sm text-muted-foreground">Loading nodes…</p> : null}
      {!loading && nodes.length === 0 ? <p className="text-sm text-muted-foreground">No nodes in this group.</p> : null}
      <div className="space-y-3">
        {nodes.map((node) => (
          <NodePanel key={node.hostname} node={node} ops={ops} />
        ))}
      </div>
    </section>
  );
}
