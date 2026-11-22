'use client';

import React, { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import Link from 'next/link';
import { toast } from 'sonner';
import Icon from '@/components/ui/AppIcon';
import ExampleDataBanner from '@/components/ui/ExampleDataBanner';
import { HealthBadge, StatusBadge } from '@/components/ui/Badge';
import { Skeleton } from '@/components/ui/Skeleton';
import Faceplate from '@/components/faceplate/Faceplate';
import ParentPortPicture from '@/components/faceplate/ParentPort';
import { FACEPLATE_HEIGHT } from '@/components/faceplate/size';
import { namesMatch } from '@/components/faceplate/library/ifname';
import { cableFlow, portIsUplink, rectsOverlap, type CableFlow } from './uplinkCable';
import { DeviceDiscoveryStatus, usePolledDeviceDiscovery } from '@/components/DeviceDiscoveryStatus';
import { api } from '@/lib/apiClient';
import { isApiError } from '@/lib/apiError';
import { devicePath, isMockMode } from '@/lib/apiMode';
import { request } from '@/lib/http';
import { deviceHealthPath } from '@/lib/deviceHealthPath';
import AddApDialog from '@/components/AddApDialog';
import { useKeyedLoad } from '@/lib/useKeyedLoad';
import { usePageQuery } from '@/lib/usePageQuery';
import { FACEPLATE_SAMPLES } from '@/lib/mockData';
import type { DeviceDiscoveryJob } from '@/lib/contract';
import type { AccessPointRadio, DeviceDetailData, HealthCause, InventorySide, PortInfo } from '@/lib/types';
import AccessPointList from './AccessPointList';
import CdpNeighbourPanel from './CdpNeighbourPanel';
import HealthCauses, { type HealthFilter } from './HealthCauses';
import HealthChecks from './HealthChecks';
import HardwareHealth from './HardwareHealth';
import PortSidePanel, { PortThroughputGraph } from './PortSidePanel';
import DeviceGraphs from './DeviceGraphs';
import PortTable from './PortTable';
import StackBadge, { stackMembersFor } from './StackBadge';

const FORMS = Object.keys(FACEPLATE_SAMPLES);
const NEEDS_ID = 'Open a device from the list. This page needs a device id.';
const BASE_TABS = [
  { id: 'inventory', label: 'Inventory' },
  { id: 'graphs', label: 'Graphs/Performance' },
  { id: 'interfaces', label: 'Interfaces' },
  { id: 'configs', label: 'Configs' },
  { id: 'logs', label: 'Logs' },
] as const;
type DetailTab = (typeof BASE_TABS)[number]['id'] | 'access-points';

function isWirelessController(device: DeviceDetailData | null | undefined): boolean {
  if (!device) return false;
  return Boolean(device.healthPanel?.wlc) || device.faceplate?.form_factor === 'wireless-controller';
}

function sectionTabs(wlc: boolean): { id: DetailTab; label: string }[] {
  if (!wlc) return [...BASE_TABS];
  return [BASE_TABS[0], { id: 'access-points', label: 'Access Points' }, ...BASE_TABS.slice(1)];
}

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
  const [detailTab, setDetailTab] = useState<DetailTab>('inventory');
  const [stageLocked, setStageLocked] = useState(false);
  const [addAp, setAddAp] = useState(false);
  const [cable, setCable] = useState<{ remotePort: string; localPort: string; plate: HTMLElement } | null>(null);
  const [stackPick, setStackPick] = useState<number | null>(null);
  const healthApplied = useRef('');
  const stageRef = useRef<HTMLDivElement>(null);
  const detailScroll = useRef<HTMLDivElement>(null);
  const localPlateRef = useRef<HTMLDivElement>(null);
  const greyRef = useRef<HTMLDivElement>(null);
  const parentPortRef = useRef<HTMLDivElement>(null);
  const discoveryJob = usePolledDeviceDiscovery(postedDiscovery, {
    onError: (job) => toast.error(job.message || 'Rediscover failed.'),
    onDone: () => toast.success('Rediscover finished.'),
  });

  const mockKey = pickedForm || (isFaceplateKey(formQuery) ? formQuery : '') || 'switch-stack';
  const deviceKey = live ? id : mockKey;
  const canLoad = ready && (!live || Boolean(id));
  const loaded = useKeyedLoad<DeviceDetailData>(deviceKey, canLoad, attempt, 'this device', (key) => api.getDevice(key));
  const device = loaded.data;
  const stackMembers = useMemo(() => (device ? stackMembersFor(device) : null), [device]);
  const activeStackMember = useMemo(() => {
    if (!stackMembers?.length) return undefined;
    if (stackPick != null && stackMembers.some((member) => member.number === stackPick)) return stackPick;
    return stackMembers.find((member) => member.master)?.number ?? stackMembers[0].number;
  }, [stackMembers, stackPick]);
  const parentLink = device?.parent ?? null;

  useEffect(() => {
    setSelected(null);
    setCable(null);
    setStackPick(null);
  }, [deviceKey]);

  useEffect(() => {
    const plate = parentPortRef.current;
    if (!parentLink || !plate) {
      setCable(null);
      return;
    }
    setCable({ remotePort: parentLink.parentInterface, localPort: parentLink.uplinkInterface, plate });
  }, [parentLink, device?.id]);

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
    if (tab === 'inventory' || tab === 'graphs' || tab === 'interfaces' || tab === 'configs' || tab === 'logs' || (tab === 'access-points' && isWirelessController(device))) {
      setDetailTab(tab);
    }
    if (tab !== 'health') return;
    const next: HealthFilter = severityQuery === 'critical' || severityQuery === 'warning' || severityQuery === 'info' ? severityQuery : 'all';
    setHealthFilter(next);
    setDetailTab('inventory');
    const stage = stageRef.current;
    if (stage && typeof stage.scrollIntoView === 'function') stage.scrollIntoView({ block: 'start' });
    window.requestAnimationFrame(() => {
      const section = document.getElementById('health');
      const scroller = detailScroll.current;
      if (!section || !scroller) return;
      const top = section.getBoundingClientRect().top - scroller.getBoundingClientRect().top + scroller.scrollTop;
      scroller.scrollTop = Math.max(0, top);
    });
  }, [device, tab, severityQuery]);

  useEffect(() => {
    const stage = stageRef.current;
    if (!stage) return undefined;
    const onScroll = () => {
      const locked = stage.getBoundingClientRect().top <= 68;
      setStageLocked((current) => (current === locked ? current : locked));
    };
    onScroll();
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, [device?.id]);

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

  const wlcView = isWirelessController(device);
  const tabs = sectionTabs(wlcView);

  useEffect(() => {
    if (detailTab === 'access-points' && !wlcView) setDetailTab('inventory');
  }, [detailTab, wlcView]);

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
    <div className="-mb-6 space-y-3">
      <nav aria-label="Breadcrumb" className="flex items-center gap-1.5 px-4 text-xs text-muted-foreground">
        <Link href="/" className="hover:text-foreground hover:underline">Devices</Link>
        <Icon name="ChevronRightIcon" size={12} />
        <span className="font-mono-data text-foreground">{device?.hostname ?? '…'}</span>
      </nav>

      {/* header */}
      <header className="rounded-none border-x-0 border-y border-border bg-card px-3 py-2 shadow-card">
        {device ? (
          <div className="min-w-0 space-y-2">
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
            </div>
            <div className="mt-2 flex flex-wrap items-start gap-3">
              <dl data-testid="device-header-facts" className="mr-auto grid w-max max-w-full grid-cols-2 gap-1.5 sm:grid-cols-4">
                <Meta label="Role" value={device.role} shade={device.roleColor} />
                <Meta label="Model" value={device.partNumber || device.faceplate.partNumber || device.faceplate.modelName || device.modelFamily} mono shade={toneShade(syncTones.tones.model)} />
                <Meta label="Serial number" value={device.serialMasked} mono shade={toneShade(syncTones.tones.serial)} />
                <Meta label="Site" value={device.site} link="/site-view" shade={toneShade(syncTones.tones.site)} />
                <Meta label="Management IP" value={device.mgmtIp} mono shade={device.reachable ? 'var(--success)' : undefined} />
                <Meta label="Uptime" value={device.uptime} mono shade={uptimeShade(device.uptime)} />
                <Meta label="Last poll" value={device.lastPoll} mono />
                <Meta label="Firmware" value={device.firmware} mono shade={toneShade(syncTones.tones.firmware)} />
              </dl>
            <div data-testid="device-header-actions" className="ml-auto flex shrink-0 items-start gap-1.5">
              {stackMembers && (
                <StackBadge
                  members={stackMembers}
                  deviceHealth={device.health}
                  deviceReason={deviceHealthReason(device.health, healthItems)}
                  selected={activeStackMember}
                  onSelect={setStackPick}
                />
              )}
              <div className="flex w-[12.5rem] shrink-0 flex-col gap-1">
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
                className="inline-flex min-h-10 items-center justify-center gap-1.5 rounded-md border border-border bg-card px-2 py-1.5 text-center text-[13px] font-medium leading-snug transition-all hover:bg-muted active:scale-95 disabled:opacity-50"
              >
                <Icon name="MagnifyingGlassIcon" size={14} />
                {rediscovering ? 'Rediscovering…' : 'Rediscover'}
              </button>
              <button
                type="button"
                onClick={() => {
                  setRerun(true);
                  setTimeout(() => setRerun(false), 1100);
                }}
                className="inline-flex min-h-10 items-center justify-center gap-1.5 rounded-md border border-border bg-card px-2 py-1.5 text-center text-[13px] font-medium leading-snug transition-all hover:bg-muted active:scale-95"
              >
                <Icon name="ArrowPathIcon" size={14} className={rerun ? 'animate-spin' : ''} />
                {rerun ? 'Running checks…' : 'Re-run health check'}
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
                className={`inline-flex min-h-10 items-center justify-center gap-1.5 rounded-md border border-transparent px-2 py-1.5 text-center text-[13px] font-medium leading-snug text-white transition-all active:scale-95 disabled:opacity-50 ${syncTones.synced ? 'bg-[#15803d] hover:bg-[#166534]' : 'bg-[#c2410c] hover:bg-[#9a3412]'}`}
              >
                <Icon name="ArrowsRightLeftIcon" size={14} />
                {syncing ? 'Syncing…' : 'NetBox Sync'}
              </button>
              <Link
                href={
                  isMockMode()
                    ? `/device-cli?form=${encodeURIComponent(form)}`
                    : `/device-cli?id=${encodeURIComponent(device?.id || id)}&form=${encodeURIComponent(form)}`
                }
                className="inline-flex min-h-10 items-center justify-center gap-1.5 rounded-md border border-border bg-card px-2 py-1.5 text-center text-[13px] font-medium leading-snug transition-all hover:bg-muted active:scale-95"
              >
                <Icon name="CommandLineIcon" size={14} />
                Open device
              </Link>
              </div>
            </div>
            </div>
            <DeviceDiscoveryStatus job={discoveryJob} />
          </div>
        ) : (
          <div className="space-y-3">
            <p role="status" className="sr-only">Loading device</p>
            <Skeleton className="h-8 w-72" />
            <Skeleton className="h-5 w-full max-w-3xl" />
          </div>
        )}
      </header>

      {device ? (
        <div ref={stageRef} data-testid="device-stage" className="sticky top-16 z-20 flex h-[calc(100dvh-4rem)] min-h-0 flex-col overflow-hidden bg-background">
          <section aria-label="Faceplate" data-testid="device-faceplate" className="shrink-0 rounded-none border-x-0 border-y border-border bg-card px-3 py-2 shadow-card">
            {isMockMode() ? (
              <div role="tablist" aria-label="Devices at this site" className="scroll-thin mb-2 flex gap-2 overflow-x-auto">
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
            <div ref={greyRef} className="relative flex items-stretch gap-0 overflow-hidden rounded-md bg-gradient-to-b from-secondary to-background p-1" style={{ height: FACEPLATE_HEIGHT }}>
              <div ref={localPlateRef} className="flex min-w-0 flex-1 items-stretch overflow-x-auto">
                <div className="w-full min-w-0">
                  <Faceplate
                    device={device.faceplate}
                    activeMember={activeStackMember}
                    selectedPortId={selected?.id ?? null}
                    onSelectPort={setSelected}
                    caption={false}
                    health={device.health}
                    chassisLabel={device.faceplate.modelName || device.modelFamily}
                  />
                </div>
              </div>
              <div className="mx-2 w-px shrink-0 bg-border" aria-hidden="true" />
              <aside data-testid="parent-device" className="flex w-44 shrink-0 flex-col justify-center overflow-visible px-2 py-1">
                <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">Parent Device</p>
                {parentLink ? (
                  <>
                    <Link href={devicePath(parentLink.id, parentLink.formFactor || 'generic')} className="mt-1 break-all font-mono-data text-sm font-semibold leading-tight text-foreground hover:text-primary hover:underline" title={parentLink.hostname}>
                      {parentLink.hostname}
                    </Link>
                    <div ref={parentPortRef} data-relation-id={parentLink.id} className="mt-2">
                      <ParentPortPicture name={parentLink.parentInterface} up={!parentLink.parentDown} />
                    </div>
                  </>
                ) : (
                  <p className="mt-1 text-sm text-muted-foreground">No parent detected</p>
                )}
              </aside>
              {cable && portIsUplink(selected, cable.localPort) ? (
                <UplinkCable localRef={localPlateRef} greyRef={greyRef} remote={cable.plate} localPortName={cable.localPort} remotePortName={cable.remotePort} flow={cableFlow(selected)} />
              ) : null}
            </div>
            {device.faceplate.form_factor === 'ceiling-ap' ? <ApRadioBoards device={device} /> : null}
          </section>
          <div role="tablist" aria-label="Device sections" className="flex shrink-0 gap-1 overflow-x-auto border-b border-border bg-card px-3">
            {tabs.map((item) => {
              const active = detailTab === item.id;
              return (
                <button
                  key={item.id}
                  type="button"
                  role="tab"
                  aria-selected={active}
                  onClick={() => {
                    setDetailTab(item.id);
                    if (detailScroll.current) detailScroll.current.scrollTop = 0;
                  }}
                  className={`shrink-0 border-b-2 px-3 py-2 text-sm font-medium transition-colors ${
                    active ? 'border-primary text-foreground' : 'border-transparent text-muted-foreground hover:text-foreground'
                  }`}
                >
                  {item.label}
                </button>
              );
            })}
          </div>
          <div ref={detailScroll} className={`min-h-0 flex-1 ${stageLocked ? 'overflow-y-auto' : 'overflow-y-hidden'}`}>
            {detailTab === 'inventory' ? (
              <div className="space-y-3 pb-4">
                {apDraft.length > 0 ? (
                  <div className="px-4 pt-3">
                    <button type="button" onClick={() => setAddAp(true)} className="rounded-md bg-primary px-3 py-1.5 text-sm font-semibold text-primary-foreground">Add to NetBox</button>
                    <AddApDialog open={addAp} aps={apDraft} onClose={() => setAddAp(false)} onDone={() => undefined} />
                  </div>
                ) : null}
                <section className="rounded-none border-x-0 border-y border-border bg-card shadow-card" aria-label="Device status overview">
                  <div className="grid grid-cols-1 items-stretch gap-3 p-3 xl:grid-cols-3">
                    <div className="h-[25.6rem] min-h-0">
                      <HealthCauses
                        items={healthItems}
                        health={device.health}
                        filter={healthFilter}
                        onFilter={setHealthFilter}
                        ports={allPorts}
                        onSelectPort={setSelected}
                      />
                    </div>
                    <div className="h-[25.6rem] min-h-0">
                      <HardwareHealth items={device.hardware ?? null} />
                    </div>
                    <div className="h-[25.6rem] min-h-0">
                      <HealthChecks checks={device.checks ?? null} runAt={device.checkRunAt ?? ''} running={rerun} />
                    </div>
                  </div>
                </section>
                {isMockMode() ? (
                  <ExampleDataBanner text="Device, port and graph values below come from mock JSON in the API client." />
                ) : (
                  <Inventory device={device} />
                )}
              </div>
            ) : null}
            {detailTab === 'graphs' ? (
              <div className="p-3">
                <DeviceGraphs deviceId={device.id} profile={device.healthPanel?.profile} />
              </div>
            ) : null}
            {detailTab === 'interfaces' ? (
              <div className="p-3">
                <PortTable ports={allPorts} selectedId={selected?.id ?? null} onSelect={setSelected} />
              </div>
            ) : null}
            {detailTab === 'configs' ? <ConfigBackup device={device} /> : null}
            {detailTab === 'logs' ? <DeviceLogs deviceId={device.id} hostname={device.hostname} /> : null}
            {detailTab === 'access-points' ? (
              <div className="pb-4">
                <AccessPointList wlc={device.hostname} />
              </div>
            ) : null}
          </div>
        </div>
      ) : null}

      {selected ? <PortDrawer port={selected} deviceId={device?.id} onClose={() => setSelected(null)} /> : null}
    </div>
  );
}

function PortDrawer({ port, deviceId, onClose }: { port: PortInfo; deviceId?: string; onClose: () => void }) {
  const panel = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    const onClick = (event: MouseEvent) => {
      const target = event.target;
      if (!(target instanceof Node) || panel.current?.contains(target)) return;
      if (target instanceof Element && target.closest('[data-port-id]')) return;
      onClose();
    };
    document.addEventListener('keydown', onKey);
    document.addEventListener('click', onClick);
    return () => {
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('click', onClick);
    };
  }, [onClose]);
  if (typeof document === 'undefined') return null;
  return createPortal(
    <div ref={panel} className="drawer-in fixed inset-y-0 right-0 z-[90] flex h-dvh w-full max-w-[420px] flex-col overflow-y-auto border-l border-border bg-card shadow-2xl" role="dialog" aria-modal="false" aria-label={`Port ${port.name} details`}>
      <PortSidePanel port={port} onClose={onClose} />
      <div className="px-4 pb-4">
        <PortThroughputGraph port={port} deviceId={deviceId} />
      </div>
    </div>,
    document.body,
  );
}

function Inventory({ device }: { device: DeviceDetailData }) {
  const sources = device.sources ?? [];
  return (
    <div className="space-y-3 rounded-none border-x-0 border-y border-border bg-card p-4 shadow-card">
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
      <CdpNeighbourPanel device={device} />
    </div>
  );
}

function configFileName(hostname: string): string {
  const clean = (hostname || 'device').replace(/[^A-Za-z0-9._-]+/g, '_');
  return `${clean}-config.txt`;
}

function downloadConfig(hostname: string, text: string) {
  const blob = new Blob([text], { type: 'text/plain;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = configFileName(hostname);
  link.click();
  URL.revokeObjectURL(url);
}

function ConfigBackup({ device }: { device: DeviceDetailData }) {
  const [config, setConfig] = useState(device.backup?.config || '');
  const [status, setStatus] = useState(device.backup?.status || '');
  const [at, setAt] = useState(device.backup?.at || '');
  const [reason, setReason] = useState(device.backup?.reason || '');
  const [available, setAvailable] = useState(Boolean(device.backup?.available));
  const [bytes, setBytes] = useState(0);
  const [loading, setLoading] = useState(!isMockMode());

  useEffect(() => {
    if (isMockMode()) return undefined;
    let cancel = false;
    setLoading(true);
    request<{ available?: boolean; reason?: string; status?: string; at?: string; config?: string; bytes?: number; hostname?: string }>(
      `/api/v1/devices/${encodeURIComponent(device.id)}/config`,
    )
      .then((body) => {
        if (cancel) return;
        setAvailable(Boolean(body.available));
        setConfig(body.config || '');
        setStatus(body.status || '');
        setAt(body.at || '');
        setReason(body.reason || '');
        setBytes(body.bytes || (body.config ? new Blob([body.config]).size : 0));
      })
      .catch((error) => {
        if (cancel) return;
        setAvailable(false);
        setConfig('');
        setReason(isApiError(error) ? error.message : 'The config could not be loaded.');
      })
      .finally(() => {
        if (!cancel) setLoading(false);
      });
    return () => {
      cancel = true;
    };
  }, [device.id]);

  return (
    <div className="p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold">Last config backup</h2>
        <button
          type="button"
          disabled={!config}
          onClick={() => downloadConfig(device.hostname, config)}
          className="rounded-md bg-navy px-3 py-1.5 text-xs font-semibold text-primary-foreground disabled:opacity-50"
        >
          Download .txt
        </button>
      </div>
      {at || status || bytes ? (
        <p className="mt-1 text-xs text-muted-foreground">
          {[at, status, bytes ? `${bytes.toLocaleString()} bytes` : ''].filter(Boolean).join(' · ')}
        </p>
      ) : null}
      {loading ? <p className="mt-3 text-sm text-muted-foreground">Loading the full config…</p> : null}
      {!loading && config ? (
        <pre className="mt-2 max-h-[70vh] overflow-auto whitespace-pre-wrap rounded-md bg-muted p-3 font-mono-data text-xs">{config}</pre>
      ) : null}
      {!loading && !config ? (
        <p className="mt-1 text-sm text-muted-foreground">{reason || (available ? 'Oxidized has no config text for this device.' : 'Oxidized has no backup for this device.')}</p>
      ) : null}
    </div>
  );
}

function DeviceLogs({ deviceId, hostname }: { deviceId: string; hostname: string }) {
  const [lines, setLines] = useState<{ at: string; severity: string; message: string }[]>([]);
  const [reason, setReason] = useState('');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancel = false;
    setLoading(true);
    api.getDeviceLogs(deviceId, hostname)
      .then((body) => {
        if (cancel) return;
        setLines(body.lines || []);
        setReason(body.reason || '');
      })
      .catch((error) => {
        if (cancel) return;
        setLines([]);
        setReason(isApiError(error) ? error.message : 'Syslog could not be loaded.');
      })
      .finally(() => {
        if (!cancel) setLoading(false);
      });
    return () => {
      cancel = true;
    };
  }, [deviceId, hostname]);

  return (
    <div className="p-4">
      <h2 className="text-sm font-semibold">Syslog</h2>
      <p className="mt-1 text-xs text-muted-foreground">Lines stored for {hostname} during the last day.</p>
      {loading ? <p className="mt-3 text-sm text-muted-foreground">Loading logs…</p> : null}
      {!loading && lines.length === 0 ? <p className="mt-3 text-sm text-muted-foreground">{reason || 'No syslog lines for this device.'}</p> : null}
      {lines.length > 0 ? (
        <ul className="mt-3 space-y-1 font-mono-data text-xs">
          {lines.map((line, index) => (
            <li key={`${line.at}-${index}`} className="grid grid-cols-[9.5rem_4.5rem_minmax(0,1fr)] gap-2 border-b border-border/60 py-1">
              <span className="text-muted-foreground">{line.at}</span>
              <span>{line.severity || '—'}</span>
              <span className="break-all">{line.message}</span>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function bandName(radio: AccessPointRadio, fallback?: string): string {
  const band = (radio.band || fallback || '').trim();
  if (!band) return radio.slot ? `Radio ${radio.slot}` : 'Radio';
  const text = band.toLowerCase();
  if (/6\s?ghz|802\.?11.?6/.test(text)) return '6 GHz';
  if (/802\.?11bg|802\.?11b|802\.?11g|2\.4|24\s?ghz/.test(text)) return '2.4 GHz';
  if (/802\.?11a|5\s?ghz/.test(text)) return '5 GHz';
  if (/ghz/i.test(band)) return band;
  return `${band} GHz`;
}

function bandRank(title: string): number {
  const found = title.match(/(\d+(?:\.\d+)?)/);
  return found ? Number(found[1]) : 1000;
}

function reading(value: number | null | undefined, unit: string): string {
  if (value == null || Number.isNaN(Number(value))) return '—';
  const number = Number(value);
  const shown = Number.isInteger(number) ? String(number) : number.toFixed(1);
  return `${shown} ${unit}`;
}

function asPercent(value: number | null | undefined): number | null {
  if (value == null || Number.isNaN(Number(value))) return null;
  const number = Number(value);
  return Math.abs(number) <= 1 ? number * 100 : number;
}

function parseDbm(value?: string): number | null {
  if (!value) return null;
  const found = value.match(/-?\d+(\.\d+)?/);
  return found ? Number(found[0]) : null;
}

type Tone = 'good' | 'fair' | 'poor' | 'none';

function toneColor(tone: Tone): string {
  if (tone === 'good') return 'var(--success)';
  if (tone === 'fair') return 'var(--warning)';
  if (tone === 'poor') return 'var(--destructive)';
  return 'var(--muted-foreground)';
}

function snrTone(value: number | null): Tone {
  if (value == null) return 'none';
  if (value >= 25) return 'good';
  if (value >= 15) return 'fair';
  return 'poor';
}

function rssiTone(value: number | null): Tone {
  if (value == null) return 'none';
  if (value >= -67) return 'good';
  if (value >= -75) return 'fair';
  return 'poor';
}

function signalTone(value: number | null): Tone {
  if (value == null) return 'none';
  if (value >= 70) return 'good';
  if (value >= 40) return 'fair';
  return 'poor';
}

function interferenceTone(value: number | null): Tone {
  if (value == null) return 'none';
  if (value <= 10) return 'good';
  if (value <= 25) return 'fair';
  return 'poor';
}

function worstTone(tones: Tone[]): Tone {
  if (tones.includes('poor')) return 'poor';
  if (tones.includes('fair')) return 'fair';
  if (tones.includes('good')) return 'good';
  return 'none';
}

function ApRadioBoards({ device }: { device: DeviceDetailData }) {
  const live = device.healthPanel?.accessPoint?.radios ?? [];
  const drawn = device.faceplate.radios ?? [];
  const boards = (live.length
    ? live.map((radio, index) => {
        const snr = radio.snrAvg ?? null;
        const rssi = radio.rssiAvg ?? null;
        const interference = asPercent(radio.interference);
        const fromSnr = snr == null ? null : Math.max(0, Math.min(100, (snr / 40) * 100));
        const fromRssi = rssi == null ? null : Math.max(0, Math.min(100, ((rssi + 90) / 50) * 100));
        return {
          id: `${radio.slot || index}`,
          slot: radio.slot || String(index),
          title: bandName(radio),
          channel: radio.channel ?? '—',
          clients: radio.clients ?? null,
          operUp: radio.operUp ?? null,
          snr,
          rssi,
          signal: fromSnr ?? fromRssi,
          interference,
        };
      })
    : drawn.map((radio) => {
        const rssi = parseDbm(radio.avgRssi);
        return {
          id: radio.id,
          slot: radio.id,
          title: radio.band,
          channel: radio.channel,
          clients: radio.clients,
          operUp: null as boolean | null,
          snr: null as number | null,
          rssi,
          signal: rssi == null ? null : Math.max(0, Math.min(100, ((rssi + 90) / 50) * 100)),
          interference: null as number | null,
        };
      })
  ).sort((left, right) => bandRank(left.title) - bandRank(right.title) || left.title.localeCompare(right.title));

  return (
    <div className="mt-2 grid auto-cols-fr grid-flow-col gap-2" role="region" aria-label="Radio performance">
      {boards.length === 0 ? (
        <p className="rounded-lg border border-border bg-muted/40 px-3 py-3 text-xs text-muted-foreground">The controller has not returned radio readings for this access point.</p>
      ) : boards.map((board) => {
        const down = board.operUp === false;
        const missing = down ? 'Radio is down' : live.length ? 'Not returned for this radio' : 'Not sampled';
        const tones = down ? [] : [snrTone(board.snr), rssiTone(board.rssi), signalTone(board.signal), interferenceTone(board.interference)];
        const verdict = down ? 'poor' : worstTone(tones);
        const verdictLabel = down ? 'Down' : verdict === 'good' ? 'Healthy' : verdict === 'fair' ? 'Watch' : verdict === 'poor' ? 'Poor' : 'No sample';
        const rows = [
          { label: 'SNR', value: reading(board.snr, 'dB'), hint: board.snr == null ? missing : board.snr >= 25 ? 'Clear of noise' : board.snr >= 15 ? 'Some noise' : 'Hard to hear', tone: snrTone(board.snr), bar: board.snr == null ? 0 : Math.max(0, Math.min(100, (board.snr / 40) * 100)) },
          { label: 'RSSI', value: reading(board.rssi, 'dBm'), hint: board.rssi == null ? missing : board.rssi >= -67 ? 'Strong at the client' : board.rssi >= -75 ? 'Usable' : 'Weak at the client', tone: rssiTone(board.rssi), bar: board.rssi == null ? 0 : Math.max(0, Math.min(100, ((board.rssi + 90) / 50) * 100)) },
          { label: 'Signal', value: board.signal == null ? '—' : `${Math.round(board.signal)}%`, hint: board.signal == null ? missing : board.signal >= 70 ? 'Strong link' : board.signal >= 40 ? 'Fair link' : 'Weak link', tone: signalTone(board.signal), bar: board.signal ?? 0 },
          { label: 'Interference', value: board.interference == null ? '—' : `${Math.round(board.interference)}%`, hint: board.interference == null ? missing : board.interference <= 10 ? 'Quiet channel' : board.interference <= 25 ? 'Some competition' : 'Busy channel', tone: interferenceTone(board.interference), bar: board.interference ?? 0 },
        ];
        return (
          <article key={board.id} className="flex min-w-[9.5rem] flex-col rounded-lg border border-border bg-card px-2.5 py-2 shadow-card" aria-label={`${board.title} radio`}>
            <div className="flex items-start justify-between gap-2">
              <h3 className="text-sm font-semibold text-foreground">{board.title}</h3>
              <span className="rounded-full border px-1.5 py-0.5 text-[10px] font-semibold" style={{ color: toneColor(verdict), borderColor: toneColor(verdict) }}>{verdictLabel}</span>
            </div>
            <p className="mt-0.5 font-mono-data text-[11px] text-muted-foreground">
              Radio {board.slot} · Channel {board.channel}{board.clients != null ? ` · ${board.clients} clients` : ''}
            </p>
            <dl className="mt-2 space-y-1.5">
              {rows.map((row) => (
                <div key={row.label}>
                  <div className="flex items-baseline justify-between gap-2 text-[11px]">
                    <dt className="text-muted-foreground">{row.label}</dt>
                    <dd className="font-mono-data font-semibold" style={{ color: toneColor(row.tone) }}>{row.value}</dd>
                  </div>
                  <div className="mt-0.5 h-1 overflow-hidden rounded-full bg-muted" aria-hidden="true">
                    <div className="h-full rounded-full" style={{ width: `${Math.max(0, Math.min(100, row.bar))}%`, backgroundColor: toneColor(row.tone) }} />
                  </div>
                  <p className="mt-0.5 text-[10px] leading-tight text-muted-foreground">{row.hint}</p>
                </div>
              ))}
            </dl>
          </article>
        );
      })}
    </div>
  );
}

function shadeColor(shade?: string): string {
  const text = (shade || '').trim();
  if (/^[0-9a-fA-F]{6}$/.test(text)) return `#${text}`;
  return text;
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
  const localX = (rect: DOMRect) => rect.left - grey.left + rect.width / 2;
  const localY = (rect: DOMRect) => rect.top - grey.top + rect.height / 2;
  const x = localX(port);
  const y = localY(port);
  const hug = 6;
  const laneY = Math.min(grey.height - hug, chassis.bottom - grey.top + hug);
  const endX = remotePort ? localX(remotePort) : remoteBox.left - grey.left + remoteBox.width / 2;
  // A short marker sits on the bottom edge of the jack. Stop inside that edge so the line enters the port and misses the label beside it.
  const rawEndY = remotePort
    ? (remotePort.height <= 12 ? remotePort.top - grey.top + 2 : remotePort.bottom - grey.top - 4)
    : remoteBox.top - grey.top + remoteBox.height / 2;
  const endY = Math.max(hug, Math.min(grey.height - hug, rawEndY));
  return cablePath([
    { x, y },
    { x, y: laneY },
    { x: endX, y: laneY },
    { x: endX, y: endY },
  ]);
}

export function UplinkCable({
  localRef,
  greyRef,
  remote,
  localPortName,
  remotePortName,
  flow,
}: {
  localRef: React.RefObject<HTMLDivElement | null>;
  greyRef: React.RefObject<HTMLDivElement | null>;
  remote: HTMLElement;
  localPortName: string;
  remotePortName: string;
  flow: CableFlow | null;
}) {
  const [path, setPath] = useState('');
  const [size, setSize] = useState({ w: 0, h: 0 });
  const [reduceMotion, setReduceMotion] = useState(false);
  useEffect(() => {
    const media = window.matchMedia?.('(prefers-reduced-motion: reduce)');
    if (!media) return undefined;
    const apply = () => setReduceMotion(media.matches);
    apply();
    media.addEventListener?.('change', apply);
    return () => media.removeEventListener?.('change', apply);
  }, []);
  useEffect(() => {
    const local = localRef.current;
    const grey = greyRef.current;
    if (!local || !grey || !remote) return;
    const measure = () => {
      const localPort = findPort(local, localPortName);
      const remotePort = findPort(remote, remotePortName);
      const greyBox = grey.getBoundingClientRect();
      if (!localPort || greyBox.width < 2 || greyBox.height < 2) {
        setPath('');
        return;
      }
      const portBox = localPort.getBoundingClientRect();
      const localBox = local.getBoundingClientRect();
      if ((portBox.width < 1 && portBox.height < 1) || !rectsOverlap(portBox, localBox)) {
        setPath('');
        return;
      }
      const metals = local.querySelectorAll('[data-chassis]');
      const metal = metals.length ? metals[metals.length - 1] : null;
      const remoteBox = remote.getBoundingClientRect();
      setSize({ w: greyBox.width, h: greyBox.height });
      setPath(outsideCable(portBox, metal ? metal.getBoundingClientRect() : localBox, remotePort ? remotePort.getBoundingClientRect() : null, remoteBox, greyBox));
    };
    measure();
    if (typeof ResizeObserver === 'undefined') return undefined;
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
  if (!path || size.w <= 0) return null;
  const moving = Boolean(flow) && !reduceMotion;
  const travel = (towardParent: boolean) => (moving ? {
    animation: `ie-cable-flow ${flow!.seconds}s linear infinite`,
    animationDirection: towardParent ? 'normal' : 'reverse',
  } as const : undefined);
  return (
    <svg data-testid="uplink-cable" data-cable-flow={moving ? 'live' : 'idle'} width={size.w} height={size.h} viewBox={`0 0 ${size.w} ${size.h}`} style={{ position: 'absolute', left: 0, top: 0, zIndex: 5, pointerEvents: 'none' }} aria-hidden="true">
      <style>{'@keyframes ie-cable-flow { to { stroke-dashoffset: -32; } }'}</style>
      <path d={path} fill="none" stroke="#1e293b" strokeWidth={7} strokeLinejoin="miter" strokeLinecap="butt" />
      <path d={path} fill="none" stroke="#3b82f6" strokeWidth={3} strokeLinejoin="miter" strokeLinecap="butt" />
      {moving && flow!.outbound ? <path data-testid="cable-flow-out" d={path} fill="none" stroke="#e0f2fe" strokeWidth={1.6} strokeDasharray="4 12" strokeLinecap="round" style={travel(true)} /> : null}
      {moving && flow!.inbound ? <path data-testid="cable-flow-in" d={path} fill="none" stroke="#bbf7d0" strokeWidth={1.6} strokeDasharray="4 12" strokeLinecap="round" style={travel(false)} /> : null}
    </svg>
  );
}

function deviceHealthReason(health: string, items: HealthCause[]): string {
  const rank: Record<string, number> = { healthy: 0, warning: 1, critical: 2, unreachable: 3 };
  let best: HealthCause | null = null;
  let bestRank = 0;
  for (const item of items) {
    const score = rank[item.effect || item.severity] || 0;
    if (score > bestRank) {
      best = item;
      bestRank = score;
    }
  }
  if (!best) return `Device is ${health}`;
  return `${best.title}. ${best.detail}`;
}

function Meta({ label, value, mono, link, shade }: { label: string; value: string; mono?: boolean; link?: string; shade?: string }) {
  const color = shadeColor(shade);
  return (
    <div
      data-testid="header-fact"
      className="flex h-12 w-[9.3rem] shrink-0 flex-col justify-center overflow-hidden rounded-md border border-border bg-muted/40 px-1.5"
      style={color ? { boxShadow: `inset 3px 0 0 ${color}` } : undefined}
    >
      <dt className="truncate text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{label}</dt>
      <dd className={`truncate text-[13px] leading-tight ${mono ? 'font-mono-data' : 'font-medium'}`} title={value}>
        {link ? <Link href={link} className="hover:text-primary hover:underline">{value}</Link> : value}
      </dd>
    </div>
  );
}