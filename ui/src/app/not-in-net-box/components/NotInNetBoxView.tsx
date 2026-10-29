'use client';

import React, { useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';
import Icon from '@/components/ui/AppIcon';
import Badge from '@/components/ui/Badge';
import EmptyState from '@/components/ui/EmptyState';
import ExampleDataBanner from '@/components/ui/ExampleDataBanner';
import { isMockMode } from '@/lib/apiMode';
import Modal from '@/components/ui/Modal';
import { TableSkeleton } from '@/components/ui/Skeleton';
import { api } from '@/lib/apiClient';
import { reportLoadError } from '@/lib/loadError';
import { isApiError } from '@/lib/apiError';
import type { DiscoveryCatalog, DiscoveryScan, UnapprovedDevice } from '@/lib/contract';

const EMPTY_CATALOG: DiscoveryCatalog = { roles: [], sites: [], platforms: [] };

function stamp(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toISOString().replace('T', ' ').slice(0, 16);
}

export default function NotInNetBoxView() {
  const [items, setItems] = useState<UnapprovedDevice[] | null>(null);
  const [scans, setScans] = useState<DiscoveryScan[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [selected, setSelected] = useState<string[]>([]);
  const [confirm, setConfirm] = useState<{ ids: string[]; mode: 'approve' | 'reject' } | null>(
    null
  );
  const [form, setForm] = useState({ role: '', site: '', name: '', platform: '' });
  const [busy, setBusy] = useState(false);
  const [reload, setReload] = useState(0);
  const [catalog, setCatalog] = useState<DiscoveryCatalog>(EMPTY_CATALOG);
  const [target, setTarget] = useState<'ip' | 'prefix'>('ip');
  const [scanValue, setScanValue] = useState('');
  const [scanning, setScanning] = useState(false);

  const load = () => {
    setItems(null);
    setError(null);
    Promise.all([api.listDiscovered(), api.listScans()])
      .then(([devices, recent]) => {
        setItems(devices);
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
            sites: data.sites ?? [],
            platforms: data.platforms ?? [],
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
    Promise.all([api.listDiscovered(), api.listScans()])
      .then(([devices, recent]) => {
        if (cancelled) return;
        setItems(devices);
        setScans(recent);
      })
      .catch((cause) => {
        if (!cancelled) setError(reportLoadError(cause, 'discovered devices'));
      });
    return () => {
      cancelled = true;
    };
  }, [reload]);

  const rows = useMemo(() => {
    if (!items) return null;
    const needle = search.trim().toLowerCase();
    return items.filter((device) => {
      if (!needle) return true;
      const hay = [
        device.sysName,
        device.hostname,
        device.ip,
        device.vendor,
        device.model,
        device.suggested.site,
        device.suggested.role,
      ]
        .filter(Boolean)
        .join(' ')
        .toLowerCase();
      return hay.includes(needle);
    });
  }, [items, search]);

  const allOn = !!rows && rows.length > 0 && rows.every((row) => selected.includes(row.id));

  const ask = (ids: string[], mode: 'approve' | 'reject') => {
    if (mode === 'approve' && ids.length === 1) {
      const device = items?.find((item) => item.id === ids[0]);
      setForm({
        role: device?.suggested.role ?? '',
        site: device?.suggested.site ?? '',
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
        if (!form.role.trim() || !form.site.trim()) {
          toast.error('Role and site are required to create the device in NetBox.');
          setBusy(false);
          return;
        }
        await api.approveDevice(ids[0], {
          role: form.role.trim(),
          site: form.site.trim(),
          name: form.name.trim() || undefined,
          platform: form.platform.trim() || undefined,
        });
      } else {
        const missing = ids.filter((id) => {
          const device = items?.find((item) => item.id === id);
          return !device?.suggested.role || !device.suggested.site;
        });
        if (missing.length) {
          toast.error(
            'Some selected devices have no suggested role or site. Approve those one at a time.'
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
      const scan = await api.startScan(target, scanValue);
      setScans((current) => [scan, ...(current ?? [])]);
      setScanValue('');
      toast.success(scan.message ?? 'Scan finished.');
      const devices = await api.listDiscovered();
      setItems(devices);
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
          <h1 className="text-2xl font-semibold tracking-tight">Not in NetBox</h1>
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
        <h2 className="text-sm font-semibold">Discover</h2>
        <p className="mt-1 text-xs text-muted-foreground">
          Enter an IP or prefix and press Discover. Scheduled scans still follow NetBox.
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
          <button
            type="submit"
            disabled={scanning || !scanValue.trim()}
            className="inline-flex h-9 items-center gap-1.5 rounded-md bg-navy px-3 text-sm font-semibold text-primary-foreground disabled:opacity-50"
          >
            <Icon name="MagnifyingGlassIcon" size={14} />
            {scanning ? 'Discovering…' : 'Discover'}
          </button>
        </form>
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
              onChange={(event) => setSearch(event.target.value)}
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

        {selected.length > 0 && (
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
            <table className="w-full min-w-[1100px] text-sm">
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
                  <th className="px-3 py-2.5">Last seen</th>
                  <th className="px-3 py-2.5 text-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((device) => {
                  const on = selected.includes(device.id);
                  const name = labelFor(device);
                  return (
                    <tr
                      key={device.id}
                      className={`border-b border-border even:bg-muted/20 hover:bg-accent/10 ${on ? 'bg-accent/15' : ''}`}
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
                      <td className="px-3 py-2.5 font-mono-data text-xs">{device.ip}</td>
                      <td className="px-3 py-2.5 text-muted-foreground">
                        {[device.vendor, device.model].filter(Boolean).join(' ') || '—'}
                      </td>
                      <td className="px-3 py-2.5">
                        {device.platform ? <Badge tone="cyan">{device.platform}</Badge> : '—'}
                      </td>
                      <td className="px-3 py-2.5">{device.suggested.site ?? '—'}</td>
                      <td className="px-3 py-2.5 text-muted-foreground">
                        {device.suggested.role ?? '—'}
                      </td>
                      <td className="px-3 py-2.5 font-mono-data text-xs text-muted-foreground">
                        {stamp(device.lastSeen)}
                      </td>
                      <td className="px-3 py-2.5">
                        <div className="flex items-center justify-end gap-1.5">
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
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
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
            ? 'NetBox gets the role, site, name, and platform you confirm.'
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
              <input
                list="disc-roles"
                value={form.role}
                onChange={(event) => setForm({ ...form, role: event.target.value })}
                className="mt-1 h-9 w-full rounded-md border border-input px-2"
              />
            </label>
            <label className="text-sm">
              Site
              <input
                list="disc-sites"
                value={form.site}
                onChange={(event) => setForm({ ...form, site: event.target.value })}
                className="mt-1 h-9 w-full rounded-md border border-input px-2"
              />
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
            <datalist id="disc-roles">
              {catalog.roles.map((option) => (
                <option key={option} value={option} />
              ))}
            </datalist>
            <datalist id="disc-sites">
              {catalog.sites.map((option) => (
                <option key={option} value={option} />
              ))}
            </datalist>
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
