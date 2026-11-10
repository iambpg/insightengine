'use client';

import React, { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import Link from 'next/link';
import { toast } from 'sonner';
import Icon from '@/components/ui/AppIcon';
import CollapsiblePanel from '@/components/ui/CollapsiblePanel';
import ExampleDataBanner from '@/components/ui/ExampleDataBanner';
import { HealthBadge, StatusBadge } from '@/components/ui/Badge';
import { Skeleton } from '@/components/ui/Skeleton';
import Faceplate, { FaceplateLegend } from '@/components/faceplate/Faceplate';
import { FACEPLATE_HEIGHT } from '@/components/faceplate/size';
import { countPorts, faceplateSummaryLine, SNMP_MISSING_HINT } from '@/components/faceplate/summary';
import { namesMatch } from '@/components/faceplate/library/ifname';
import { portNameLine } from '@/components/faceplate/portText';
import { DeviceDiscoveryStatus, usePolledDeviceDiscovery } from '@/components/DeviceDiscoveryStatus';
import { api } from '@/lib/apiClient';
import { isApiError } from '@/lib/apiError';
import { devicePath, isMockMode } from '@/lib/apiMode';
import { deviceHealthPath } from '@/lib/deviceHealthPath';
import AddApDialog from '@/components/AddApDialog';
import { useKeyedLoad } from '@/lib/useKeyedLoad';
import { usePageQuery } from '@/lib/usePageQuery';
import { FACEPLATE_SAMPLES } from '@/lib/mockData';
import type { DeviceDiscoveryJob } from '@/lib/contract';
import type { DeviceDetailData, DeviceParentLink, HealthCause, InventorySide, PortInfo } from '@/lib/types';
import AccessPointList from './AccessPointList';
import HealthCauses, { type HealthFilter } from './HealthCauses';
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

const EMBER = '#c2410c';
const UPTIME_ORANGE = '#f97316';
const UPTIME_LIGHT_RED = '#fca5a5';

function sameText(left: string, right: string): boolean {
  return left.trim().toLowerCase().replace(/\s+/g, ' ') === right.trim().toLowerCase().replace(/\s+/g, ' ');
}

function inventoryTone(netbox?: string, netdisco?: string): 'match' | 'differ' | 'unknown' {
  const left = (netbox || '').trim();
  const right = (netdisco || '').trim();
  if (!left && !right) return 'unknown';
  if (!left || !right || !sameText(left, right)) return 'differ';
  return 'match';
}

function modelTone(netbox: InventorySide | undefined, live?: string): 'match' | 'differ' | 'unknown' {
  const right = (live || '').trim();
  const left = (netbox?.model || '').trim();
  const part = (netbox?.partNumber || '').trim();
  if (!left && !part && !right) return 'unknown';
  if (right && (sameText(left, right) || sameText(part, right))) return 'match';
  return 'differ';
}

function toneShade(tone: 'match' | 'differ' | 'unknown'): string | undefined {
  if (tone === 'match') return 'var(--success)';
  if (tone === 'differ') return EMBER;
  return undefined;
}

function uptimeShade(value: string): string | undefined {
  const text = (value || '').trim();
  if (!text || text === '—') return undefined;
  const days = text.match(/(\d+)\s*d\b/i);
  if (days) return Number(days[1]) > 5 ? 'var(--success)' : UPTIME_ORANGE;
  if (/\d/.test(text)) return UPTIME_LIGHT_RED;
  return undefined;
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
  const [syncing, setSyncing] = useState(false);
  const [healthFilter, setHealthFilter] = useState<HealthFilter>('all');
  const [addAp, setAddAp] = useState(false);
  const [cable, setCable] = useState<{ remotePort: string; localPort: string; plate: HTMLElement } | null>(null);
  const healthApplied = useRef('');
  const localPlateRef = useRef<HTMLDivElement>(null);
  const greyRef = useRef<HTMLDivElement>(null);
  const plateRefs = useRef(new Map<string, HTMLDivElement>());
  const plateBinders = useRef(new Map<string, (el: HTMLDivElement | null) => void>());
  const discoveryJob = usePolledDeviceDiscovery(postedDiscovery, {
    onError: (job) => toast.error(job.message || 'Rediscover failed.'),
    onDone: () => toast.success('Rediscover finished.'),
  });

  const mockKey = pickedForm || (isFaceplateKey(formQuery) ? formQuery : '') || 'switch-stack';
  const deviceKey = live ? id : mockKey;
  const canLoad = ready && (!live || Boolean(id));
  const loaded = useKeyedLoad<DeviceDetailData>(deviceKey, canLoad, attempt, 'this device', (key) => api.getDevice(key));
  const device = loaded.data;
  const kin = useMemo(() => {
    const rows: { id: string; localPort: string; remotePort: string }[] = [];
    if (device?.parent) {
      rows.push({ id: device.parent.id, localPort: device.parent.uplinkInterface, remotePort: device.parent.parentInterface });
    }
    for (const child of device?.children ?? []) {
      rows.push({ id: child.id, localPort: child.parentInterface, remotePort: child.uplinkInterface });
    }
    return rows;
  }, [device]);

  const plateBinder = (id: string) => {
    let binder = plateBinders.current.get(id);
    if (!binder) {
      binder = (el: HTMLDivElement | null) => {
        if (el) plateRefs.current.set(id, el);
        else plateRefs.current.delete(id);
      };
      plateBinders.current.set(id, binder);
    }
    return binder;
  };

  useEffect(() => {
    setSelected(null);
    setCable(null);
  }, [deviceKey]);

  useEffect(() => {
    if (!selected) {
      setCable(null);
      return;
    }
    const hit = kin.find((row) => portIs(selected, row.localPort));
    const plate = hit ? plateRefs.current.get(hit.id) ?? document.querySelector<HTMLElement>(`[data-relation-id="${hit.id}"]`) : null;
    setCable(hit && plate ? { remotePort: hit.remotePort, localPort: selected.name, plate } : null);
  }, [selected, kin, device?.id]);

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

  const tab = params.get('tab') ?? '';
  const severityQuery = params.get('severity') ?? '';
  useEffect(() => {
    if (!device) return;
    const key = `${device.id}|${tab}|${severityQuery}`;
    if (healthApplied.current === key) return;
    healthApplied.current = key;
    if (tab !== 'health') return;
    const next: HealthFilter = severityQuery === 'critical' || severityQuery === 'warning' || severityQuery === 'info' ? severityQuery : 'all';
    setHealthFilter(next);
    const section = document.getElementById('health');
    if (section && typeof section.scrollIntoView === 'function') section.scrollIntoView({ block: 'start' });
  }, [device, tab, severityQuery]);

  const apDraft = useMemo(() => {
    const point = device?.healthPanel?.accessPoint;
    if (device?.inNetbox !== false || !point) return [];
    return [{
      name: point.name || device.hostname,
      wlc: point.wlc,
      model: point.model,
      serial: point.serial,
      ip: point.ip,
      ios: point.ios,
      location: point.location,
      siteTag: point.siteTag,
      suggestedSite: device.site && device.site !== '—' ? device.site : '',
    }];
  }, [device]);

  const syncTones = useMemo(() => {
    const nb = device?.comparison?.netbox;
    const nd = device?.comparison?.netdisco;
    const live = device?.comparison?.observed;
    const tones = {
      model: modelTone(nb, live?.model || nd?.model),
      serial: inventoryTone(nb?.serial, live?.serial || nd?.serial),
      site: inventoryTone(nb?.site || (device?.site && device.site !== '—' ? device.site : ''), nd?.site),
      firmware: inventoryTone(nb?.firmware || nb?.os, live?.firmware || nd?.firmware || nd?.os),
    };
    const labels: { key: keyof typeof tones; label: string }[] = [
      { key: 'model', label: 'Model' },
      { key: 'serial', label: 'Serial number' },
      { key: 'site', label: 'Site' },
      { key: 'firmware', label: 'Firmware' },
    ];
    const differs = labels.filter((item) => item.key !== 'site' && tones[item.key] !== 'match').map((item) => item.label);
    return { tones, synced: differs.length === 0, differs };
  }, [device]);

  const visibleIssues = useMemo(() => {
    const issues = device?.issues ?? [];
    if (!device?.parentDown) return issues;
    return issues.filter((issue) => !/icmp|unreachable|not answering/i.test(`${issue.title} ${issue.detail}`));
  }, [device]);

  const healthItems = useMemo<HealthCause[]>(() => {
    if (!device) return [];
    const items = Array.isArray(device.healthItems)
      ? device.healthItems
      : (device.issues ?? []).map((issue) => ({
          id: issue.id,
          severity: issue.severity,
          title: issue.title,
          detail: issue.detail,
          value: issue.target,
          threshold: '—',
          source: 'alertmanager',
          since: issue.since,
          target: issue.target,
        }));
    if (!device.parentDown) return items;
    return items.filter((issue) => !/icmp|unreachable|not answering/i.test(`${issue.title} ${issue.detail}`));
  }, [device]);

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
              <div className="flex flex-wrap items-center gap-2">
                <h1 className="rounded-lg border border-border bg-muted/50 px-3 py-1.5 font-mono-data text-xl font-semibold tracking-tight">{device.hostname}</h1>
                <HealthBadge health={device.health} href={deviceHealthPath(device.id || id, device.faceplate.form_factor, device.health)} />
                <StatusBadge status={device.status} />
                {device.faceplate.modelName && (
                  <span className="rounded-md border border-border bg-muted px-2 py-0.5 font-mono-data text-xs font-semibold text-foreground">{device.faceplate.modelName}</span>
                )}
                {visibleIssues.filter((i) => i.severity === 'critical').length > 0 && (
                  <span className="inline-flex items-center gap-1 rounded-full bg-destructive px-2.5 py-0.5 text-xs font-bold text-destructive-foreground">
                    <Icon name="BellAlertIcon" size={12} variant="solid" />
                    {visibleIssues.filter((i) => i.severity === 'critical').length} critical
                  </span>
                )}
              </div>
              <dl className="mt-3 flex flex-wrap gap-2 text-sm">
                <Meta label="Role" value={device.role} shade={device.roleColor} />
                <Meta label="Model" value={device.partNumber || device.faceplate.partNumber || device.faceplate.modelName || device.modelFamily} mono shade={toneShade(syncTones.tones.model)} />
                <Meta label="Serial number" value={device.serialMasked} mono shade={toneShade(syncTones.tones.serial)} />
                <Meta label="Site" value={device.site} link="/site-view" shade={toneShade(syncTones.tones.site)} />
                <Meta label="Management IP" value={device.mgmtIp} mono shade={device.reachable ? 'var(--success)' : undefined} />
                <Meta label="Uptime" value={device.uptime} mono shade={uptimeShade(device.uptime)} />
                <Meta label="Last poll" value={device.lastPoll} mono />
                <Meta label="Firmware" value={device.firmware} mono shade={toneShade(syncTones.tones.firmware)} />
              </dl>
            </div>
            <div className="grid shrink-0 grid-cols-2 gap-2">
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
                disabled={syncing || !device.id}
                onClick={() => {
                  setSyncing(true);
                  api
                    .syncNetbox(device.id)
                    .then((result) => {
                      const labels: Record<string, string> = { model: 'model', serial: 'serial number', firmware: 'firmware' };
                      const written = (result.updated || []).map((key) => labels[key] || key);
                      if (written.length) toast.success(`Updated ${written.join(', ')} in NetBox.${result.note ? ` ${result.note}` : ''}`);
                      else toast.success(result.note || 'NetBox already has this model, serial number and firmware.');
                      setAttempt((n) => n + 1);
                    })
                    .catch((error) => {
                      toast.error(isApiError(error) ? error.message : 'NetBox sync failed.');
                    })
                    .finally(() => setSyncing(false));
                }}
                className={`inline-flex items-center justify-center gap-1.5 rounded-md border border-transparent px-3 py-2 text-sm font-medium text-white transition-all active:scale-95 disabled:opacity-50 ${syncTones.synced ? 'bg-[#15803d] hover:bg-[#166534]' : 'bg-[#c2410c] hover:bg-[#9a3412]'}`}
              >
                <Icon name="ArrowsRightLeftIcon" size={16} />
                {syncing ? 'Syncing…' : 'Netbox Sync'}
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

      {apDraft.length > 0 ? (
        <div className="px-4">
          <button type="button" onClick={() => setAddAp(true)} className="rounded-md bg-primary px-3 py-1.5 text-sm font-semibold text-primary-foreground">Add to NetBox</button>
          <AddApDialog open={addAp} aps={apDraft} onClose={() => setAddAp(false)} onDone={() => undefined} />
        </div>
      ) : null}

      {/* issues + hardware health + health check */}
      <section className="rounded-none border-x-0 border-y border-border bg-card shadow-card" aria-label="Device status overview">
        <div className="grid grid-cols-1 items-stretch gap-3 p-3 xl:grid-cols-3">
          <div className="h-[25.6rem] min-h-0">
            <HealthCauses
              items={device ? healthItems : null}
              health={device?.health ?? 'healthy'}
              filter={healthFilter}
              onFilter={setHealthFilter}
              ports={allPorts}
              onSelectPort={(port) => {
                setSelected(port);
                document.getElementById('fp-title')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
              }}
            />
          </div>
          <div className="h-[25.6rem] min-h-0">
            <HardwareHealth items={device?.hardware ?? null} />
          </div>
          <div className="h-[25.6rem] min-h-0">
            <HealthChecks checks={device?.checks ?? null} runAt={device?.checkRunAt ?? ''} running={rerun} />
          </div>
        </div>
      </section>

      {device?.healthPanel?.wlc ? <AccessPointList wlc={device.hostname} /> : null}

      {/* faceplate */}
      <CollapsiblePanel
        title="Faceplate"
        titleId="fp-title"
        subtitle="Pick a device to see its own faceplate. Hover a port for details, click to open its graph."
      >
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
            <div ref={greyRef} className={`relative rounded-lg bg-gradient-to-b from-secondary to-background p-3 ${kin.length > 0 ? '' : 'scroll-thin overflow-x-auto'}`}>
              <div className={`flex items-center gap-6 ${kin.length > 0 ? 'w-max max-w-full' : ''}`}>
                <div ref={localPlateRef} className={kin.length > 0 ? 'scroll-thin min-w-0 overflow-x-auto' : 'shrink-0'}>
                  {device ? (
                    <div
                      className={device.faceplate.form_factor === 'ceiling-ap' ? 'w-full' : 'flex w-max min-w-full items-center'}
                      style={device.faceplate.form_factor === 'ceiling-ap' ? undefined : { height: FACEPLATE_HEIGHT }}
                    >
                      <Faceplate device={device.faceplate} selectedPortId={selected?.id ?? null} onSelectPort={setSelected} />
                    </div>
                  ) : (
                    <Skeleton className="h-[168px] w-full" />
                  )}
                </div>
                {kin.length > 0 ? (
                  <div className="flex w-max min-w-0 max-w-[50%] shrink-0 items-center gap-3 overflow-hidden">
                    {device?.parent ? <RelationFaceplate link={device.parent} label="Parent" plateRef={plateBinder(device.parent.id)} className="w-40 min-w-[5.5rem] shrink-[0.2]" /> : null}
                    {(device?.children ?? []).length > 0 ? (
                      <div className="flex min-w-0 shrink items-center gap-2">
                        {(device?.children ?? []).map((child) => (
                          <RelationFaceplate key={child.id} link={child} label="Child" plateRef={plateBinder(child.id)} className="w-40 min-w-0 max-w-40 shrink" />
                        ))}
                      </div>
                    ) : null}
                  </div>
                ) : null}
              </div>
              {device ? <ParentBlock device={device} /> : null}
              {cable ? <UplinkCable localRef={localPlateRef} greyRef={greyRef} remote={cable.plate} localPortName={cable.localPort} remotePortName={cable.remotePort} /> : null}
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
      </CollapsiblePanel>

      {isMockMode() ? (
        <ExampleDataBanner text="Device, port and graph values below come from mock JSON in the API client." />
      ) : null}

      {device && !isMockMode() ? <Inventory device={device} /> : null}

      {device && <DeviceGraphs deviceId={device.id} profile={device.healthPanel?.profile} />}

      {device && <PortTable ports={allPorts} selectedId={selected?.id ?? null} onSelect={setSelected} />}
    </div>
  );
}

function Inventory({ device }: { device: DeviceDetailData }) {
  const sources = device.sources ?? [];
  return (
    <CollapsiblePanel
      title="Inventory"
      className="rounded-none border-x-0 border-y border-border bg-card shadow-card"
      bodyClassName="space-y-3 p-4"
    >
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
            <ul className="mt-2 max-h-72 space-y-1 overflow-auto font-mono-data text-xs">
              {(device.interfaces ?? []).map((row) => (
                <li key={row.name}>
                  {portNameLine(row)}
                  {row.description ? ` · ${row.description}` : ''}
                  {' · '}{row.enabled ? 'enabled' : 'disabled'} · {row.type || '—'}
                </li>
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
    </CollapsiblePanel>
  );
}

function shadeColor(shade?: string): string {
  const text = (shade || '').trim();
  if (/^[0-9a-fA-F]{6}$/.test(text)) return `#${text}`;
  return text;
}

function portIs(port: PortInfo, wanted: string): boolean {
  return [port.name, port.id, ...(port.names ?? [])].some((value) => namesMatch(value, wanted));
}

function portMatches(el: Element, wanted: string): boolean {
  const values = [
    el.getAttribute('data-port-name') || '',
    el.getAttribute('data-port-id') || '',
    ...(el.getAttribute('data-port-aliases') || '').split('|'),
  ].filter(Boolean);
  return values.some((value) => namesMatch(value, wanted));
}

function findPort(root: ParentNode, wanted: string): Element | null {
  for (const node of root.querySelectorAll('[data-port-name]')) {
    if (portMatches(node, wanted)) return node;
  }
  return null;
}

function cablePath(points: { x: number; y: number }[]): string {
  const rounded = points.map((point) => ({ x: Math.round(point.x), y: Math.round(point.y) }));
  const first = rounded[0];
  let path = `M ${first.x} ${first.y}`;
  let current = first;
  for (const point of rounded.slice(1)) {
    if (point.x !== current.x) path += ` H ${point.x}`;
    if (point.y !== current.y) path += ` V ${point.y}`;
    current = point;
  }
  return path;
}

function outsideCable(port: DOMRect, chassis: DOMRect, remotePort: DOMRect | null, remoteBox: DOMRect, grey: DOMRect): string {
  const x = port.left + port.width / 2;
  const y = port.top + port.height / 2;
  const hug = 2;
  const above = y <= (chassis.top + chassis.bottom) / 2;
  const laneY = above ? Math.max(grey.top + hug, chassis.top - hug) : Math.min(grey.bottom - hug, chassis.bottom + hug);
  const endX = remotePort ? remotePort.left + remotePort.width / 2 : remoteBox.left + remoteBox.width / 2;
  const rawEndY = remotePort ? remotePort.top + remotePort.height / 2 : remoteBox.top + remoteBox.height / 2;
  const endY = Math.max(grey.top + hug, Math.min(grey.bottom - hug, rawEndY));
  return cablePath([
    { x, y },
    { x, y: laneY },
    { x: endX, y: laneY },
    { x: endX, y: endY },
  ]);
}

function UplinkCable({
  localRef,
  greyRef,
  remote,
  localPortName,
  remotePortName,
}: {
  localRef: React.RefObject<HTMLDivElement | null>;
  greyRef: React.RefObject<HTMLDivElement | null>;
  remote: HTMLElement;
  localPortName: string;
  remotePortName: string;
}) {
  const [path, setPath] = useState('');
  const [size, setSize] = useState({ w: 0, h: 0 });
  useEffect(() => {
    const local = localRef.current;
    const grey = greyRef.current;
    if (!local || !grey || !remote) return;
    const measure = () => {
      const localPort = findPort(local, localPortName);
      const remotePort = findPort(remote, remotePortName);
      if (!localPort) {
        setPath('');
        return;
      }
      const localBox = local.getBoundingClientRect();
      const metal = local.querySelector('[data-chassis]');
      const remoteBox = remote.getBoundingClientRect();
      setSize({ w: window.innerWidth, h: window.innerHeight });
      setPath(outsideCable(localPort.getBoundingClientRect(), metal ? metal.getBoundingClientRect() : localBox, remotePort ? remotePort.getBoundingClientRect() : null, remoteBox, grey.getBoundingClientRect()));
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(local);
    observer.observe(grey);
    observer.observe(remote);
    document.addEventListener('scroll', measure, true);
    window.addEventListener('resize', measure);
    return () => {
      observer.disconnect();
      document.removeEventListener('scroll', measure, true);
      window.removeEventListener('resize', measure);
    };
  }, [localRef, greyRef, remote, localPortName, remotePortName]);
  if (!path || size.w <= 0 || typeof document === 'undefined') return null;
  return createPortal(
    <svg width={size.w} height={size.h} viewBox={`0 0 ${size.w} ${size.h}`} style={{ position: 'fixed', left: 0, top: 0, zIndex: 80, pointerEvents: 'none' }} aria-hidden="true">
      <path d={path} fill="none" stroke="#1e293b" strokeWidth={7} strokeLinejoin="miter" strokeLinecap="butt" />
      <path d={path} fill="none" stroke="#3b82f6" strokeWidth={3} strokeLinejoin="miter" strokeLinecap="butt" />
    </svg>,
    document.body,
  );
}

function RelationFaceplate({ link, label, plateRef, className }: { link: DeviceParentLink; label: 'Parent' | 'Child'; plateRef: (el: HTMLDivElement | null) => void; className: string }) {
  const face = link.faceplate ?? null;
  return (
    <Link
      href={devicePath(link.id, link.formFactor || 'generic')}
      aria-label={`Open ${label.toLowerCase()} ${link.hostname}`}
      style={{ containerType: 'inline-size' }}
      className={`relative flex flex-col items-center gap-1 self-center rounded-lg border border-border bg-card p-1.5 shadow-card transition-colors hover:border-primary ${className}`}
    >
      <div ref={plateRef} data-relation-id={link.id} className="relative w-full overflow-hidden rounded-md bg-background p-1">
        <span className="pointer-events-none absolute left-1/2 top-0.5 z-10 -translate-x-1/2 text-[9px] font-bold uppercase leading-none tracking-wide text-foreground">{label}</span>
        <div className="pointer-events-none">
          {face ? <Faceplate device={face} compact /> : <div className="h-12" />}
        </div>
      </div>
      <span className="max-w-full truncate font-mono-data text-[clamp(0.5rem,16cqw,0.75rem)] font-medium text-foreground" title={link.hostname}>{link.hostname}</span>
    </Link>
  );
}

function ParentBlock({ device }: { device: DeviceDetailData }) {
  if (!device.unparented && !device.parentDown && !device.wlc) return null;
  return (
    <div className="mt-2 max-w-sm space-y-1.5 text-sm">
      {device.parentDown ? (
        <p role="status" className="font-medium text-destructive">Unreachable due to parent</p>
      ) : null}
      {device.unparented ? (
        <p className="text-amber-800">No path to a subnet root. This device has no parent.</p>
      ) : null}
      {device.wlc ? (
        <p>Joined WLC <span className="font-mono-data">{device.wlc}</span></p>
      ) : null}
    </div>
  );
}

function Meta({ label, value, mono, link, shade }: { label: string; value: string; mono?: boolean; link?: string; shade?: string }) {
  const color = shadeColor(shade);
  return (
    <div
      className="min-w-[7.5rem] max-w-[16rem] rounded-lg border border-border bg-muted/40 px-3 py-1.5"
      style={color ? { boxShadow: `0 10px 16px -10px ${color}, inset 3px 0 0 ${color}` } : undefined}
    >
      <dt className="label-caps text-muted-foreground">{label}</dt>
      <dd className={`mt-0.5 truncate text-sm ${mono ? 'font-mono-data' : 'font-medium'}`} title={value}>
        {link ? <Link href={link} className="hover:text-primary hover:underline">{value}</Link> : value}
      </dd>
    </div>
  );
}