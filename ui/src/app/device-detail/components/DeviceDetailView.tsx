'use client';

import React, { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { toast } from 'sonner';
import Icon from '@/components/ui/AppIcon';
import ExampleDataBanner from '@/components/ui/ExampleDataBanner';
import { HealthBadge, StatusBadge } from '@/components/ui/Badge';
import { Skeleton } from '@/components/ui/Skeleton';
import Faceplate, { FaceplateLegend } from '@/components/faceplate/Faceplate';
import { countPorts, faceplateSummaryLine, SNMP_MISSING_HINT } from '@/components/faceplate/summary';
import { DeviceDiscoveryStatus, usePolledDeviceDiscovery } from '@/components/DeviceDiscoveryStatus';
import { api } from '@/lib/apiClient';
import { isApiError } from '@/lib/apiError';
import { isMockMode } from '@/lib/apiMode';
import { useKeyedLoad } from '@/lib/useKeyedLoad';
import { usePageQuery } from '@/lib/usePageQuery';
import { FACEPLATE_SAMPLES } from '@/lib/mockData';
import type { DeviceDiscoveryJob } from '@/lib/contract';
import type { DeviceDetailData, PortInfo, SourceComparison } from '@/lib/types';
import IssuesPanel from './IssuesPanel';
import HealthChecks from './HealthChecks';
import HardwareHealth from './HardwareHealth';
import PortSidePanel, { PortThroughputGraph } from './PortSidePanel';
import DeviceGraphs from './DeviceGraphs';
import PortTable from './PortTable';

const FORMS = Object.keys(FACEPLATE_SAMPLES);
const NEEDS_ID = 'Open a device from the list. This page needs a device id.';

function isFaceplateKey(value: string): boolean {
  return FORMS.includes(value) || value.startsWith('fg-') || value.startsWith('pa-');
}

const DEVICE_ICON: Record<string, string> = {
  'access-switch-24': 'ServerIcon',
  'access-switch-48': 'ServerIcon',
  'switch-stack': 'Squares2X2Icon',
  'ceiling-ap': 'WifiIcon',
  'wireless-controller': 'SignalIcon',
  firewall: 'ShieldCheckIcon',
  'branch-router': 'ArrowsRightLeftIcon',
  'modular-chassis': 'CpuChipIcon',
  generic: 'CubeIcon',
};

export default function DeviceDetailView() {
  const live = !isMockMode();
  const { ready, params } = usePageQuery('/device-detail');
  const id = params.get('id') ?? '';
  const formQuery = params.get('form') ?? '';
  const [pickedForm, setPickedForm] = useState<string | null>(null);
  const [selected, setSelected] = useState<PortInfo | null>(null);
  const [rerun, setRerun] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [missingId, setMissingId] = useState(false);
  const [postedDiscovery, setPostedDiscovery] = useState<DeviceDiscoveryJob | null>(null);
  const [rediscovering, setRediscovering] = useState(false);
  const discoveryJob = usePolledDeviceDiscovery(postedDiscovery, {
    onError: (job) => toast.error(job.message || 'Rediscover failed.'),
    onDone: () => toast.success('Rediscover finished.'),
  });

  const mockKey = pickedForm || (isFaceplateKey(formQuery) ? formQuery : '') || 'switch-stack';
  const deviceKey = live ? id : mockKey;
  const canLoad = ready && (!live || Boolean(id));
  const loaded = useKeyedLoad<DeviceDetailData>(deviceKey, canLoad, attempt, 'this device', (key) => api.getDevice(key));
  const device = loaded.data;

  useEffect(() => {
    setSelected(null);
  }, [deviceKey]);

  useEffect(() => {
    if (!ready || !live || id) {
      setMissingId(false);
      return undefined;
    }
    // A client navigation can paint `?form=` before `id`. Keep loading until
    // that snapshot has had a chance to gain the id.
    const timer = window.setTimeout(() => setMissingId(true), 50);
    return () => window.clearTimeout(timer);
  }, [ready, live, id]);

  const face = device?.faceplate?.form_factor;
  const form = (!live && pickedForm && isFaceplateKey(pickedForm) ? pickedForm : '')
    || (face && isFaceplateKey(face) ? face : '')
    || (isFaceplateKey(formQuery) ? formQuery : '')
    || 'switch-stack';
  const showMissing = ready && live && !id && missingId;
  const error = showMissing ? NEEDS_ID : loaded.error;

  const allPorts = useMemo<PortInfo[]>(() => {
    if (!device) return [];
    const f = device.faceplate;
    if (f.members) return f.members.flatMap((m) => m.ports);
    if (f.modules) return f.modules.flatMap((m) => m.ports);
    return f.ports ?? [];
  }, [device]);

  if (error) {
    return (
      <div role="alert" className="flex items-center justify-between gap-3 rounded-md border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
        <span className="flex items-center gap-2"><Icon name="ExclamationCircleIcon" size={18} />{error}</span>
        <button type="button" onClick={() => setAttempt((n) => n + 1)} className="rounded-md border border-destructive/40 px-3 py-1 text-xs font-semibold">Retry</button>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <nav aria-label="Breadcrumb" className="flex items-center gap-1.5 px-4 text-xs text-muted-foreground">
        <Link href="/" className="hover:text-foreground hover:underline">Devices</Link>
        <Icon name="ChevronRightIcon" size={12} />
        <span className="font-mono-data text-foreground">{device?.hostname ?? '…'}</span>
      </nav>

      {/* header */}
      <header className="rounded-none border-x-0 border-y border-border bg-card p-4 shadow-card">
        {device ? (
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-3">
                <h1 className="font-mono-data text-2xl font-semibold tracking-tight">{device.hostname}</h1>
                <HealthBadge health={device.health} />
                <StatusBadge status={device.status} />
                {device.faceplate.modelName && (
                  <span className="rounded-md border border-border bg-muted px-2 py-0.5 font-mono-data text-xs font-semibold text-foreground">{device.faceplate.modelName}</span>
                )}
                {device.issues.filter((i) => i.severity === 'critical').length > 0 && (
                  <span className="inline-flex items-center gap-1 rounded-full bg-destructive px-2.5 py-0.5 text-xs font-bold text-destructive-foreground">
                    <Icon name="BellAlertIcon" size={12} variant="solid" />
                    {device.issues.filter((i) => i.severity === 'critical').length} critical
                  </span>
                )}
              </div>
              <dl className="mt-2 grid grid-cols-2 gap-x-6 gap-y-1.5 text-sm sm:grid-cols-3 xl:grid-cols-6">
                <Meta label="Role" value={device.role} />
                <Meta label="Model" value={device.modelFamily} mono />
                <Meta label="Serial number" value={device.serialMasked} mono />
                <Meta label="Site" value={device.site} link="/site-view" />
                <Meta label="Management IP" value={device.mgmtIp} mono />
                <Meta label="Uptime" value={device.uptime} mono />
                <Meta label="Last poll" value={device.lastPoll} mono />
                <Meta label="Firmware" value={device.firmware} mono />
              </dl>
            </div>
            <div className="flex flex-col items-stretch gap-2">
              <button
                type="button"
                disabled={rediscovering || !device.mgmtIp}
                onClick={() => {
                  setRediscovering(true);
                  api
                    .discoverDevice(device.mgmtIp, false)
                    .then(setPostedDiscovery)
                    .catch((error) => {
                      toast.error(isApiError(error) ? error.message : 'Rediscover failed.');
                    })
                    .finally(() => setRediscovering(false));
                }}
                className="inline-flex items-center justify-center gap-1.5 rounded-md border border-border bg-card px-3 py-2 text-sm font-medium transition-all hover:bg-muted active:scale-95 disabled:opacity-50"
              >
                <Icon name="MagnifyingGlassIcon" size={16} />
                {rediscovering ? 'Rediscovering…' : 'Rediscover'}
              </button>
              <button
                type="button"
                onClick={() => {
                  setRerun(true);
                  setTimeout(() => setRerun(false), 1100);
                }}
                className="inline-flex items-center justify-center gap-1.5 rounded-md border border-border bg-card px-3 py-2 text-sm font-medium transition-all hover:bg-muted active:scale-95"
              >
                <Icon name="ArrowPathIcon" size={16} className={rerun ? 'animate-spin' : ''} />
                {rerun ? 'Running checks…' : 'Re-run health check'}
              </button>
              <Link
                href={
                  isMockMode()
                    ? `/device-cli?form=${encodeURIComponent(form)}`
                    : `/device-cli?id=${encodeURIComponent(device?.id || id)}&form=${encodeURIComponent(form)}`
                }
                className="inline-flex items-center justify-center gap-1.5 rounded-md border border-border bg-card px-3 py-2 text-sm font-medium transition-all hover:bg-muted active:scale-95"
              >
                <Icon name="CommandLineIcon" size={16} />
                Open device
              </Link>
              <Link
                href={
                  isMockMode()
                    ? `/topology?form=${encodeURIComponent(form)}`
                    : `/topology?id=${encodeURIComponent(device?.id || id)}&form=${encodeURIComponent(form)}`
                }
                className="inline-flex items-center justify-center gap-1.5 rounded-md border border-border bg-card px-3 py-2 text-sm font-medium transition-all hover:bg-muted active:scale-95"
              >
                <Icon name="ShareIcon" size={16} />
                Topology
              </Link>
            </div>
            <div className="basis-full">
              <DeviceDiscoveryStatus job={discoveryJob} />
            </div>
          </div>
        ) : (
          <div className="space-y-3">
            <p role="status" className="sr-only">Loading device</p>
            <Skeleton className="h-8 w-72" />
            <Skeleton className="h-5 w-full max-w-3xl" />
          </div>
        )}
      </header>

      {/* issues + hardware health + health check */}
      <section className="rounded-none border-x-0 border-y border-border bg-card shadow-card" aria-label="Device status overview">
        <div className="grid grid-cols-1 gap-3 p-3 xl:grid-cols-3">
          <div>
            <IssuesPanel issues={device?.issues ?? null} />
          </div>
          <div>
            <HardwareHealth items={device?.hardware ?? null} />
          </div>
          <div>
            <HealthChecks checks={device?.checks ?? null} runAt={device?.checkRunAt ?? ''} running={rerun} />
          </div>
        </div>
      </section>

      {device && !isMockMode() ? <ComparisonPanel comparison={device.comparison} /> : null}

      {/* faceplate */}
      <section className="rounded-none border-x-0 border-y border-border bg-card shadow-card" aria-labelledby="fp-title">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-4 py-2.5">
          <div>
            <h2 id="fp-title" className="text-base font-semibold">Faceplate</h2>
            <p className="text-xs text-muted-foreground">Pick a device to see its own faceplate. Hover a port for details, click to open its graph.</p>
          </div>
        </div>

        {isMockMode() ? (
        <div role="tablist" aria-label="Devices at this site" className="scroll-thin flex gap-2 overflow-x-auto border-b border-border bg-muted/40 px-4 py-2">
          {FORMS.map((f) => {
            const active = f === form;
            return (
              <button
                key={`dev-${f}`}
                type="button"
                role="tab"
                aria-selected={active}
                onClick={() => setPickedForm(f)}
                className={`inline-flex shrink-0 items-center gap-2 rounded-md border px-3 py-2 text-sm font-medium transition-all active:scale-95 focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary ${
                  active ? 'border-primary bg-primary/10 text-foreground shadow-card' : 'border-border bg-card text-muted-foreground hover:bg-muted hover:text-foreground'
                }`}
              >
                <Icon name={(DEVICE_ICON[f] ?? (f.startsWith('fg-') || f.startsWith('pa-') ? 'ShieldCheckIcon' : 'CubeIcon')) as any} size={16} />
                {FACEPLATE_SAMPLES[f].label}
              </button>
            );
          })}
        </div>
        ) : null}

        <div className="grid grid-cols-1 xl:grid-cols-[1fr_auto]">
          <div className="min-w-0 p-4">
            <div className="scroll-thin overflow-x-auto rounded-lg bg-gradient-to-b from-secondary to-background p-3">
              {device ? (
                <div className="mx-auto min-w-[640px]" style={{ maxWidth: 1180 }}>
                  <Faceplate device={device.faceplate} selectedPortId={selected?.id ?? null} onSelectPort={setSelected} />
                </div>
              ) : (
                <Skeleton className="h-52 w-full" />
              )}
            </div>
            <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
              <FaceplateLegend />
              <div className="text-xs text-muted-foreground">
                <p data-testid="faceplate-summary">{faceplateSummaryLine(countPorts(allPorts), device?.faceplate.snmpAt)}</p>
                {device?.faceplate.snmpMissing ? <p className="mt-1">{SNMP_MISSING_HINT}</p> : null}
              </div>
            </div>
            {selected && (
              <div className="slide-in-right mt-3">
                <PortThroughputGraph port={selected} deviceId={device?.id} />
              </div>
            )}
          </div>
          {selected && (
            <div className="slide-in-right border-t border-border xl:w-[380px] xl:border-l xl:border-t-0">
              <PortSidePanel port={selected} onClose={() => setSelected(null)} />
            </div>
          )}
        </div>
      </section>

      {isMockMode() ? (
        <ExampleDataBanner text="Device, port and graph values below come from mock JSON in the API client." />
      ) : null}

      {device && !isMockMode() ? <Inventory device={device} /> : null}

      {device && <DeviceGraphs deviceId={device.id} />}

      {device && <PortTable ports={allPorts} selectedId={selected?.id ?? null} onSelect={setSelected} />}
    </div>
  );
}

const COMPARE_ROWS: { key: keyof SourceComparison['netbox']; label: string }[] = [
  { key: 'vendor', label: 'Vendor' },
  { key: 'model', label: 'Model' },
  { key: 'serial', label: 'Serial' },
  { key: 'os', label: 'OS' },
  { key: 'portCount', label: 'Port count' },
];

function ComparisonPanel({ comparison }: { comparison?: SourceComparison }) {
  if (!comparison) return null;
  const source = comparison.faceplateSource || 'none';
  return (
    <section className="rounded-none border-x-0 border-y border-border bg-card p-4 shadow-card" aria-label="NetBox and Netdisco comparison">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-base font-semibold">NetBox and Netdisco</h2>
          <p className="text-xs text-muted-foreground">Faceplate built from {source}.</p>
        </div>
        {comparison.differ ? (
          <span className="rounded-md border border-warning/40 bg-warning/15 px-2 py-1 text-xs font-semibold text-foreground">NetBox and Netdisco differ</span>
        ) : null}
      </div>
      <table className="mt-3 w-full border-collapse text-sm">
        <thead>
          <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-muted-foreground">
            <th className="py-1.5 pr-3 font-semibold">Field</th>
            <th className="py-1.5 pr-3 font-semibold">NetBox</th>
            <th className="py-1.5 font-semibold">Netdisco</th>
          </tr>
        </thead>
        <tbody>
          {COMPARE_ROWS.map((row) => (
            <tr key={row.key} className="border-b border-border/70">
              <th scope="row" className="py-1.5 pr-3 text-left font-medium">{row.label}</th>
              <td className="py-1.5 pr-3 font-mono-data">{String(comparison.netbox?.[row.key] ?? '—') || '—'}</td>
              <td className="py-1.5 font-mono-data">{String(comparison.netdisco?.[row.key] ?? '—') || '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function Inventory({ device }: { device: DeviceDetailData }) {
  const sources = device.sources ?? [];
  return (
    <section className="space-y-3 rounded-none border-x-0 border-y border-border bg-card p-4 shadow-card" aria-label="Inventory">
      {sources.length > 0 ? (
        <ul className="flex flex-wrap gap-2 text-xs">
          {sources.map((source) => (
            <li key={source.name} className="inline-flex items-center gap-1.5 rounded-full border border-border px-2.5 py-1" title={source.detail || source.name}>
              <span className={`h-2 w-2 rounded-full ${source.ok ? 'bg-success' : 'bg-warning'}`} />
              <span className="font-medium capitalize">{source.name}</span>
              {!source.ok && source.detail ? <span className="text-muted-foreground">{source.detail}</span> : null}
            </li>
          ))}
        </ul>
      ) : null}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <div>
          <h2 className="text-sm font-semibold">Interfaces and addresses</h2>
          {(device.interfaces ?? []).length === 0 && (device.addresses ?? []).length === 0 ? (
            <p className="mt-1 text-sm text-muted-foreground">NetBox did not return interfaces or IP addresses for this device.</p>
          ) : (
            <ul className="mt-2 space-y-1 font-mono-data text-xs">
              {(device.interfaces ?? []).slice(0, 40).map((row) => (
                <li key={row.name}>{row.name} · {row.enabled ? 'enabled' : 'disabled'} · {row.type || '—'}</li>
              ))}
              {(device.addresses ?? []).slice(0, 20).map((row) => (
                <li key={row.address}>{row.address}{row.interface ? ` on ${row.interface}` : ''}</li>
              ))}
            </ul>
          )}
        </div>
        <div>
          <h2 className="text-sm font-semibold">Neighbours</h2>
          {device.neighborNote ? (
            <p className="mt-1 text-sm text-muted-foreground">{device.neighborNote}</p>
          ) : null}
          {(device.neighbors ?? []).length === 0 ? (
            device.neighborNote ? null : <p className="mt-1 text-sm text-muted-foreground">No Netdisco LLDP or CDP neighbours were returned.</p>
          ) : (
            <ul className="mt-2 space-y-1 font-mono-data text-xs">
              {(device.neighbors ?? []).map((row) => (
                <li key={`${row.localPort}-${row.remoteName}-${row.remotePort}-${row.source || ''}`}>
                  {row.localPort} → {row.remoteName || row.remoteAddress || 'unknown'} {row.remotePort}
                  {row.source ? <span className="text-muted-foreground"> · {row.source}</span> : null}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
      <div>
        <h2 className="text-sm font-semibold">Last config backup</h2>
        {device.backup?.available ? (
          <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap rounded-md bg-muted p-3 font-mono-data text-xs">{device.backup.config || device.backup.status || 'Backup recorded'}</pre>
        ) : (
          <p className="mt-1 text-sm text-muted-foreground">{device.backup?.reason || 'Oxidized has no backup for this device.'}</p>
        )}
      </div>
    </section>
  );
}

function Meta({ label, value, mono, link }: { label: string; value: string; mono?: boolean; link?: string }) {
  return (
    <div className="min-w-0">
      <dt className="label-caps text-muted-foreground">{label}</dt>
      <dd className={`mt-0.5 truncate text-sm ${mono ? 'font-mono-data' : 'font-medium'}`} title={value}>
        {link ? <Link href={link} className="hover:text-primary hover:underline">{value}</Link> : value}
      </dd>
    </div>
  );
}