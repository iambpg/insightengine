'use client';

import React, { useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';
import Icon from '@/components/ui/AppIcon';
import Modal from '@/components/ui/Modal';
import { isApiError } from '@/lib/apiError';
import { isMockMode } from '@/lib/apiMode';
import { request } from '@/lib/http';

type Endpoint = {
  name: string;
  portKey: string;
  port: number;
  scheme: string;
  url: string;
};

type Entry = {
  key: string;
  secret: boolean;
  set: boolean;
  value?: string;
};

type VaultGroup = {
  id: string;
  name: string;
  note: string;
  endpoints: Endpoint[];
  entries: Entry[];
};

type VaultList = {
  readOnly: boolean;
  revealSeconds: number;
  groups: VaultGroup[];
};

type Job = { key: string; action: 'reveal' | 'copy' };

const MASK = '••••••••';

const MOCK: VaultList = {
  readOnly: true,
  revealSeconds: 300,
  groups: [
    {
      id: 'netbox',
      name: 'NetBox',
      note: '',
      endpoints: [
        { name: 'NetBox', portKey: 'PORT_NETBOX', port: 8092, scheme: 'https', url: 'https://monitor.example.com:8092/' },
      ],
      entries: [
        { key: 'NETBOX_SUPERUSER_NAME', secret: false, set: true, value: 'admin' },
        { key: 'NETBOX_SUPERUSER_PASSWORD', secret: true, set: true },
        { key: 'PORT_NETBOX', secret: false, set: true, value: '8092' },
      ],
    },
    {
      id: 'grafana',
      name: 'Grafana',
      note: '',
      endpoints: [
        { name: 'Grafana', portKey: 'PORT_GRAFANA', port: 3000, scheme: 'https', url: 'https://monitor.example.com:3000/' },
      ],
      entries: [
        { key: 'GRAFANA_ADMIN_USER', secret: false, set: true, value: 'admin' },
        { key: 'GRAFANA_ADMIN_PASSWORD', secret: true, set: true },
      ],
    },
    {
      id: 'prometheus-alertmanager',
      name: 'Prometheus / Alertmanager',
      note: 'Basic auth in front of Prometheus and Alertmanager is enforced by Caddy.',
      endpoints: [
        { name: 'Prometheus', portKey: 'PORT_PROMETHEUS', port: 9090, scheme: 'https', url: 'https://monitor.example.com:9090/' },
        { name: 'Alertmanager', portKey: 'PORT_ALERTMANAGER', port: 8086, scheme: 'https', url: 'https://monitor.example.com:8086/' },
      ],
      entries: [
        { key: 'ADMIN_BASIC_USER', secret: false, set: true, value: 'admin' },
        { key: 'ADMIN_BASIC_PASSWORD', secret: true, set: true },
      ],
    },
    {
      id: 'activepieces',
      name: 'Activepieces',
      note: '',
      endpoints: [
        { name: 'Activepieces', portKey: 'PORT_ACTIVEPIECES', port: 8081, scheme: 'https', url: 'https://monitor.example.com:8081/' },
      ],
      entries: [{ key: 'AP_POSTGRES_PASSWORD', secret: true, set: true }],
    },
    {
      id: 'netdisco',
      name: 'Netdisco',
      note: '',
      endpoints: [
        { name: 'Netdisco', portKey: 'PORT_NETDISCO', port: 5000, scheme: 'https', url: 'https://monitor.example.com:5000/' },
      ],
      entries: [{ key: 'NETDISCO_DB_PASSWORD', secret: true, set: true }],
    },
    {
      id: 'oxidized',
      name: 'Oxidized',
      note: '',
      endpoints: [
        { name: 'Oxidized', portKey: 'PORT_OXIDIZED', port: 8888, scheme: 'https', url: 'https://monitor.example.com:8888/' },
      ],
      entries: [{ key: 'PORT_OXIDIZED', secret: false, set: true, value: '8888' }],
    },
    {
      id: 'snmp',
      name: 'SNMP',
      note: '',
      endpoints: [
        { name: 'SNMP exporter', portKey: 'PORT_SNMP_EXPORTER', port: 9116, scheme: 'http', url: 'http://monitor.example.com:9116/' },
      ],
      entries: [
        { key: 'SNMP_V3_USERNAME', secret: false, set: true, value: 'mon-user' },
        { key: 'SNMP_V3_AUTH_PASSWORD', secret: true, set: true },
      ],
    },
    {
      id: 'ui-admin',
      name: 'UI / admin',
      note: '',
      endpoints: [
        { name: 'InsightEngine HTTPS', portKey: 'PORT_HTTPS', port: 57400, scheme: 'https', url: 'https://monitor.example.com:57400/' },
        { name: 'InsightEngine HTTP', portKey: 'PORT_HTTP', port: 18086, scheme: 'http', url: 'http://monitor.example.com:18086/' },
      ],
      entries: [
        { key: 'PORT_HTTP', secret: false, set: true, value: '18086' },
        { key: 'PORT_HTTPS', secret: false, set: true, value: '57400' },
      ],
    },
  ],
};

function shownValue(entry: Entry, revealed: Record<string, string>): string {
  if (!entry.secret) return entry.value ?? '';
  if (!entry.set) return '(not set)';
  return revealed[entry.key] ?? MASK;
}

function endpointLabel(endpoint: Endpoint): string {
  if (endpoint.url) return endpoint.url;
  return `${endpoint.scheme} port ${endpoint.port}`;
}

function keyCountLabel(count: number): string {
  return count === 1 ? '1 key' : `${count} keys`;
}

export default function VaultTab() {
  const [data, setData] = useState<VaultList | null>(isMockMode() ? MOCK : null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState('');
  const [revealed, setRevealed] = useState<Record<string, string>>({});
  const [unlockedUntil, setUnlockedUntil] = useState(0);
  const [pending, setPending] = useState<Job | null>(null);
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [openIds, setOpenIds] = useState<Set<string>>(() => new Set());

  useEffect(() => {
    if (isMockMode()) return;
    let cancelled = false;
    request<VaultList>('/api/v1/settings/vault')
      .then((body) => {
        if (!cancelled) setData(body);
      })
      .catch((cause) => {
        if (cancelled) return;
        setError(isApiError(cause) ? cause.message : 'Vault could not be loaded');
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!unlockedUntil) return;
    const wait = Math.max(0, unlockedUntil - Date.now());
    const timer = window.setTimeout(() => {
      setUnlockedUntil(0);
      setRevealed({});
    }, wait);
    return () => window.clearTimeout(timer);
  }, [unlockedUntil]);

  const groups = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    return (data?.groups ?? [])
      .map((group) => ({
        ...group,
        entries: needle ? group.entries.filter((entry) => entry.key.toLowerCase().includes(needle)) : group.entries,
      }))
      .filter((group) => group.entries.length > 0);
  }, [data, filter]);

  const remaskGroup = (groupId: string) => {
    const keys = new Set(
      (data?.groups ?? []).find((group) => group.id === groupId)?.entries.map((entry) => entry.key) ?? []
    );
    if (keys.size === 0) return;
    setRevealed((prev) => {
      const next = { ...prev };
      let changed = false;
      for (const key of keys) {
        if (key in next) {
          delete next[key];
          changed = true;
        }
      }
      return changed ? next : prev;
    });
  };

  const toggleGroup = (groupId: string) => {
    const closing = openIds.has(groupId);
    setOpenIds((prev) => {
      const next = new Set(prev);
      if (closing) next.delete(groupId);
      else next.add(groupId);
      return next;
    });
    if (closing) remaskGroup(groupId);
  };

  const expandAll = () => {
    setOpenIds(new Set(groups.map((group) => group.id)));
  };

  const collapseAll = () => {
    setOpenIds(new Set());
    setRevealed({});
  };

  const findEntry = (key: string): Entry | undefined => {
    for (const group of data?.groups ?? []) {
      const entry = group.entries.find((item) => item.key === key);
      if (entry) return entry;
    }
    return undefined;
  };

  const sessionOpen = () => Date.now() < unlockedUntil;

  const run = async (job: Job) => {
    const entry = findEntry(job.key);
    if (!entry) return;
    if (isMockMode()) {
      if (job.action === 'copy') {
        const value = entry.secret ? '(mock)' : (entry.value ?? '');
        await navigator.clipboard.writeText(value);
        toast.success('Copied');
        return;
      }
      setRevealed((prev) => ({ ...prev, [job.key]: '(mock)' }));
      return;
    }
    const result = await request<{ key: string; value: string }>(
      '/api/v1/settings/vault/reveal',
      { method: 'POST', body: { key: job.key, action: job.action } }
    );
    if (job.action === 'reveal') {
      setRevealed((prev) => ({ ...prev, [job.key]: result.value }));
      return;
    }
    await navigator.clipboard.writeText(result.value);
    toast.success('Copied');
  };

  const start = async (job: Job) => {
    const entry = findEntry(job.key);
    if (entry?.secret && !sessionOpen()) {
      setPassword('');
      setPending(job);
      return;
    }
    try {
      await run(job);
    } catch (cause) {
      if (isApiError(cause) && cause.code === 'reauth_required') {
        setUnlockedUntil(0);
        setRevealed({});
        setPassword('');
        setPending(job);
        return;
      }
      toast.error(isApiError(cause) ? cause.message : 'The value could not be read');
    }
  };

  const confirm = async (event: React.FormEvent) => {
    event.preventDefault();
    const job = pending;
    const typed = password;
    setPassword('');
    if (!job) return;
    if (!typed) {
      toast.error('Enter the current administrator password');
      return;
    }
    if (isMockMode()) {
      setUnlockedUntil(Date.now() + 5 * 60 * 1000);
      setPending(null);
      await run(job);
      return;
    }
    setBusy(true);
    try {
      const opened = await request<{ expiresIn: number }>('/api/v1/settings/vault/unlock', {
        method: 'POST',
        body: { password: typed },
      });
      setUnlockedUntil(Date.now() + opened.expiresIn * 1000);
      setPending(null);
      await run(job);
    } catch (cause) {
      toast.error(isApiError(cause) ? cause.message : 'Password was not accepted');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-5">
      <div role="note" className="flex items-start gap-3 rounded-lg border border-info/30 bg-info/5 px-4 py-3 text-sm">
        <Icon name="LockClosedIcon" size={18} variant="solid" className="mt-0.5 shrink-0 text-info" />
        <p>
          <span className="font-semibold">Read-only.</span> Every key in this install&apos;s .env. Secret values stay
          masked until you re-enter the current administrator password. A reveal lasts about five minutes. Reveal and
          copy are written to the audit log with the key, never the value.
        </p>
      </div>

      {error ? (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      ) : null}

      <div className="flex flex-wrap items-center justify-between gap-3 px-1">
        <h2 className="text-base font-semibold">Vault</h2>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={expandAll}
            className="rounded-md border border-border bg-card px-2.5 py-1.5 text-xs font-medium hover:bg-muted"
          >
            Expand all
          </button>
          <button
            type="button"
            onClick={collapseAll}
            className="rounded-md border border-border bg-card px-2.5 py-1.5 text-xs font-medium hover:bg-muted"
          >
            Collapse all
          </button>
        </div>
        <label className="flex items-center gap-2 text-sm text-muted-foreground">
          <span className="sr-only">Filter keys</span>
          <input
            aria-label="Filter keys"
            value={filter}
            onChange={(event) => setFilter(event.target.value)}
            placeholder="Filter keys"
            className="h-9 w-56 rounded-md border border-border bg-card px-3 text-sm text-foreground"
          />
        </label>
      </div>

      {!data && !error ? <p className="text-sm text-muted-foreground">Loading vault…</p> : null}

      {groups.map((group) => {
        const open = openIds.has(group.id);
        const panelId = `vault-panel-${group.id}`;
        return (
        <section
          key={group.id}
          aria-labelledby={`vault-${group.id}`}
          className="rounded-none border-x-0 border-y border-border bg-card shadow-card"
        >
          <h3 id={`vault-${group.id}`} className="text-base font-semibold">
            <button
              type="button"
              aria-expanded={open}
              aria-controls={panelId}
              onClick={() => toggleGroup(group.id)}
              className="flex w-full flex-wrap items-center gap-x-3 gap-y-1 px-5 py-3 text-left hover:bg-muted/60"
            >
              <Icon
                name="ChevronDownIcon"
                size={16}
                className={`shrink-0 text-muted-foreground transition-transform ${open ? 'rotate-0' : '-rotate-90'}`}
              />
              <span>{group.name}</span>
              <span className="min-w-0 flex-1 truncate font-mono-data text-xs font-normal text-muted-foreground">
                {group.endpoints.map(endpointLabel).join(' · ') || 'No published URL'}
              </span>
              <span className="font-mono-data text-xs font-normal text-muted-foreground">
                {keyCountLabel(group.entries.length)}
              </span>
            </button>
          </h3>
          {open ? (
          <div id={panelId} role="region" aria-labelledby={`vault-${group.id}`}>
          {group.note ? <p className="border-t border-border px-5 py-2 text-xs text-muted-foreground">{group.note}</p> : null}
          <div className="scroll-thin overflow-x-auto border-t border-border">
            <table className="w-full min-w-[640px] text-sm">
              <thead>
                <tr className="border-b border-border bg-muted/60 text-left">
                  <th scope="col" className="px-5 py-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Key</th>
                  <th scope="col" className="px-3 py-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Value</th>
                  <th scope="col" className="px-5 py-2 text-right text-xs font-semibold uppercase tracking-wide text-muted-foreground">Actions</th>
                </tr>
              </thead>
              <tbody>
                {group.entries.map((entry) => {
                  const value = shownValue(entry, revealed);
                  const open = entry.secret && Boolean(revealed[entry.key]);
                  return (
                    <tr key={entry.key} className="border-b border-border even:bg-muted/20">
                      <th scope="row" className="px-5 py-2 text-left font-mono-data text-xs font-medium">
                        {entry.key}
                      </th>
                      <td className="px-3 py-2 font-mono-data text-xs">
                        <span className={entry.secret && !open ? 'tracking-widest text-muted-foreground' : ''}>{value}</span>
                      </td>
                      <td className="px-5 py-2 text-right">
                        <span className="inline-flex gap-1.5">
                          {entry.secret && !open ? (
                            <button
                              type="button"
                              aria-label={`Reveal ${entry.key}`}
                              onClick={() => start({ key: entry.key, action: 'reveal' })}
                              className="rounded-md border border-border bg-card px-2 py-1 text-xs font-medium hover:bg-muted"
                            >
                              Reveal
                            </button>
                          ) : null}
                          {open ? (
                            <button
                              type="button"
                              aria-label={`Hide ${entry.key}`}
                              onClick={() =>
                                setRevealed((prev) => {
                                  const next = { ...prev };
                                  delete next[entry.key];
                                  return next;
                                })
                              }
                              className="rounded-md border border-border bg-card px-2 py-1 text-xs font-medium hover:bg-muted"
                            >
                              Hide
                            </button>
                          ) : null}
                          <button
                            type="button"
                            aria-label={`Copy ${entry.key}`}
                            onClick={() => start({ key: entry.key, action: 'copy' })}
                            className="rounded-md bg-navy px-2 py-1 text-xs font-semibold text-primary-foreground"
                          >
                            Copy
                          </button>
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          </div>
          ) : null}
        </section>
        );
      })}

      <Modal
        open={pending !== null}
        title="Confirm administrator password"
        description="Re-enter the current administrator password. Reveals stay available for about five minutes."
        onClose={() => {
          setPending(null);
          setPassword('');
        }}
        footer={
          <>
            <button
              type="button"
              onClick={() => {
                setPending(null);
                setPassword('');
              }}
              className="rounded-md border border-border bg-card px-3 py-1.5 text-sm"
            >
              Cancel
            </button>
            <button
              type="submit"
              form="vault-reauth"
              disabled={busy}
              className="rounded-md bg-navy px-3 py-1.5 text-sm font-semibold text-primary-foreground disabled:opacity-50"
            >
              Confirm password
            </button>
          </>
        }
      >
        <form id="vault-reauth" onSubmit={confirm} className="space-y-2">
          <label htmlFor="vault-password" className="text-sm font-medium">
            Current administrator password
          </label>
          <input
            id="vault-password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            className="h-9 w-full rounded-md border border-border bg-card px-3 text-sm"
          />
        </form>
      </Modal>
    </div>
  );
}
