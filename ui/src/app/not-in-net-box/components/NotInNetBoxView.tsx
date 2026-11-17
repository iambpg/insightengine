'use client';

import React, { useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';
import Icon from '@/components/ui/AppIcon';
import Badge from '@/components/ui/Badge';
import EmptyState from '@/components/ui/EmptyState';
import ExampleDataBanner from '@/components/ui/ExampleDataBanner';
import { isMockMode } from '@/lib/apiMode';
import Modal from '@/components/ui/Modal';
import Pagination from '@/components/ui/Pagination';
import { TableSkeleton } from '@/components/ui/Skeleton';
import { DeviceDiscoveryStatus, usePolledDeviceDiscovery } from '@/components/DeviceDiscoveryStatus';
import { api } from '@/lib/apiClient';
import { reportLoadError } from '@/lib/loadError';
import { isApiError } from '@/lib/apiError';
import type { DeviceDiscoveryJob, DiscoveryCatalog, DiscoveryScan, UnapprovedDevice } from '@/lib/contract';
import { allowOperate } from '@/lib/settings/access';
import { useKnownRole } from '@/lib/useSession';

type DiscoveredPage = { rows: UnapprovedDevice[]; total: number };

function isPage(value: unknown): value is DiscoveredPage {
  return !!value && typeof value === 'object' && Array.isArray((value as DiscoveredPage).rows);
}

function roleNames(catalog: DiscoveryCatalog, current?: string): string[] {
  const fromChoices = (catalog.roleChoices ?? []).map((choice) => choice.name).filter(Boolean);
  const names = fromChoices.length ? fromChoices : catalog.roles;
  const selected = roleValue(catalog, current);
  if (selected && !names.includes(selected)) return [selected, ...names];
  return names;
}

function roleValue(catalog: DiscoveryCatalog, current?: string): string {
  if (!current) return '';
  const hit = (catalog.roleChoices ?? []).find((choice) => choice.name === current || choice.slug === current);
  return hit?.name || current;
}

function siteNames(catalog: DiscoveryCatalog, current?: string): string[] {
  const fromChoices = (catalog.siteChoices ?? []).map((choice) => choice.name).filter(Boolean);
  const names = fromChoices.length ? fromChoices : catalog.sites;
  const selected = siteValue(catalog, current);
  if (selected && !names.includes(selected)) return [selected, ...names];
  return names;
}

function siteValue(catalog: DiscoveryCatalog, current?: string): string {
  if (!current) return '';
  const hit = (catalog.siteChoices ?? []).find((choice) => choice.name === current || choice.slug === current);
  return hit?.name || current;
}

const NO_GROUP = 'No group';

function tenantGroups(catalog: DiscoveryCatalog): string[] {
  const names = (catalog.tenantGroups ?? []).map((group) => group.name).filter(Boolean);
  for (const tenant of catalog.tenants ?? []) {
    if (tenant.group && !names.includes(tenant.group)) names.push(tenant.group);
  }
  const ungrouped = (catalog.tenants ?? []).some((tenant) => !tenant.group);
  return ungrouped ? [...names, NO_GROUP] : names;
}

function groupFor(catalog: DiscoveryCatalog, tenant?: string): string {
  if (!tenant) return '';
  const hit = (catalog.tenants ?? []).find((row) => row.name === tenant || row.slug === tenant);
  if (!hit) return '';
  return hit.group || NO_GROUP;
}

function tenantsIn(catalog: DiscoveryCatalog, group: string): string[] {
  if (!group) return [];
  const want = group === NO_GROUP ? '' : group;
  return (catalog.tenants ?? []).filter((tenant) => (tenant.group || '') === want).map((tenant) => tenant.name);
}

const EMPTY_CATALOG: DiscoveryCatalog = { roles: [], sites: [], platforms: [] };

function stamp(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toISOString().replace('T', ' ').slice(0, 16);
}

export default function NotInNetBoxView({ embedded = false }: { embedded?: boolean }) {
  const canWrite = allowOperate(useKnownRole());
  const [items, setItems] = useState<UnapprovedDevice[] | null>(null);
  const [serverPaged, setServerPaged] = useState(false);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [bulkRole, setBulkRole] = useState('');
  const [bulkSite, setBulkSite] = useState('');
  const [bulkGroup, setBulkGroup] = useState('');
  const [bulkTenant, setBulkTenant] = useState('');
  const [groupPick, setGroupPick] = useState<Record<string, string>>({});
  const [scans, setScans] = useState<DiscoveryScan[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [selected, setSelected] = useState<string[]>([]);
  const [confirm, setConfirm] = useState<{ ids: string[]; mode: 'approve' | 'reject' } | null>(
    null
  );
  const [form, setForm] = useState({ role: '', site: '', tenant: '', tenantGroup: '', name: '', platform: '' });
  const [busy, setBusy] = useState(false);
  const [reload, setReload] = useState(0);
  const [catalog, setCatalog] = useState<DiscoveryCatalog>(EMPTY_CATALOG);
  const [target, setTarget] = useState<'ip' | 'prefix'>('ip');
  const [scanValue, setScanValue] = useState('');
  const [neighbours, setNeighbours] = useState(false);
  const [scanning, setScanning] = useState(false);
  const [posted, setPosted] = useState<DeviceDiscoveryJob | null>(null);
  const [highlightIp, setHighlightIp] = useState<string | null>(null);
  const discoveryJob = usePolledDeviceDiscovery(posted, {
    onDone: (job) => {
      setHighlightIp(job.ip);
      api
        .listDiscovered()
        .then((data) => applyList(data))
        .catch(() => undefined);
      toast.success('Discovery finished. If the device is not in NetBox, it is in this list, including one you deleted there.');
    },
    onError: (job) => toast.error(job.message || 'Discovery failed.'),
  });

  const applyList = (data: UnapprovedDevice[] | DiscoveredPage) => {
    if (isPage(data) && !Array.isArray(data)) {
      setServerPaged(true);
      setItems(data.rows);
      setTotal(data.total);
      return;
    }
    const rows = data as UnapprovedDevice[];
    setServerPaged(false);
    setItems(rows);
    setTotal(rows.length);
  };

  const load = () => {
    setItems(null);
    setError(null);
    Promise.all([api.listDiscovered({ page, pageSize, q: search }), api.listScans()])
      .then(([devices, recent]) => {
        applyList(devices as UnapprovedDevice[] | DiscoveredPage);
        setScans(recent);
      })
      .catch((cause) => setError(reportLoadError(cause, 'discovered devices')));
  };

  useEffect(() => {
    let cancelled = false;
    api
      .discoveryCatalog()
      .then((data) => {
        if (!cancelled) {
          setCatalog({
            roles: data.roles ?? [],
            roleChoices: data.roleChoices,
            sites: data.sites ?? [],
            siteChoices: data.siteChoices,
            platforms: data.platforms ?? [],
            tenantGroups: data.tenantGroups ?? [],
            tenants: data.tenants ?? [],
          });
        }
      })
      .catch(() => {
        if (!cancelled) setCatalog(EMPTY_CATALOG);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    setItems(null);
    setError(null);
    Promise.all([api.listDiscovered({ page, pageSize, q: search }), api.listScans()])
      .then(([devices, recent]) => {
        if (cancelled) return;
        applyList(devices as UnapprovedDevice[] | DiscoveredPage);
        setScans(recent);
      })
      .catch((cause) => {
        if (!cancelled) setError(reportLoadError(cause, 'discovered devices'));
      });
    return () => {
      cancelled = true;
    };
  }, [reload, page, pageSize, search]);

  const view = useMemo(() => {
    if (!items) return null;
    if (serverPaged) return { rows: items, total };
    const needle = search.trim().toLowerCase();
    const filtered = items.filter((device) => {
      if (!needle) return true;
      const hay = [
        device.sysName,
        device.hostname,
        device.ip,
        device.vendor,
        device.model,
        device.suggested.site,
        device.suggested.role,
        device.suggested.tenant,
      ]
        .filter(Boolean)
        .join(' ')
        .toLowerCase();
      return hay.includes(needle);
    });
    const start = (page - 1) * pageSize;
    return { rows: filtered.slice(start, start + pageSize), total: filtered.length };
  }, [items, search, serverPaged, total, page, pageSize]);
  const rows = view?.rows ?? null;

  const saveRole = async (ids: string[], role: string) => {
    const chosen = role.trim();
    if (!chosen || ids.length === 0) return;
    setItems((current) =>
      current?.map((device) =>
        ids.includes(device.id) ? { ...device, suggested: { ...device.suggested, role: chosen } } : device
      ) ?? current
    );
    try {
      await api.setDeviceRoles(ids, chosen);
    } catch (cause) {
      toast.error(isApiError(cause) ? cause.message : 'The role was not saved.');
      setReload((value) => value + 1);
    }
  };

  const saveSite = async (ids: string[], site: string) => {
    const chosen = site.trim();
    if (!chosen || ids.length === 0) return;
    setItems((current) =>
      current?.map((device) =>
        ids.includes(device.id) ? { ...device, suggested: { ...device.suggested, site: chosen } } : device
      ) ?? current
    );
    try {
      await api.setDeviceSites(ids, chosen);
    } catch (cause) {
      toast.error(isApiError(cause) ? cause.message : 'The site was not saved.');
      setReload((value) => value + 1);
    }
  };

  const saveTenant = async (ids: string[], tenant: string) => {
    const chosen = tenant.trim();
    if (ids.length === 0) return;
    setItems((current) =>
      current?.map((device) =>
        ids.includes(device.id) ? { ...device, suggested: { ...device.suggested, tenant: chosen } } : device
      ) ?? current
    );
    try {
      await api.setDeviceTenants(ids, chosen);
    } catch (cause) {
      toast.error(isApiError(cause) ? cause.message : 'The tenant was not saved.');
      setReload((value) => value + 1);
    }
  };

  const allOn = !!rows && rows.length > 0 && rows.every((row) => selected.includes(row.id));

  const ask = (ids: string[], mode: 'approve' | 'reject') => {
    if (mode === 'approve' && ids.length === 1) {
      const device = items?.find((item) => item.id === ids[0]);
      setForm({
        role: device?.suggested.role ?? '',
        site: device?.suggested.site ?? '',
        tenant: device?.suggested.tenant ?? '',
        tenantGroup: groupFor(catalog, device?.suggested.tenant),
        name: device?.sysName || device?.hostname || '',
        platform: device?.suggested.platform ?? device?.platform ?? '',
      });
    }
    setConfirm({ ids, mode });
  };

  const run = async () => {
    if (!confirm) return;
    setBusy(true);
    const { ids, mode } = confirm;
    try {
      if (mode === 'reject') {
        await Promise.all(ids.map((id) => api.rejectDevice(id)));
      } else if (ids.length === 1) {
        if (!form.role.trim() || !form.site.trim() || !form.tenant.trim()) {
          toast.error('Role, site, and tenant are required to create the device in NetBox.');
          setBusy(false);
          return;
        }
        await api.approveDevice(ids[0], {
          role: form.role.trim(),
          site: form.site.trim(),
          tenant: form.tenant.trim(),
          name: form.name.trim() || undefined,
          platform: form.platform.trim() || undefined,
        });
      } else {
        const missing = ids.filter((id) => {
          const device = items?.find((item) => item.id === id);
          return !device?.suggested.role || !device.suggested.site || !device.suggested.tenant;
        });
        if (missing.length) {
          toast.error(
            'Some selected devices have no suggested role, site, or tenant. Approve those one at a time.'
          );
          setBusy(false);
          return;
        }
        await Promise.all(
          ids.map((id) => {
            const device = items?.find((item) => item.id === id);
            return api.approveDevice(id, {
              role: device?.suggested.role ?? '',
              site: device?.suggested.site ?? '',
              tenant: device?.suggested.tenant ?? '',
              name: device?.sysName,
              platform: device?.suggested.platform,
            });
          })
        );
      }
      setItems((current) => current?.filter((device) => !ids.includes(device.id)) ?? current);
      setSelected((current) => current.filter((id) => !ids.includes(id)));
      setConfirm(null);
      toast.success(
        mode === 'approve'
          ? `${ids.length} ${ids.length === 1 ? 'device' : 'devices'} approved and created in NetBox`
          : `${ids.length} ${ids.length === 1 ? 'device' : 'devices'} rejected`
      );
    } catch (error) {
      toast.error(
        isApiError(error) ? error.message : 'The request failed. No devices were changed.'
      );
    } finally {
      setBusy(false);
    }
  };

  const discover = async () => {
    setScanning(true);
    try {
      if (target === 'ip') {
        const job = await api.discoverDevice(scanValue.trim(), neighbours);
        setPosted(job);
        setScanValue('');
      } else {
        const scan = await api.startScan(target, scanValue);
        setScans((current) => [scan, ...(current ?? [])]);
        setScanValue('');
        toast.success(scan.message || 'Scan queued.');
      }
    } catch (error) {
      toast.error(isApiError(error) ? error.message : 'The scan could not be started.');
    } finally {
      setScanning(false);
    }
  };

  const labelFor = (device: UnapprovedDevice) => device.sysName || device.hostname || device.ip;

  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-end justify-between gap-3 px-4">
        <div>
          {embedded ? (
            <h2 className="text-lg font-semibold tracking-tight">Not in NetBox</h2>
          ) : (
            <h1 className="text-2xl font-semibold tracking-tight">Not in NetBox</h1>
          )}
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
            Devices that discovery found on the network but that are not yet approved in the
            inventory. Approving creates the device in NetBox and starts monitoring it.
          </p>
        </div>
        <div className="flex items-center gap-2 rounded-md border border-warning/40 bg-warning/10 px-3 py-2 text-sm">
          <Icon name="ExclamationTriangleIcon" size={16} variant="solid" className="text-warning" />
          <span className="font-semibold tabular">{items?.length ?? '—'}</span>
          <span className="text-muted-foreground">awaiting approval</span>
        </div>
      </header>

      {isMockMode() ? <ExampleDataBanner /> : null}

      <p className="rounded-md border border-info/30 bg-info/10 px-3 py-2 text-sm">
        Add a device or define an IP range (prefix) in NetBox and Netdisco scans it automatically.
      </p>

      <section
        className="rounded-md border border-border bg-card p-4 shadow-card"
        aria-label="Discover"
      >
        <h2 className="text-sm font-semibold">Discover device</h2>
        <p className="mt-1 text-xs text-muted-foreground">
          Enter an IP to discover that device, or a prefix to queue a walk. Scheduled scans still follow NetBox.
        </p>
        <form
          className="mt-3 flex flex-wrap items-end gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            discover();
          }}
        >
          <label className="text-sm">
            <span className="text-muted-foreground">Target</span>
            <select
              aria-label="Discover target"
              value={target}
              onChange={(event) => setTarget(event.target.value as 'ip' | 'prefix')}
              className="mt-1 block h-9 rounded-md border border-input bg-card px-2"
            >
              <option value="ip">IP address</option>
              <option value="prefix">Prefix</option>
            </select>
          </label>
          <label className="min-w-[220px] flex-1 text-sm">
            <span className="text-muted-foreground">
              {target === 'ip' ? 'IP address' : 'Prefix'}
            </span>
            <input
              aria-label={target === 'ip' ? 'IP address' : 'Prefix'}
              value={scanValue}
              onChange={(event) => setScanValue(event.target.value)}
              placeholder={target === 'ip' ? '10.22.14.80' : '10.22.14.0/24'}
              className="mt-1 h-9 w-full rounded-md border border-input bg-background px-3 font-mono-data text-sm"
            />
          </label>
          {target === 'ip' ? (
            <label className="flex h-9 items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={neighbours}
                onChange={(event) => setNeighbours(event.target.checked)}
              />
              Also discover CDP/LLDP neighbours
            </label>
          ) : null}
          <button
            type="submit"
            disabled={scanning || !scanValue.trim()}
            className="inline-flex h-9 items-center gap-1.5 rounded-md bg-navy px-3 text-sm font-semibold text-primary-foreground disabled:opacity-50"
          >
            <Icon name="MagnifyingGlassIcon" size={14} />
            {scanning ? 'Discovering…' : 'Discover'}
          </button>
        </form>
        <DeviceDiscoveryStatus job={discoveryJob} />
        {scans && scans.length > 0 ? (
          <ul
            className="mt-3 divide-y divide-border rounded-md border border-border text-sm"
            aria-label="Scan status"
          >
            {scans.map((scan) => (
              <li key={scan.id} className="flex flex-wrap items-center gap-2 px-3 py-2">
                <Badge
                  tone={
                    scan.status === 'failed'
                      ? 'destructive'
                      : scan.status === 'finished'
                        ? 'success'
                        : 'info'
                  }
                >
                  {scan.status}
                </Badge>
                <span className="font-mono-data text-xs">
                  {scan.target} {scan.value}
                </span>
                <span className="text-xs text-muted-foreground">{scan.message}</span>
              </li>
            ))}
          </ul>
        ) : null}
      </section>

      <section
        className="rounded-none border-x-0 border-y border-border bg-card shadow-card"
        aria-label="Discovered devices"
      >
        <div className="flex flex-wrap items-center gap-2 border-b border-border p-4">
          <label className="relative min-w-[220px] flex-1 sm:max-w-sm">
            <span className="sr-only">Search discovered devices</span>
            <Icon
              name="MagnifyingGlassIcon"
              size={16}
              className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground"
            />
            <input
              type="search"
              value={search}
              onChange={(event) => {
                setSearch(event.target.value);
                setPage(1);
              }}
              placeholder="sysName, IP, vendor or site…"
              className="h-9 w-full rounded-md border border-input bg-background pl-9 pr-3 text-sm outline-none focus:border-ring"
            />
          </label>
          <button
            type="button"
            onClick={() => setReload((value) => value + 1)}
            className="ml-auto inline-flex h-9 items-center gap-1.5 rounded-md border border-border bg-card px-3 text-sm font-medium hover:bg-muted"
          >
            <Icon name="ArrowPathIcon" size={14} /> Refresh
          </button>
        </div>

        {selected.length > 0 && canWrite && (
          <div className="slide-up flex flex-wrap items-center gap-3 border-b border-border bg-navy px-4 py-2 text-sm text-primary-foreground">
            <span className="font-medium tabular">{selected.length} selected</span>
            <button
              type="button"
              onClick={() => ask(selected, 'approve')}
              className="inline-flex items-center gap-1.5 rounded-md bg-teal px-3 py-1 text-xs font-bold text-accent-foreground"
            >
              <Icon name="CheckIcon" size={14} /> Approve selected
            </button>
            <button
              type="button"
              onClick={() => ask(selected, 'reject')}
              className="inline-flex items-center gap-1.5 rounded-md bg-navy-3 px-3 py-1 text-xs font-medium"
            >
              <Icon name="XMarkIcon" size={14} /> Reject selected
            </button>
            <label className="flex items-center gap-2 text-xs">
              <span>Set role</span>
              <select
                aria-label="Role for selected devices"
                value={bulkRole}
                onChange={(event) => setBulkRole(event.target.value)}
                className="h-7 rounded-md border border-navy-3 bg-navy-2 px-2 text-primary-foreground"
              >
                <option value="">Choose a role</option>
                {roleNames(catalog).map((name) => (
                  <option key={name} value={name}>
                    {name}
                  </option>
                ))}
              </select>
              <button
                type="button"
                onClick={() => saveRole(selected, bulkRole)}
                className="rounded-md bg-cyan px-2 py-1 font-semibold text-navy"
              >
                Set role for selected
              </button>
            </label>
            <label className="flex items-center gap-2 text-xs">
              <span>Set site</span>
              <select
                aria-label="Site for selected devices"
                value={bulkSite}
                onChange={(event) => setBulkSite(event.target.value)}
                className="h-7 rounded-md border border-navy-3 bg-navy-2 px-2 text-primary-foreground"
              >
                <option value="">Choose a site</option>
                {siteNames(catalog).map((name) => (
                  <option key={name} value={name}>
                    {name}
                  </option>
                ))}
              </select>
              <button
                type="button"
                onClick={() => saveSite(selected, bulkSite)}
                className="rounded-md bg-cyan px-2 py-1 font-semibold text-navy"
              >
                Set site for selected
              </button>
            </label>
            <label className="flex items-center gap-2 text-xs">
              <span>Tenant group</span>
              <select
                aria-label="Tenant group for selected devices"
                value={bulkGroup}
                onChange={(event) => {
                  setBulkGroup(event.target.value);
                  setBulkTenant('');
                }}
                className="h-7 rounded-md border border-navy-3 bg-navy-2 px-2 text-primary-foreground"
              >
                <option value="">Choose a group</option>
                {tenantGroups(catalog).map((name) => (
                  <option key={name} value={name}>
                    {name}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex items-center gap-2 text-xs">
              <span>Tenant</span>
              <select
                aria-label="Tenant for selected devices"
                value={bulkTenant}
                disabled={!bulkGroup}
                onChange={(event) => setBulkTenant(event.target.value)}
                className="h-7 rounded-md border border-navy-3 bg-navy-2 px-2 text-primary-foreground disabled:opacity-60"
              >
                <option value="">{bulkGroup ? 'Choose a tenant' : 'Choose a group first'}</option>
                {tenantsIn(catalog, bulkGroup).map((name) => (
                  <option key={name} value={name}>
                    {name}
                  </option>
                ))}
              </select>
              <button
                type="button"
                onClick={() => saveTenant(selected, bulkTenant)}
                className="rounded-md bg-cyan px-2 py-1 font-semibold text-navy"
              >
                Set tenant for selected
              </button>
            </label>
            <button
              type="button"
              onClick={() => setSelected([])}
              className="ml-auto text-xs text-down"
            >
              Clear selection
            </button>
          </div>
        )}

        {error ? (
          <div
            role="alert"
            className="m-4 flex items-center justify-between gap-3 rounded-md border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive"
          >
            <span>{error}</span>
            <button
              type="button"
              onClick={load}
              className="rounded-md border border-destructive/40 px-3 py-1 text-xs font-semibold"
            >
              Retry
            </button>
          </div>
        ) : rows === null ? (
          <TableSkeleton rows={8} cols={8} />
        ) : rows.length === 0 ? (
          <EmptyState
            icon="CheckBadgeIcon"
            title={
              items && items.length === 0
                ? 'Nothing waiting for approval'
                : 'No discovered devices match'
            }
            description={
              items && items.length === 0
                ? 'Every device that discovery found is already approved in NetBox. New finds will appear here after the next scan.'
                : 'No discovered device matches your search.'
            }
            actionLabel={items && items.length === 0 ? 'Refresh' : 'Clear search'}
            onAction={() =>
              items && items.length === 0 ? setReload((value) => value + 1) : setSearch('')
            }
          />
        ) : (
          <div className="scroll-thin overflow-x-auto">
            <table className="w-full min-w-[1400px] text-sm">
              <thead>
                <tr className="border-b border-border bg-muted/60 text-left text-xs uppercase tracking-wide text-muted-foreground">
                  <th className="w-10 px-4 py-2.5">
                    <input
                      type="checkbox"
                      aria-label="Select all discovered devices"
                      checked={allOn}
                      onChange={() => setSelected(allOn ? [] : rows.map((row) => row.id))}
                      className="h-4 w-4 accent-[var(--primary)]"
                    />
                  </th>
                  <th className="px-3 py-2.5">sysName</th>
                  <th className="px-3 py-2.5">IP address</th>
                  <th className="px-3 py-2.5">Vendor / model</th>
                  <th className="px-3 py-2.5">Platform</th>
                  <th className="px-3 py-2.5">Suggested site</th>
                  <th className="px-3 py-2.5">Suggested role</th>
                  <th className="px-3 py-2.5">Tenant group</th>
                  <th className="px-3 py-2.5">Tenant</th>
                  <th className="px-3 py-2.5">Last seen</th>
                  <th className="px-3 py-2.5 text-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((device) => {
                  const on = selected.includes(device.id);
                  const fresh = highlightIp === device.ip;
                  const name = labelFor(device);
                  const group = groupPick[device.id] || groupFor(catalog, device.suggested.tenant);
                  return (
                    <tr
                      key={device.id}
                      data-highlight={fresh ? 'new' : undefined}
                      className={`border-b border-border even:bg-muted/20 hover:bg-accent/10 ${on ? 'bg-accent/15' : ''} ${fresh ? 'bg-accent/25 ring-1 ring-inset ring-accent' : ''}`}
                    >
                      <td className="px-4 py-2.5">
                        <input
                          type="checkbox"
                          aria-label={`Select ${name}`}
                          checked={on}
                          onChange={() =>
                            setSelected(
                              on
                                ? selected.filter((id) => id !== device.id)
                                : [...selected, device.id]
                            )
                          }
                          className="h-4 w-4 accent-[var(--primary)]"
                        />
                      </td>
                      <td className="px-3 py-2.5">
                        <span
                          className={`font-mono-data font-semibold ${device.sysName ? '' : 'italic text-muted-foreground'}`}
                        >
                          {name}
                        </span>
                        {device.hostname && device.sysName ? (
                          <span className="mt-0.5 block text-xs text-muted-foreground">
                            {device.hostname}
                          </span>
                        ) : null}
                      </td>
                      <td className="px-3 py-2.5 font-mono-data text-xs">
                        {device.ip}
                        {fresh ? (
                          <Badge tone="success" className="ml-2">
                            New
                          </Badge>
                        ) : null}
                      </td>
                      <td className="px-3 py-2.5 text-muted-foreground">
                        {[device.vendor, device.model].filter(Boolean).join(' ') || '—'}
                      </td>
                      <td className="px-3 py-2.5">
                        {device.platform ? <Badge tone="cyan">{device.platform}</Badge> : '—'}
                      </td>
                      <td className="px-3 py-2.5">
                        <select
                          aria-label={`Suggested site for ${name}`}
                          value={siteValue(catalog, device.suggested.site)}
                          disabled={!canWrite}
                          onChange={(event) => saveSite([device.id], event.target.value)}
                          className="h-8 max-w-[14rem] rounded-md border border-input bg-card px-2 text-sm disabled:opacity-60"
                        >
                          <option value="">Select a site</option>
                          {siteNames(catalog, device.suggested.site).map((option) => (
                            <option key={`${device.id}-site-${option}`} value={option}>
                              {option}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td className="px-3 py-2.5">
                        <select
                          aria-label={`Suggested role for ${name}`}
                          value={roleValue(catalog, device.suggested.role)}
                          disabled={!canWrite}
                          onChange={(event) => saveRole([device.id], event.target.value)}
                          className="h-8 max-w-[14rem] rounded-md border border-input bg-card px-2 text-sm disabled:opacity-60"
                        >
                          <option value="">Select a role</option>
                          {roleNames(catalog, device.suggested.role).map((option) => (
                            <option key={`${device.id}-${option}`} value={option}>
                              {option}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td className="px-3 py-2.5">
                        <select
                          aria-label={`Tenant group for ${name}`}
                          value={group}
                          disabled={!canWrite}
                          onChange={(event) => {
                            const next = event.target.value;
                            setGroupPick((current) => ({ ...current, [device.id]: next }));
                            const kept = tenantsIn(catalog, next).includes(device.suggested.tenant || '');
                            if (device.suggested.tenant && !kept) saveTenant([device.id], '');
                          }}
                          className="h-8 max-w-[14rem] rounded-md border border-input bg-card px-2 text-sm disabled:opacity-60"
                        >
                          <option value="">Select a group</option>
                          {tenantGroups(catalog).map((option) => (
                            <option key={`${device.id}-group-${option}`} value={option}>
                              {option}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td className="px-3 py-2.5">
                        <select
                          aria-label={`Tenant for ${name}`}
                          value={tenantsIn(catalog, group).includes(device.suggested.tenant || '') ? device.suggested.tenant : ''}
                          disabled={!canWrite || !group}
                          onChange={(event) => saveTenant([device.id], event.target.value)}
                          className="h-8 max-w-[14rem] rounded-md border border-input bg-card px-2 text-sm disabled:opacity-60"
                        >
                          <option value="">{group ? 'Select a tenant' : 'Select a group first'}</option>
                          {tenantsIn(catalog, group).map((option) => (
                            <option key={`${device.id}-tenant-${option}`} value={option}>
                              {option}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td className="px-3 py-2.5 font-mono-data text-xs text-muted-foreground">
                        {stamp(device.lastSeen)}
                      </td>
                      <td className="px-3 py-2.5">
                        <div className="flex items-center justify-end gap-1.5">
                          {canWrite ? (
                            <>
                              <button
                                type="button"
                                onClick={() => ask([device.id], 'approve')}
                                className="inline-flex items-center gap-1 rounded-md bg-primary px-2.5 py-1 text-xs font-semibold text-primary-foreground"
                              >
                                <Icon name="CheckIcon" size={13} /> Approve
                              </button>
                              <button
                                type="button"
                                aria-label={`Reject ${name}`}
                                onClick={() => ask([device.id], 'reject')}
                                className="flex h-7 w-7 items-center justify-center rounded-md border border-border text-muted-foreground hover:border-destructive/40 hover:text-destructive"
                              >
                                <Icon name="XMarkIcon" size={14} />
                              </button>
                            </>
                          ) : (
                            <span className="text-xs text-muted-foreground">Read-only</span>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        {view && view.total > 0 ? (
          <Pagination
            page={page}
            pageSize={pageSize}
            total={view.total}
            noun="devices"
            onPage={setPage}
            onPageSize={(size) => {
              setPageSize(size);
              setPage(1);
            }}
          />
        ) : null}
      </section>

      <Modal
        open={!!confirm}
        onClose={() => !busy && setConfirm(null)}
        title={
          confirm?.mode === 'approve'
            ? `Approve ${confirm.ids.length} ${confirm.ids.length === 1 ? 'device' : 'devices'}?`
            : `Reject ${confirm?.ids.length ?? 0}?`
        }
        description={
          confirm?.mode === 'approve'
            ? 'NetBox gets the role, site, tenant, name, and platform you confirm.'
            : 'Rejected devices are hidden until discovery sees them again.'
        }
        width={confirm?.mode === 'approve' && confirm.ids.length === 1 ? 'max-w-lg' : 'max-w-md'}
        footer={
          <>
            <button
              type="button"
              disabled={busy}
              onClick={() => setConfirm(null)}
              className="rounded-md border border-border px-3 py-1.5 text-sm"
            >
              Cancel
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={run}
              className={`rounded-md px-3 py-1.5 text-sm font-semibold ${confirm?.mode === 'reject' ? 'bg-destructive text-destructive-foreground' : 'bg-primary text-primary-foreground'}`}
            >
              {busy
                ? 'Working…'
                : confirm?.mode === 'approve'
                  ? 'Approve in NetBox'
                  : 'Reject devices'}
            </button>
          </>
        }
      >
        {confirm?.mode === 'approve' && confirm.ids.length === 1 ? (
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="text-sm">
              Role
              <select
                aria-label="Role"
                value={roleValue(catalog, form.role)}
                onChange={(event) => setForm({ ...form, role: event.target.value })}
                className="mt-1 h-9 w-full rounded-md border border-input bg-card px-2"
              >
                <option value="">Select a role</option>
                {roleNames(catalog, form.role).map((option) => (
                  <option key={`form-role-${option}`} value={option}>
                    {option}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-sm">
              Tenant group
              <select
                aria-label="Tenant group"
                value={form.tenantGroup}
                onChange={(event) => {
                  const tenantGroup = event.target.value;
                  const kept = tenantsIn(catalog, tenantGroup).includes(form.tenant);
                  setForm({ ...form, tenantGroup, tenant: kept ? form.tenant : '' });
                }}
                className="mt-1 h-9 w-full rounded-md border border-input bg-card px-2"
              >
                <option value="">Select a group</option>
                {tenantGroups(catalog).map((option) => (
                  <option key={`form-group-${option}`} value={option}>
                    {option}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-sm">
              Tenant
              <select
                aria-label="Tenant"
                value={tenantsIn(catalog, form.tenantGroup).includes(form.tenant) ? form.tenant : ''}
                disabled={!form.tenantGroup}
                onChange={(event) => setForm({ ...form, tenant: event.target.value })}
                className="mt-1 h-9 w-full rounded-md border border-input bg-card px-2 disabled:opacity-60"
              >
                <option value="">{form.tenantGroup ? 'Select a tenant' : 'Select a group first'}</option>
                {tenantsIn(catalog, form.tenantGroup).map((option) => (
                  <option key={`form-tenant-${option}`} value={option}>
                    {option}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-sm">
              Site
              <select
                aria-label="Site"
                value={siteValue(catalog, form.site)}
                onChange={(event) => setForm({ ...form, site: event.target.value })}
                className="mt-1 h-9 w-full rounded-md border border-input bg-card px-2"
              >
                <option value="">Select a site</option>
                {siteNames(catalog, form.site).map((option) => (
                  <option key={`form-site-${option}`} value={option}>
                    {option}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-sm">
              Name
              <input
                value={form.name}
                onChange={(event) => setForm({ ...form, name: event.target.value })}
                className="mt-1 h-9 w-full rounded-md border border-input px-2 font-mono-data"
              />
            </label>
            <label className="text-sm">
              Platform
              <input
                list="disc-platforms"
                value={form.platform}
                onChange={(event) => setForm({ ...form, platform: event.target.value })}
                className="mt-1 h-9 w-full rounded-md border border-input px-2"
              />
            </label>
            <datalist id="disc-platforms">
              {catalog.platforms.map((option) => (
                <option key={option} value={option} />
              ))}
            </datalist>
          </div>
        ) : (
          <ul className="max-h-40 space-y-1 overflow-y-auto text-sm">
            {confirm?.ids.map((id) => {
              const device = items?.find((item) => item.id === id);
              return (
                <li key={id} className="font-mono-data">
                  {device ? labelFor(device) : id}
                </li>
              );
            })}
          </ul>
        )}
      </Modal>
    </div>
  );
}
