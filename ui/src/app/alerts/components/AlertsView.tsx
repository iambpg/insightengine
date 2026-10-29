'use client';

import React, { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { toast } from 'sonner';
import Icon from '@/components/ui/AppIcon';
import Badge from '@/components/ui/Badge';
import EmptyState from '@/components/ui/EmptyState';
import ExampleDataBanner from '@/components/ui/ExampleDataBanner';
import Pagination from '@/components/ui/Pagination';
import { TableSkeleton } from '@/components/ui/Skeleton';
import { api } from '@/lib/apiClient';
import { reportLoadError } from '@/lib/loadError';
import { devicePath, isMockMode } from '@/lib/apiMode';
import { readSession } from '@/lib/session';
import type { AlertItem, AlertSeverity } from '@/lib/types';

type SevFilter = AlertSeverity | 'all';
type StatusFilter = 'open' | 'acknowledged' | 'all';
type GroupBy = 'none' | 'severity' | 'site';

const SEV_META: Record<AlertSeverity, { label: string; tone: 'destructive' | 'warning' | 'info'; icon: string; rank: number }> = {
  critical: { label: 'Critical', tone: 'destructive', icon: 'XCircleIcon', rank: 0 },
  warning: { label: 'Warning', tone: 'warning', icon: 'ExclamationTriangleIcon', rank: 1 },
  info: { label: 'Info', tone: 'info', icon: 'InformationCircleIcon', rank: 2 },
};

function formatAge(min: number): string {
  if (min < 60) return `${min}m`;
  const h = Math.floor(min / 60);
  if (h < 24) return `${h}h ${min % 60}m`;
  return `${Math.floor(h / 24)}d ${h % 24}h`;
}

interface Group {
  key: string;
  label: string;
  items: AlertItem[];
}

export default function AlertsView() {
  const [alerts, setAlerts] = useState<AlertItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  const [search, setSearch] = useState('');
  const [severity, setSeverity] = useState<SevFilter>('all');
  const [status, setStatus] = useState<StatusFilter>('open');
  const [site, setSite] = useState('all');
  const [groupBy, setGroupBy] = useState<GroupBy>('severity');
  const [selected, setSelected] = useState<string[]>([]);
  const [collapsed, setCollapsed] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);

  useEffect(() => {
    let cancelled = false;
    setAlerts(null);
    setError(null);
    api
      .listAlerts()
      .then((d) => !cancelled && setAlerts(d))
      .catch((cause) => !cancelled && setError(reportLoadError(cause, 'alerts')));
    return () => {
      cancelled = true;
    };
  }, [reload]);

  const sites = useMemo(() => Array.from(new Set((alerts ?? []).map((a) => a.site))).sort(), [alerts]);

  const counts = useMemo(() => {
    const open = (alerts ?? []).filter((a) => a.status === 'open');
    return {
      critical: open.filter((a) => a.severity === 'critical').length,
      warning: open.filter((a) => a.severity === 'warning').length,
      info: open.filter((a) => a.severity === 'info').length,
      acknowledged: (alerts ?? []).filter((a) => a.status === 'acknowledged').length,
    };
  }, [alerts]);

  const filtered = useMemo(() => {
    if (!alerts) return null;
    const s = search.trim().toLowerCase();
    return alerts
      .filter(
        (a) =>
          (severity === 'all' || a.severity === severity) &&
          (status === 'all' || a.status === status) &&
          (site === 'all' || a.site === site) &&
          (!s || a.title.toLowerCase().includes(s) || a.deviceHostname.toLowerCase().includes(s) || a.site.toLowerCase().includes(s) || a.category.toLowerCase().includes(s))
      )
      .sort((a, b) => SEV_META[a.severity].rank - SEV_META[b.severity].rank || a.ageMinutes - b.ageMinutes);
  }, [alerts, search, severity, status, site]);

  useEffect(() => {
    setPage(1);
  }, [search, severity, status, site, groupBy, pageSize]);

  const pageRows = useMemo(() => {
    if (!filtered) return null;
    return filtered.slice((page - 1) * pageSize, page * pageSize);
  }, [filtered, page, pageSize]);

  const groups: Group[] = useMemo(() => {
    if (!pageRows) return [];
    if (groupBy === 'none') return [{ key: 'all', label: 'All alerts', items: pageRows }];
    const map = new Map<string, AlertItem[]>();
    pageRows.forEach((a) => {
      const k = groupBy === 'severity' ? a.severity : a.site;
      map.set(k, [...(map.get(k) ?? []), a]);
    });
    const entries = Array.from(map.entries());
    if (groupBy === 'severity') {
      entries.sort((x, y) => SEV_META[x[0] as AlertSeverity].rank - SEV_META[y[0] as AlertSeverity].rank);
      return entries.map(([k, items]) => ({ key: k, label: SEV_META[k as AlertSeverity].label, items }));
    }
    entries.sort((x, y) => y[1].filter((a) => a.severity === 'critical').length - x[1].filter((a) => a.severity === 'critical').length || y[1].length - x[1].length);
    return entries.map(([k, items]) => ({ key: k, label: k, items }));
  }, [pageRows, groupBy]);

  const openIdsOnPage = (pageRows ?? []).filter((a) => a.status === 'open').map((a) => a.id);
  const allOn = openIdsOnPage.length > 0 && openIdsOnPage.every((id) => selected.includes(id));
  const filtersActive = search.trim() !== '' || severity !== 'all' || status !== 'open' || site !== 'all';

  const acknowledge = async (ids: string[]) => {
    if (ids.length === 0) return;
    setBusy(true);
    try {
      await api.acknowledgeAlerts(ids);
      const at = isMockMode()
        ? '2026-10-27 17:25'
        : new Date().toISOString().replace('T', ' ').slice(0, 16) + ' UTC';
      const by = isMockMode() ? 'Marit van der Berg' : readSession()?.email || 'you';
      setAlerts((cur) => cur?.map((a) => (ids.includes(a.id) ? { ...a, status: 'acknowledged', acknowledgedBy: by, acknowledgedAt: at } : a)) ?? cur);
      setSelected((s) => s.filter((x) => !ids.includes(x)));
      toast.success(`${ids.length} ${ids.length === 1 ? 'alert' : 'alerts'} acknowledged`);
    } catch {
      toast.error('The request failed. No alerts were changed.');
    } finally {
      setBusy(false);
    }
  };

  const toggleGroup = (key: string) => setCollapsed((c) => (c.includes(key) ? c.filter((k) => k !== key) : [...c, key]));
  const clearFilters = () => {
    setSearch('');
    setSeverity('all');
    setStatus('open');
    setSite('all');
  };

  const summaryCards: { key: AlertSeverity; count: number }[] = [
    { key: 'critical', count: counts.critical },
    { key: 'warning', count: counts.warning },
    { key: 'info', count: counts.info },
  ];

  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-end justify-between gap-3 px-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Alerts</h1>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
            Triage active alerts across the network. Filter by severity, site or status, group them, and acknowledge what your team is handling.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setReload((n) => n + 1)}
          className="inline-flex h-9 items-center gap-1.5 rounded-md border border-border bg-card px-3 text-sm font-medium transition-all hover:bg-muted active:scale-95"
        >
          <Icon name="ArrowPathIcon" size={14} /> Refresh
        </button>
      </header>

      {isMockMode() ? <ExampleDataBanner /> : null}

      <section className="grid grid-cols-1 gap-3 px-4 sm:grid-cols-2 lg:grid-cols-4" aria-label="Alert summary">
        {summaryCards.map((c) => {
          const m = SEV_META[c.key];
          const on = severity === c.key;
          return (
            <button
              key={`sum-${c.key}`}
              type="button"
              onClick={() => setSeverity(on ? 'all' : c.key)}
              aria-pressed={on}
              className={`flex items-center gap-3 rounded-lg border bg-card p-4 text-left shadow-card transition-all hover:bg-muted/50 active:scale-[0.99] ${on ? 'border-primary ring-1 ring-primary' : 'border-border'}`}
            >
              <span className={`flex h-10 w-10 items-center justify-center rounded-full ${c.key === 'critical' ? 'bg-destructive/10 text-destructive' : c.key === 'warning' ? 'bg-warning/15 text-warning' : 'bg-info/10 text-info'}`}>
                <Icon name={m.icon} size={22} variant="solid" />
              </span>
              <span>
                <span className="block text-2xl font-semibold tabular leading-none">{alerts ? c.count : '—'}</span>
                <span className="mt-1 block text-xs text-muted-foreground">Open {m.label.toLowerCase()}</span>
              </span>
            </button>
          );
        })}
        <button
          type="button"
          onClick={() => setStatus(status === 'acknowledged' ? 'open' : 'acknowledged')}
          aria-pressed={status === 'acknowledged'}
          className={`flex items-center gap-3 rounded-lg border bg-card p-4 text-left shadow-card transition-all hover:bg-muted/50 active:scale-[0.99] ${status === 'acknowledged' ? 'border-primary ring-1 ring-primary' : 'border-border'}`}
        >
          <span className="flex h-10 w-10 items-center justify-center rounded-full bg-success/10 text-success">
            <Icon name="CheckBadgeIcon" size={22} variant="solid" />
          </span>
          <span>
            <span className="block text-2xl font-semibold tabular leading-none">{alerts ? counts.acknowledged : '—'}</span>
            <span className="mt-1 block text-xs text-muted-foreground">Acknowledged</span>
          </span>
        </button>
      </section>

      <section className="rounded-none border-x-0 border-y border-border bg-card shadow-card" aria-label="Alert triage">
        <div className="flex flex-wrap items-center gap-2 border-b border-border p-4">
          <label className="relative min-w-[220px] flex-1 sm:max-w-sm">
            <span className="sr-only">Search alerts</span>
            <Icon name="MagnifyingGlassIcon" size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
            <input
              type="search"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Alert, device, site or category…"
              className="h-9 w-full rounded-md border border-input bg-background pl-9 pr-3 text-sm outline-none focus:border-ring"
            />
          </label>
          <label className="flex items-center gap-1.5 text-sm">
            <span className="text-muted-foreground">Severity</span>
            <select value={severity} onChange={(e) => setSeverity(e.target.value as SevFilter)} className="h-9 rounded-md border border-input bg-card px-2 text-sm">
              <option value="all">All</option>
              <option value="critical">Critical</option>
              <option value="warning">Warning</option>
              <option value="info">Info</option>
            </select>
          </label>
          <label className="flex items-center gap-1.5 text-sm">
            <span className="text-muted-foreground">Status</span>
            <select value={status} onChange={(e) => setStatus(e.target.value as StatusFilter)} className="h-9 rounded-md border border-input bg-card px-2 text-sm">
              <option value="open">Open</option>
              <option value="acknowledged">Acknowledged</option>
              <option value="all">All</option>
            </select>
          </label>
          <label className="flex items-center gap-1.5 text-sm">
            <span className="text-muted-foreground">Site</span>
            <select value={site} onChange={(e) => setSite(e.target.value)} className="h-9 max-w-[200px] rounded-md border border-input bg-card px-2 text-sm">
              <option value="all">All sites</option>
              {sites.map((s) => (
                <option key={`site-opt-${s}`} value={s}>{s}</option>
              ))}
            </select>
          </label>
          <div className="ml-auto flex items-center gap-1.5 text-sm">
            <span className="text-muted-foreground">Group by</span>
            <div role="group" aria-label="Group alerts by" className="inline-flex overflow-hidden rounded-md border border-border">
              {(['severity', 'site', 'none'] as GroupBy[]).map((g) => (
                <button
                  key={`grp-${g}`}
                  type="button"
                  onClick={() => setGroupBy(g)}
                  aria-pressed={groupBy === g}
                  className={`h-9 px-3 text-sm transition-colors ${groupBy === g ? 'bg-navy font-semibold text-primary-foreground' : 'bg-card text-muted-foreground hover:bg-muted'}`}
                >
                  {g === 'none' ? 'None' : g === 'severity' ? 'Severity' : 'Site'}
                </button>
              ))}
            </div>
          </div>
        </div>

        {selected.length > 0 && (
          <div className="slide-up flex flex-wrap items-center gap-3 border-b border-border bg-navy px-4 py-2 text-sm text-primary-foreground">
            <span className="font-medium tabular">{selected.length} selected</span>
            <button
              type="button"
              disabled={busy}
              onClick={() => acknowledge(selected)}
              className="inline-flex items-center gap-1.5 rounded-md bg-teal px-3 py-1 text-xs font-bold text-accent-foreground transition-all hover:opacity-90 active:scale-95 disabled:opacity-60"
            >
              {busy ? <Icon name="ArrowPathIcon" size={14} className="animate-spin" /> : <Icon name="CheckIcon" size={14} />} Acknowledge selected
            </button>
            <button type="button" onClick={() => setSelected([])} className="ml-auto text-xs text-down hover:text-primary-foreground">Clear selection</button>
          </div>
        )}

        {error ? (
          <div role="alert" className="m-4 flex items-center justify-between gap-3 rounded-md border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
            <span>{error}</span>
            <button type="button" onClick={() => setReload((n) => n + 1)} className="rounded-md border border-destructive/40 px-3 py-1 text-xs font-semibold">Retry</button>
          </div>
        ) : filtered === null ? (
          <TableSkeleton rows={8} cols={7} />
        ) : filtered.length === 0 ? (
          <EmptyState
            icon="BellSlashIcon"
            title={filtersActive ? 'No alerts match your filters' : 'No open alerts'}
            description={filtersActive ? 'Try widening the severity, status or site filter.' : 'Everything is quiet. New alerts will appear here as soon as they are raised.'}
            actionLabel={filtersActive ? 'Clear filters' : 'Refresh'}
            onAction={() => (filtersActive ? clearFilters() : setReload((n) => n + 1))}
          />
        ) : (
          <div className="scroll-thin overflow-x-auto">
            <table className="w-full min-w-[980px] text-sm">
              <thead>
                <tr className="border-b border-border bg-muted/60 text-left text-xs uppercase tracking-wide text-muted-foreground">
                  <th scope="col" className="w-10 px-4 py-2.5">
                    <input
                      type="checkbox"
                      aria-label="Select all open alerts on this page"
                      checked={allOn}
                      disabled={openIdsOnPage.length === 0}
                      onChange={() => setSelected(allOn ? selected.filter((id) => !openIdsOnPage.includes(id)) : Array.from(new Set([...selected, ...openIdsOnPage])))}
                      className="h-4 w-4 accent-[var(--primary)]"
                    />
                  </th>
                  <th scope="col" className="px-3 py-2.5">Severity</th>
                  <th scope="col" className="px-3 py-2.5">Alert</th>
                  <th scope="col" className="px-3 py-2.5">Device</th>
                  <th scope="col" className="px-3 py-2.5">Site</th>
                  <th scope="col" className="px-3 py-2.5">Category</th>
                  <th scope="col" className="px-3 py-2.5 text-right">Age</th>
                  <th scope="col" className="px-3 py-2.5 text-right">Action</th>
                </tr>
              </thead>
              {groups.map((g) => {
                const isClosed = collapsed.includes(g.key) && groupBy !== 'none';
                const crit = g.items.filter((a) => a.severity === 'critical').length;
                return (
                  <tbody key={`group-${g.key}`}>
                    {groupBy !== 'none' && (
                      <tr className="border-b border-border bg-muted/40">
                        <td colSpan={8} className="px-4 py-2">
                          <button
                            type="button"
                            onClick={() => toggleGroup(g.key)}
                            aria-expanded={!isClosed}
                            className="flex w-full items-center gap-2 text-left text-sm font-semibold"
                          >
                            <Icon name={isClosed ? 'ChevronRightIcon' : 'ChevronDownIcon'} size={14} className="text-muted-foreground" />
                            {groupBy === 'severity' ? (
                              <Badge tone={SEV_META[g.key as AlertSeverity].tone} icon={SEV_META[g.key as AlertSeverity].icon}>{g.label}</Badge>
                            ) : (
                              <>
                                <Icon name="BuildingOffice2Icon" size={15} className="text-muted-foreground" />
                                <span>{g.label}</span>
                              </>
                            )}
                            <span className="font-normal text-muted-foreground tabular">
                              {g.items.length} {g.items.length === 1 ? 'alert' : 'alerts'}
                            </span>
                            {groupBy === 'site' && crit > 0 && <Badge tone="destructive" icon="XCircleIcon">{crit} critical</Badge>}
                          </button>
                        </td>
                      </tr>
                    )}
                    {!isClosed &&
                      g.items.map((a) => {
                        const m = SEV_META[a.severity];
                        const acked = a.status === 'acknowledged';
                        const on = selected.includes(a.id);
                        return (
                          <tr key={a.id} className={`border-b border-border transition-colors even:bg-muted/20 hover:bg-accent/10 ${on ? 'bg-accent/15' : ''} ${acked ? 'opacity-70' : ''}`}>
                            <td className="px-4 py-2.5">
                              <input
                                type="checkbox"
                                aria-label={`Select alert ${a.title} on ${a.deviceHostname}`}
                                checked={on}
                                disabled={acked}
                                onChange={() => setSelected(on ? selected.filter((s) => s !== a.id) : [...selected, a.id])}
                                className="h-4 w-4 accent-[var(--primary)]"
                              />
                            </td>
                            <td className="px-3 py-2.5"><Badge tone={m.tone} icon={m.icon}>{m.label}</Badge></td>
                            <td className="max-w-[360px] px-3 py-2.5">
                              <p className="font-medium">{a.title}</p>
                              <p className="truncate text-xs text-muted-foreground" title={a.detail}>{a.detail}</p>
                            </td>
                            <td className="px-3 py-2.5">
                              <Link href={devicePath(a.deviceHostname, a.formFactor)} className="font-mono-data text-xs font-semibold hover:text-primary hover:underline">
                                {a.deviceHostname}
                              </Link>
                            </td>
                            <td className="max-w-[200px] truncate px-3 py-2.5 text-muted-foreground" title={a.site}>{a.site}</td>
                            <td className="px-3 py-2.5"><Badge tone="neutral">{a.category}</Badge></td>
                            <td className="px-3 py-2.5 text-right">
                              <span className="font-mono-data text-xs tabular" title={`Raised ${a.raisedAt}`}>{formatAge(a.ageMinutes)}</span>
                            </td>
                            <td className="px-3 py-2.5">
                              <div className="flex items-center justify-end">
                                {acked ? (
                                  <span className="inline-flex items-center gap-1 text-xs text-muted-foreground" title={`Acknowledged by ${a.acknowledgedBy} at ${a.acknowledgedAt}`}>
                                    <Icon name="CheckCircleIcon" size={14} variant="solid" className="text-success" /> Acknowledged
                                  </span>
                                ) : (
                                  <button
                                    type="button"
                                    disabled={busy}
                                    onClick={() => acknowledge([a.id])}
                                    className="inline-flex items-center gap-1 rounded-md border border-border bg-card px-2.5 py-1 text-xs font-semibold transition-all hover:bg-muted active:scale-95 disabled:opacity-50"
                                  >
                                    <Icon name="CheckIcon" size={13} /> Acknowledge
                                  </button>
                                )}
                              </div>
                            </td>
                          </tr>
                        );
                      })}
                  </tbody>
                );
              })}
            </table>
          </div>
        )}

        {filtered && filtered.length > 0 && (
          <Pagination page={page} pageSize={pageSize} total={filtered.length} onPage={setPage} onPageSize={setPageSize} sizes={[10, 25, 50]} noun="alerts" />
        )}
      </section>
    </div>
  );
}
