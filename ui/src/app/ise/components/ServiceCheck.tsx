'use client';

import React, { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import Icon from '@/components/ui/AppIcon';

export type ServiceCheckNode = {
  hostname: string;
  ip?: string;
  status?: string;
  roles?: string[];
  cpu?: number | null;
  memory?: number | null;
  diskRoot?: number | null;
  diskOpt?: number | null;
  issues?: string[];
  ntp?: boolean | null;
  directory?: boolean | null;
};

export type ServiceCheckOps = {
  sessions?: { active?: number | null; windowMinutes?: number; recent?: number | null };
  directories?: { name?: string; domain?: string }[];
  dependencies?: { name: string; status?: string; detail?: string; attention?: { name?: string; days?: number }[] }[];
  alarms?: { available?: boolean; message?: string; rows?: { name?: string; severity?: string }[] };
};

type Check = { look: string; finding: string; known: boolean };

export type ServiceBrief = {
  name: string;
  why: string;
  running?: boolean;
  checks: Check[];
};

const PROCESS: Record<string, string> = {
  'Application Server': 'java',
  Web: 'nginx',
  Database: 'oracle',
  Cache: 'redis-server',
  Messaging: 'rabbitmq',
  'API database': 'postgres',
  Containers: 'docker',
  Metrics: 'ise-prometheus',
  NTP: 'chronyd or ntpd',
  Directory: 'sssd or winbindd',
};

const WHY: Record<string, string> = {
  'Application Server': 'Core ISE functionality. Problems can affect policy processing and administration.',
  Web: 'Admin, guest, and other web portals may become unavailable.',
  Database: 'Configuration, reporting, or authentication-related operations may be affected.',
  Cache: 'Cache problems can affect performance. Detailed hit and miss counters are not available through the public APIs.',
  Messaging: 'Internal services and nodes depend on messaging.',
  'API database': 'Problems can affect API gateway operation.',
  Containers: 'Some ISE components depend on container infrastructure. This check does not open Docker on the node.',
  Metrics: 'A failed collector can leave you with missing or stale monitoring data.',
  NTP: 'Incorrect time can break authentication, certificate validation, and log correlation.',
  Directory: 'Directory problems can cause user authentication failures.',
};

const NOT_ERRORS = 'ISE did not expose error counters for this service on the APIs this page can read.';
const NOT_RESTARTS = 'Restart counts are not in the SNMP process list.';

function runningFinding(name: string, running?: boolean): string {
  const process = PROCESS[name];
  const who = process ? `The ${process} process` : 'This service';
  if (running === true) return `${who} is running on this node.`;
  if (running === false) return `${who} was not running on this node.`;
  return 'SNMP did not return a process list for this node.';
}

function resourceFinding(node: ServiceCheckNode): string {
  const parts: string[] = [];
  if (node.cpu != null) parts.push(`CPU ${node.cpu}%`);
  if (node.memory != null) parts.push(`memory ${node.memory}%`);
  if (node.diskRoot != null) parts.push(`disk / ${node.diskRoot}%`);
  if (node.diskOpt != null) parts.push(`disk /opt ${node.diskOpt}%`);
  if (parts.length === 0) return 'This node has no CPU, memory, or disk reading from SNMP.';
  const pressure = (node.issues || []).filter((issue) => /cpu|memory|disk/i.test(issue));
  return pressure.length ? `${parts.join(', ')}. ${pressure.join(' ')}` : `${parts.join(', ')}.`;
}

function storageFinding(node: ServiceCheckNode): string {
  const disks: string[] = [];
  if (node.diskRoot != null) disks.push(`Root disk is ${node.diskRoot}% used`);
  if (node.diskOpt != null) disks.push(`Application disk /opt is ${node.diskOpt}% used`);
  if (disks.length === 0) return 'SNMP did not return disk usage for this node.';
  const high = [node.diskRoot, node.diskOpt].some((value) => value != null && value >= 90);
  return `${disks.join('. ')}. ${high ? 'That is storage pressure.' : 'Both are under 90%.'}`;
}

function sessionFinding(ops?: ServiceCheckOps): string {
  const sessions = ops?.sessions;
  if (sessions?.active == null && sessions?.recent == null) return 'Session counts were not loaded for this deployment.';
  const window = sessions.windowMinutes || 30;
  const active = sessions.active == null ? '—' : sessions.active.toLocaleString('en-US');
  const recent = sessions.recent == null ? '—' : sessions.recent.toLocaleString('en-US');
  return `${active} active sessions. ${recent} authentications in the last ${window} minutes, across the deployment.`;
}

function dependency(ops: ServiceCheckOps | undefined, name: string) {
  return (ops?.dependencies || []).find((row) => row.name === name);
}

function httpsFinding(node: ServiceCheckNode, ops?: ServiceCheckOps): string {
  const status = (node.status || '').toLowerCase() === 'connected'
    ? `${node.hostname} is Connected in the deployment.`
    : `${node.hostname} deployment status is ${node.status || 'unknown'}.`;
  const reach = dependency(ops, 'Reachability');
  return `${status} ${reach?.detail || 'TCP 443 was not checked from InsightEngine.'}`;
}

function certFinding(ops?: ServiceCheckOps): string {
  const certs = dependency(ops, 'Certificates');
  if (!certs?.detail) return 'Trusted certificates were not loaded.';
  return certs.detail;
}

function alarmFinding(node: ServiceCheckNode, ops?: ServiceCheckOps): string | null {
  const related = (node.issues || []).filter((issue) => /replicat|synchron|alarm/i.test(issue));
  const rows = (ops?.alarms?.rows || []).map((row) => row.name).filter(Boolean);
  if (related.length === 0 && rows.length === 0) return null;
  const parts = [...related, ...rows];
  return parts.join('. ');
}

function directoryFinding(node: ServiceCheckNode, ops?: ServiceCheckOps): string {
  const client = node.directory === true
    ? 'The directory client process is running on this node.'
    : node.directory === false
      ? 'The directory client process is not running on this node.'
      : 'SNMP did not say whether the directory client is running.';
  const dirs = (ops?.directories || []).map((row) => [row.name, row.domain].filter(Boolean).join(' for ')).filter(Boolean);
  const named = dirs.length ? ` Configured directory: ${dirs.join('; ')}.` : '';
  const ad = dependency(ops, 'Active Directory');
  return `${client}${named}${ad?.detail ? ` ${ad.detail}` : ''}`;
}

function ntpProcess(node: ServiceCheckNode, running?: boolean): string {
  if (node.ntp === true || running === true) return 'The NTP process is running on this node.';
  if (node.ntp === false || running === false) return 'The NTP process is not running on this node.';
  return 'SNMP did not say whether the NTP process is running.';
}

function freshFinding(node: ServiceCheckNode): string {
  if (node.cpu != null || node.memory != null || node.diskRoot != null) {
    return 'CPU, memory, and disk on this node came back in the latest SNMP poll.';
  }
  return 'This poll has no CPU, memory, or disk reading.';
}

function known(look: string, finding: string): Check {
  return { look, finding, known: true };
}

function missing(look: string, finding: string): Check {
  return { look, finding, known: false };
}

export function serviceBrief(name: string, running: boolean | undefined, node: ServiceCheckNode, ops?: ServiceCheckOps): ServiceBrief {
  const status = known('Process', runningFinding(name, running));
  const replication = alarmFinding(node, ops);
  const checks: Record<string, Check[]> = {
    'Application Server': [
      status,
      missing('Unexpected restarts', NOT_RESTARTS),
      missing('Application errors', NOT_ERRORS),
      known('Authentication-processing symptoms', sessionFinding(ops)),
    ],
    Web: [
      status,
      known('HTTPS availability', httpsFinding(node, ops)),
      missing('Portal response time', 'Portal response time is not measured from InsightEngine.'),
      missing('HTTP errors', NOT_ERRORS),
      known('TLS certificate expiry', certFinding(ops)),
    ],
    Database: [
      status,
      known('Storage pressure', storageFinding(node)),
      missing('Database errors', NOT_ERRORS),
      replication ? known('Replication and synchronization alarms', replication) : missing('Replication and synchronization alarms', 'ISE did not return a replication alarm for this node.'),
    ],
    Cache: [
      status,
      missing('Restart and error events', `${NOT_RESTARTS} ${NOT_ERRORS}`),
      known('Resource pressure', resourceFinding(node)),
      missing('Hit and miss counters', 'Hit and miss counters are not available through the public APIs.'),
    ],
    Messaging: [
      status,
      missing('Communication failures', NOT_ERRORS),
      known('Messaging-certificate issues', `${certFinding(ops)} It does not identify a messaging certificate on its own.`),
      missing('Relevant logs', 'Messaging logs are not part of this poll.'),
    ],
    'API database': [
      status,
      missing('API Gateway Database errors', NOT_ERRORS),
    ],
    Containers: [
      status,
      missing('Container failures', 'Container failure detail is not exposed. InsightEngine does not open Docker on the node.'),
    ],
    Metrics: [
      status,
      known('Monitoring data freshness', freshFinding(node)),
    ],
    NTP: [
      known('Process', ntpProcess(node, running)),
      missing('Synchronization status', 'ISE SNMP did not return synchronization state.'),
      missing('Configured time sources', 'Configured NTP servers were not in the SNMP reading.'),
      missing('Clock offset', 'Clock offset was not returned by SNMP.'),
    ],
    Directory: [
      status,
      known('Join and connectivity status', directoryFinding(node, ops)),
      missing('Domain-controller reachability', 'InsightEngine does not probe the domain controllers separately.'),
      missing('Lookup and authentication failures', NOT_ERRORS),
    ],
  };
  return {
    name,
    why: WHY[name] || 'This service was reported on the node.',
    running,
    checks: checks[name] || [status],
  };
}

function place(anchor: DOMRect): { left: number; top: number } {
  const left = Math.min(window.innerWidth - 160, Math.max(160, anchor.left + anchor.width / 2));
  return { left, top: Math.max(12, anchor.top - 8) };
}

export function ServiceTooltip({ brief, anchor }: { brief: ServiceBrief; anchor: DOMRect }) {
  const [container, setContainer] = useState<HTMLElement | null>(null);
  useEffect(() => setContainer(document.body), []);
  if (!container) return null;
  const spot = place(anchor);
  const preview = brief.checks.filter((check) => check.known).slice(0, 3);
  const running = brief.running === true;
  return createPortal(
    <div
      role="tooltip"
      style={{ left: spot.left, top: spot.top, zIndex: 2147483647 }}
      className="pointer-events-none fixed w-80 -translate-x-1/2 -translate-y-full rounded-lg border border-navy-3 bg-navy p-3 text-primary-foreground shadow-pop pop-in"
    >
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm font-semibold">{brief.name}</span>
        <span className={`inline-flex rounded-full border px-2 py-0.5 text-[11px] font-semibold ${running ? 'border-success text-success' : 'border-warning text-warning'}`}>
          {brief.running == null ? 'Unknown' : running ? 'Running' : 'Not running'}
        </span>
      </div>
      <dl className="mt-2 space-y-1.5 text-xs">
        {preview.map((check) => (
          <div key={check.look}>
            <dt className="text-down">{check.look}</dt>
            <dd className="mt-0.5">{check.finding}</dd>
          </div>
        ))}
      </dl>
      <p className="mt-2 border-t border-navy-3 pt-1.5 text-[10px] text-down">Click to open the full check</p>
    </div>,
    container,
  );
}

export function ServiceDrawer({ brief, node, onClose }: { brief: ServiceBrief; node: ServiceCheckNode; onClose: () => void }) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);
  if (typeof document === 'undefined') return null;
  const running = brief.running === true;
  return createPortal(
    <>
      <button type="button" aria-label="Close service" className="fixed inset-0 z-[80] bg-black/20" onClick={onClose} />
      <div className="drawer-in fixed inset-y-0 right-0 z-[90] flex w-full max-w-[440px] flex-col overflow-y-auto border-l border-border bg-card shadow-2xl" role="dialog" aria-modal="false" aria-label={brief.name}>
        <header className="flex items-start justify-between gap-3 p-4">
          <div>
            <p className="text-xs uppercase tracking-wide text-muted-foreground">{node.hostname}{node.ip ? ` · ${node.ip}` : ''}</p>
            <h2 className="text-xl font-semibold">{brief.name}</h2>
          </div>
          <button type="button" onClick={onClose} aria-label="Close service panel" className="rounded-md p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground">
            <Icon name="XMarkIcon" size={18} />
          </button>
        </header>
        <div className="space-y-4 px-4 pb-6">
          <div className="flex items-start justify-between gap-3">
            <p className="text-sm text-muted-foreground">{brief.why}</p>
            <span className={`inline-flex shrink-0 rounded-full px-2.5 py-0.5 text-xs font-semibold ${running ? 'bg-success/10 text-success' : 'bg-warning/15 text-foreground'}`}>
              {brief.running == null ? 'Unknown' : running ? 'Running' : 'Not running'}
            </span>
          </div>
          <ul className="space-y-2">
            {brief.checks.filter((check) => check.known).map((check) => (
              <li key={check.look} className="rounded-md border border-border px-3 py-2">
                <p className="text-sm font-semibold">{check.look}</p>
                <p className="mt-1 text-sm text-foreground">{check.finding}</p>
              </li>
            ))}
          </ul>
          {brief.checks.some((check) => !check.known) ? (
            <p className="text-sm text-muted-foreground">Not returned for this service: {brief.checks.filter((check) => !check.known).map((check) => check.look.toLowerCase()).join(', ')}.</p>
          ) : null}
        </div>
      </div>
    </>,
    document.body,
  );
}
