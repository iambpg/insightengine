'use client';

import React, { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { api } from '@/lib/apiClient';
import { isApiError } from '@/lib/apiError';

type Part = { name: string; percent?: number | null; used?: string; size?: string };
type Service = { name: string; running?: boolean };
type Member = {
  hostname: string;
  ip?: string;
  status?: string;
  healthy?: boolean;
  group?: string;
  roles?: string[];
  cpu?: number | null;
  cpus?: number[];
  memory?: number | null;
  uptime?: string;
  description?: string;
  load?: string[];
  filesystems?: Part[];
  memoryParts?: Part[];
  services?: Service[];
  processes?: Service[];
  issues?: string[];
};

function tone(value?: number | null): string {
  if (value == null) return 'bg-muted-foreground/30';
  if (value >= 90) return 'bg-destructive';
  if (value >= 75) return 'bg-warning';
  return 'bg-success';
}

function Bar({ label, value, detail }: { label: string; value?: number | null; detail?: string }) {
  const width = value == null ? 0 : Math.max(0, Math.min(100, value));
  return (
    <div>
      <div className="flex items-center justify-between gap-3 text-sm">
        <span>{label}</span>
        <span className="tabular font-medium">{value == null ? '—' : `${value}%`}{detail ? <span className="ml-2 font-normal text-muted-foreground">{detail}</span> : null}</span>
      </div>
      <div className="mt-1 h-2 rounded-full bg-muted">
        <div className={`h-2 rounded-full ${tone(value)}`} style={{ width: `${width}%` }} />
      </div>
    </div>
  );
}

export default function InfobloxMemberView({ hostname }: { hostname: string }) {
  const [member, setMember] = useState<Member | null>(null);
  const [grid, setGrid] = useState('');
  const [version, setVersion] = useState('');
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    setLoading(true);
    setError('');
    api
      .netbridgeGet(`/infoblox/members/${encodeURIComponent(hostname)}`)
      .then((body) => {
        const row = body as { member?: Member | null; grid?: string; version?: string; message?: string };
        setMember(row.member || null);
        setGrid(row.grid || '');
        setVersion(row.version || '');
        setMessage(row.message || '');
      })
      .catch((cause) => setError(isApiError(cause) ? cause.message : 'This member could not be loaded.'))
      .finally(() => setLoading(false));
  }, [hostname]);

  useEffect(() => {
    load();
  }, [load]);

  const loadText = (member?.load || []).length === 3
    ? `1 min ${member?.load?.[0]} · 5 min ${member?.load?.[1]} · 15 min ${member?.load?.[2]}`
    : (member?.load || []).join(' · ');

  return (
    <div className="space-y-5 px-4">
      <div>
        <Link href="/infoblox" className="text-sm font-medium text-primary">Back to Infoblox</Link>
        <div className="mt-2 flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">{member?.hostname || hostname}</h1>
            <p className="mt-1 text-sm text-muted-foreground">{member?.ip || 'Member detail'}</p>
          </div>
          <button type="button" onClick={load} className="rounded-md border border-border bg-card px-3 py-1.5 text-sm">Refresh</button>
        </div>
      </div>

      {error ? <p role="alert" className="rounded-md border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">{error}</p> : null}
      {loading ? <p className="text-sm text-muted-foreground">Loading this member…</p> : null}
      {!loading && message ? <p className="rounded-md border border-warning/40 bg-warning/10 px-4 py-3 text-sm">{message}</p> : null}

      {member ? (
        <>
          <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <Info label="Status" value={member.healthy ? 'Healthy' : member.status || 'Unknown'} />
            <Info label="Address" value={member.ip || '—'} />
            <Info label="Uptime" value={member.uptime || '—'} />
            <Info label="Grid" value={grid || version || '—'} />
          </section>

          <section className="rounded-md border border-border bg-card p-4">
            <h2 className="text-base font-semibold">Identity</h2>
            <p className="mt-1 text-sm text-muted-foreground">{member.group === 'grid' ? 'Grid Master' : 'Member'} · {(member.roles || []).join(' · ') || 'No role reported'}</p>
            {member.description ? <p className="mt-2 text-sm">{member.description}</p> : null}
            {loadText ? <p className="mt-2 text-sm">Load average {loadText}</p> : null}
          </section>

          <ServiceList title="API services" services={member.services || []} empty="No service status from the API." />
          <ServiceList title="SNMP processes" services={member.processes || []} empty="No process status from SNMP." />

          <section className="rounded-md border border-border bg-card p-4" aria-label="CPU">
            <h2 className="text-base font-semibold">CPU</h2>
            <div className="mt-3"><Bar label="Average" value={member.cpu} /></div>
            <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              {(member.cpus || []).map((value, index) => (
                <Bar key={`cpu-${index}`} label={`Core ${index + 1}`} value={value} />
              ))}
            </div>
          </section>

          <section className="rounded-md border border-border bg-card p-4" aria-label="Memory">
            <h2 className="text-base font-semibold">Memory</h2>
            <div className="mt-3 space-y-3">
              {(member.memoryParts || []).length === 0 ? <Bar label="Physical memory" value={member.memory} /> : null}
              {(member.memoryParts || []).map((part) => (
                <Bar key={part.name} label={part.name} value={part.percent} detail={part.used && part.size ? `${part.used} of ${part.size}` : ''} />
              ))}
            </div>
          </section>

          <section className="rounded-md border border-border bg-card p-4" aria-label="Disks">
            <h2 className="text-base font-semibold">Disks</h2>
            <div className="mt-3 space-y-3">
              {(member.filesystems || []).length === 0 ? <p className="text-sm text-muted-foreground">No disk reading.</p> : null}
              {(member.filesystems || []).map((part) => (
                <Bar key={part.name} label={part.name} value={part.percent} detail={part.used && part.size ? `${part.used} of ${part.size}` : ''} />
              ))}
            </div>
          </section>

          <section className="rounded-md border border-border bg-card p-4" aria-label="Issues">
            <h2 className="text-base font-semibold">Issues</h2>
            {(member.issues || []).length === 0 ? <p className="mt-2 text-sm text-muted-foreground">No issues.</p> : (
              <ul className="mt-2 space-y-1">
                {(member.issues || []).map((issue) => <li key={issue} className="text-sm text-warning">{issue}</li>)}
              </ul>
            )}
          </section>
        </>
      ) : null}
    </div>
  );
}

function ServiceList({ title, services, empty }: { title: string; services: Service[]; empty: string }) {
  return (
    <section className="rounded-md border border-border bg-card p-4" aria-label={title}>
      <h2 className="text-base font-semibold">{title}</h2>
      {services.length === 0 ? <p className="mt-2 text-sm text-muted-foreground">{empty}</p> : (
        <ul className="mt-3 flex flex-wrap gap-2">
          {services.map((service) => (
            <li key={service.name} className={`rounded-md px-2.5 py-1 text-sm font-medium ${service.running === false ? 'bg-warning/15' : 'bg-success/10 text-success'}`}>{service.name}</li>
          ))}
        </ul>
      )}
    </section>
  );
}

function Info({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-border bg-card p-4">
      <p className="text-xs uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className="mt-1 text-lg font-semibold">{value}</p>
    </div>
  );
}
