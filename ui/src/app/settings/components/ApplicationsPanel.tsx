'use client';

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Icon from '@/components/ui/AppIcon';
import Badge from '@/components/ui/Badge';
import { api } from '@/lib/apiClient';
import { isMockMode } from '@/lib/apiMode';
import type {
  AppGroup,
  AuditEntry,
  OverviewApp,
  OverviewResponse,
  SettingsApp,
} from '@/lib/contract';
import { GROUP_LABEL, GROUP_ORDER } from '@/lib/contract';
import type { RoleName } from '@/lib/types';
import { canSeeApplications } from '@/lib/settings/access';
import AppEditor from './AppEditor';

export default function ApplicationsPanel({ role }: { role: RoleName | null }) {
  const [apps, setApps] = useState<SettingsApp[] | null>(null);
  const [overview, setOverview] = useState<OverviewResponse | null>(null);
  const [audit, setAudit] = useState<AuditEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<string>('all');
  const [reloadKey, setReloadKey] = useState(0);
  const dirtyRef = useRef(false);
  const onDirty = useCallback((dirty: boolean) => {
    dirtyRef.current = dirty;
  }, []);

  useEffect(() => {
    if (!canSeeApplications(role)) return undefined;
    let cancelled = false;
    setLoading(true);
    setError(null);
    Promise.all([api.listApps(), api.getOverview(), api.getAudit({ page: 1 })])
      .then(([appRows, overviewRows, auditPage]) => {
        if (cancelled) return;
        setApps(appRows);
        setOverview(overviewRows);
        setAudit(auditPage.entries);
      })
      .catch((cause) => {
        if (!cancelled)
          setError(cause instanceof Error ? cause.message : 'Could not load application settings.');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [role, reloadKey]);

  const overviewById = useMemo(() => {
    const map = new Map<string, OverviewApp>();
    overview?.apps.forEach((item) => map.set(item.id, item));
    return map;
  }, [overview]);

  if (!canSeeApplications(role)) {
    return (
      <section className="rounded-md border border-border bg-card px-5 py-8 text-sm">
        <h2 className="text-base font-semibold">Applications</h2>
        <p className="mt-2 text-muted-foreground">
          Settings for Prometheus, Alertmanager, SNMP, and the rest of the stack are limited to
          Engineers and Administrators.
          {role
            ? ` You are signed in as ${role}.`
            : ' Sign in with an Engineer or Administrator account.'}
        </p>
      </section>
    );
  }

  const open = (id: string) => {
    if (id === selected) return;
    if (dirtyRef.current && !window.confirm('You have unsaved changes. Leave this file anyway?'))
      return;
    dirtyRef.current = false;
    setSelected(id);
  };

  const selectedApp = apps?.find((item) => item.id === selected);

  return (
    <div className="grid grid-cols-1 gap-4 xl:grid-cols-[240px_1fr]">
      <nav aria-label="Applications" className="space-y-3">
        <button
          type="button"
          onClick={() => open('all')}
          className={`flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm ${selected === 'all' ? 'bg-navy font-semibold text-primary-foreground' : 'hover:bg-muted'}`}
        >
          <Icon name="Squares2X2Icon" size={16} />
          All applications
        </button>
        {GROUP_ORDER.map((group) => {
          const rows = (apps ?? []).filter((item) => item.group === group);
          if (rows.length === 0 && loading) return null;
          if (rows.length === 0) return null;
          return (
            <div key={group}>
              <p className="label-caps mb-1 px-2 text-[10px] text-muted-foreground">
                {GROUP_LABEL[group]}
              </p>
              <ul className="space-y-0.5">
                {rows.map((item) => {
                  const state = overviewById.get(item.id)?.container.state ?? item.container.state;
                  const on = selected === item.id;
                  return (
                    <li key={item.id}>
                      <button
                        type="button"
                        onClick={() => open(item.id)}
                        className={`flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm ${on ? 'bg-navy font-semibold text-primary-foreground' : 'hover:bg-muted'}`}
                      >
                        <Dot state={state} />
                        <span className="flex-1 truncate">{item.name}</span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            </div>
          );
        })}
      </nav>

      <div className="min-w-0">
        {isMockMode() ? (
          <p className="mb-3 rounded-md border border-warning/40 bg-warning/10 px-3 py-1.5 text-xs">
            Example data — mock configuration, no live containers are connected.
          </p>
        ) : null}
        {error ? (
          <div
            role="alert"
            className="flex items-center justify-between gap-3 rounded-md border border-destructive/30 bg-destructive/10 px-3 py-3 text-sm text-destructive"
          >
            <span>{error}</span>
            <button
              type="button"
              className="rounded-md border border-destructive/40 px-2 py-1 text-xs"
              onClick={() => setReloadKey((value) => value + 1)}
            >
              Retry
            </button>
          </div>
        ) : null}
        {loading && !apps ? <p role="status">Loading applications…</p> : null}
        {!loading && selected === 'all' && apps ? (
          <Landing apps={apps} overviewById={overviewById} audit={audit} onOpen={open} />
        ) : null}
        {selectedApp ? (
          <AppEditor
            app={selectedApp}
            overview={overviewById.get(selectedApp.id)}
            role={role}
            onOpenApp={open}
            onDirty={onDirty}
          />
        ) : null}
      </div>
    </div>
  );
}

function Landing({
  apps,
  overviewById,
  audit,
  onOpen,
}: {
  apps: SettingsApp[];
  overviewById: Map<string, OverviewApp>;
  audit: AuditEntry[] | null;
  onOpen: (id: string) => void;
}) {
  return (
    <div className="space-y-6">
      <header>
        <h2 className="text-xl font-semibold tracking-tight">Applications</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Every service in the stack. Open one to edit its files, validate, and reload.
        </p>
      </header>
      {GROUP_ORDER.map((group) => (
        <Group
          key={group}
          group={group}
          apps={apps.filter((item) => item.group === group)}
          overviewById={overviewById}
          onOpen={onOpen}
        />
      ))}
      <section aria-label="Recent configuration changes">
        <h3 className="text-base font-semibold">Recent changes</h3>
        {audit === null ? (
          <p className="mt-2 text-sm text-muted-foreground">Audit log unavailable.</p>
        ) : null}
        {audit && audit.length === 0 ? (
          <p className="mt-2 text-sm text-muted-foreground">
            No configuration changes recorded yet.
          </p>
        ) : null}
        {audit && audit.length > 0 ? (
          <div className="scroll-thin mt-2 overflow-x-auto rounded-md border border-border">
            <table className="w-full min-w-[720px] text-sm">
              <thead>
                <tr className="border-b border-border bg-muted/60 text-left text-xs uppercase tracking-wide text-muted-foreground">
                  <th className="px-3 py-2">When</th>
                  <th className="px-3 py-2">User</th>
                  <th className="px-3 py-2">App</th>
                  <th className="px-3 py-2">File</th>
                  <th className="px-3 py-2">Action</th>
                  <th className="px-3 py-2">Comment</th>
                  <th className="px-3 py-2">Result</th>
                </tr>
              </thead>
              <tbody>
                {audit.map((entry) => (
                  <tr key={entry.id} className="border-b border-border last:border-0">
                    <td className="px-3 py-2 font-mono-data text-xs">
                      {entry.at.replace('T', ' ').slice(0, 16)}
                    </td>
                    <td className="px-3 py-2">{entry.user}</td>
                    <td className="px-3 py-2">{entry.app}</td>
                    <td className="px-3 py-2 font-mono-data text-xs">{entry.file ?? '—'}</td>
                    <td className="px-3 py-2">{entry.action}</td>
                    <td className="px-3 py-2">{entry.comment ?? '—'}</td>
                    <td className="px-3 py-2">{entry.result}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </section>
    </div>
  );
}

function Group({
  group,
  apps,
  overviewById,
  onOpen,
}: {
  group: AppGroup;
  apps: SettingsApp[];
  overviewById: Map<string, OverviewApp>;
  onOpen: (id: string) => void;
}) {
  if (apps.length === 0) return null;
  return (
    <section aria-label={GROUP_LABEL[group]}>
      <h3 className="label-caps text-muted-foreground">{GROUP_LABEL[group]}</h3>
      <div className="mt-2 grid gap-3 md:grid-cols-2">
        {apps.map((item) => {
          const extra = overviewById.get(item.id);
          const state = extra?.container.state ?? item.container.state;
          return (
            <button
              key={item.id}
              type="button"
              onClick={() => onOpen(item.id)}
              className="rounded-md border border-border bg-card p-4 text-left shadow-card transition-colors hover:border-ring"
            >
              <div className="flex items-start justify-between gap-2">
                <span className="font-semibold">{item.name}</span>
                <StateBadge state={state} />
              </div>
              <p className="mt-1 line-clamp-2 text-sm text-muted-foreground">{item.description}</p>
              <p className="mt-2 font-mono-data text-[11px] text-muted-foreground">
                {item.container.name}
                {item.version ? ` · ${item.version}` : ''}
              </p>
              <p className="mt-1 text-xs text-muted-foreground">
                Last reload{' '}
                {extra?.lastReloadAt
                  ? extra.lastReloadAt.replace('T', ' ').slice(0, 16) + ' UTC'
                  : '—'}
              </p>
              {extra?.lastError ? (
                <p className="mt-1 text-xs text-destructive">{extra.lastError}</p>
              ) : null}
            </button>
          );
        })}
      </div>
    </section>
  );
}

function StateBadge({ state }: { state: string }) {
  const tone =
    state === 'running'
      ? 'success'
      : state === 'unhealthy'
        ? 'destructive'
        : state === 'exited'
          ? 'warning'
          : 'neutral';
  return <Badge tone={tone}>{state}</Badge>;
}

function Dot({ state }: { state: string }) {
  const color =
    state === 'running'
      ? 'bg-success'
      : state === 'unhealthy'
        ? 'bg-destructive'
        : state === 'exited'
          ? 'bg-warning'
          : 'bg-muted-foreground';
  return <span className={`h-2 w-2 shrink-0 rounded-full ${color}`} aria-hidden="true" />;
}
