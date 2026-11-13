'use client';

import React, { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { api } from '@/lib/apiClient';
import { isApiError } from '@/lib/apiError';
import UsageGauge from '@/components/ui/UsageGauge';

type Service = { name: string; running?: boolean };

type Member = {
  hostname: string;
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
};

type Health = {
  configured?: boolean;
  ok?: boolean;
  message?: string;
  grid?: string;
  version?: string;
  members?: Member[];
};

export default function InfobloxDashboard() {
  const [data, setData] = useState<Health | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    setLoading(true);
    setError('');
    api
      .netbridgeGet('/infoblox/health')
      .then((body) => setData(body as Health))
      .catch((cause) => setError(isApiError(cause) ? cause.message : 'Infoblox could not be loaded.'))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const members = data?.members ?? [];
  const grid = members.filter((member) => member.group === 'grid');
  const others = members.filter((member) => member.group !== 'grid');
  const healthy = members.filter((member) => member.healthy).length;

  if (!loading && data && data.configured === false) {
    return (
      <div className="px-4">
        <h1 className="text-2xl font-semibold tracking-tight">Infoblox</h1>
        <p className="mt-3 max-w-2xl rounded-md border border-border bg-card px-4 py-3 text-sm">
          {data.message || 'Add the Infoblox URL, username, and password in Settings → Vault.'}{' '}
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
          <h1 className="text-2xl font-semibold tracking-tight">Infoblox</h1>
          <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
            Grid members from the API, with CPU, memory, disk, and process health from SNMP. Click a member for the full reading.
          </p>
        </div>
        <button type="button" onClick={load} className="rounded-md border border-border bg-card px-3 py-1.5 text-sm">
          Refresh
        </button>
      </header>

      {error ? <p role="alert" className="rounded-md border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">{error}</p> : null}
      {data?.message ? <p className="rounded-md border border-warning/40 bg-warning/10 px-4 py-3 text-sm">{data.message}</p> : null}

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Stat label="Grid" value={loading ? '…' : data?.grid || '—'} note="Name reported by the Grid Master" />
        <Stat label="WAPI" value={loading ? '…' : data?.version || '—'} note="API version that answered" />
        <Stat label="Members healthy" value={loading ? '…' : members.length ? `${healthy} of ${members.length}` : '—'} note="No failed services" />
        <Stat label="Members" value={loading ? '…' : members.length || '—'} note="Grid Master and members" />
      </div>

      <MemberGroup title="Grid Master" note="The member that answered the API." members={grid} loading={loading} />
      <MemberGroup title="Members" note="The other appliances in the grid." members={others} loading={loading} />
    </div>
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

function MemberGroup({ title, note, members, loading }: { title: string; note: string; members: Member[]; loading: boolean }) {
  return (
    <section aria-label={title} className="space-y-3">
      <div>
        <h2 className="text-base font-semibold">{title}</h2>
        <p className="text-sm text-muted-foreground">{note}</p>
      </div>
      {loading ? <p className="text-sm text-muted-foreground">Loading members…</p> : null}
      {!loading && members.length === 0 ? <p className="text-sm text-muted-foreground">No members in this group.</p> : null}
      <div className="grid gap-3 md:grid-cols-2">
        {members.map((member) => (
          <Link
            key={member.hostname}
            href={`/infoblox/${encodeURIComponent(member.hostname)}`}
            aria-label={`Open ${member.hostname}`}
            className="block rounded-md border border-border bg-card p-4 shadow-card transition-colors hover:border-primary"
          >
            <div className="min-h-[8.4rem]">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <h3 className="text-base font-semibold">{member.hostname}</h3>
                  <p className="font-mono-data text-xs text-muted-foreground">{member.ip || 'No address'}</p>
                </div>
                <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-semibold ${member.healthy ? 'bg-success/10 text-success' : 'bg-warning/15 text-foreground'}`}>
                  <span className={`h-2 w-2 rounded-full ${member.healthy ? 'bg-success' : 'bg-warning'}`} />
                  {member.healthy ? 'Healthy' : member.status || 'Unknown'}
                </span>
              </div>
              <ul className="mt-3 flex flex-wrap gap-1.5">
                {(member.roles || []).map((role) => (
                  <li key={role} className="rounded-md bg-muted px-2 py-0.5 text-xs">{role}</li>
                ))}
              </ul>
            </div>
            <div className="mt-3 grid grid-cols-4 gap-2">
              <UsageGauge label="CPU" value={member.cpu} />
              <UsageGauge label="Memory" value={member.memory} />
              <UsageGauge label="Disk /" value={member.diskRoot} />
              <UsageGauge label="Disk /opt" value={member.diskOpt} />
            </div>
            <div className="mt-3">
              <p className="text-xs uppercase tracking-wide text-muted-foreground">API services</p>
              {(member.services || []).length === 0 ? (
                <p className="mt-1 text-sm text-muted-foreground">No service status</p>
              ) : (
                <ul className="mt-1 flex flex-wrap gap-1.5">
                  {(member.services || []).map((service) => (
                    <li key={service.name} className={`rounded-md px-2 py-0.5 text-xs font-medium ${service.running === false ? 'bg-warning/15 text-foreground' : 'bg-success/10 text-success'}`}>
                      {service.name}
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <div className="mt-3">
              <p className="text-xs uppercase tracking-wide text-muted-foreground">Issues</p>
              {(member.issues || []).length === 0 ? (
                <p className="mt-1 text-sm text-muted-foreground">No issues</p>
              ) : (
                <ul className="mt-1 space-y-1">
                  {(member.issues || []).map((issue) => (
                    <li key={issue} className="text-sm text-warning">{issue}</li>
                  ))}
                </ul>
              )}
            </div>
          </Link>
        ))}
      </div>
    </section>
  );
}
