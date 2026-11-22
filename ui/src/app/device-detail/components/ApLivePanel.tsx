'use client';

import React, { useEffect, useState } from 'react';
import Link from 'next/link';
import { api } from '@/lib/apiClient';
import { isApiError } from '@/lib/apiError';
import type { ApLiveResponse } from '@/lib/liveApi';

function formatSast(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  const clock = new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Africa/Johannesburg',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hourCycle: 'h23',
  }).format(date);
  return `${clock} SAST`;
}

function platformLabel(platform: string): string {
  if (platform === 'aireos') return 'AireOS';
  if (platform === 'iosxe') return 'IOS-XE';
  return platform || 'controller';
}

function foundBy(data: ApLiveResponse): string {
  if (data.resolvedBy === 'metrics') return 'metrics';
  if (data.resolvedBy === 'netbox') return 'NetBox';
  const count = data.attempts.length || 1;
  return `searched ${count} controllers`;
}

function Fact({ label, value }: { label: string; value?: string | null }) {
  if (!value) return null;
  return (
    <div className="flex justify-between gap-3 border-b border-border/60 py-1">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="text-right font-mono-data text-foreground">{value}</dd>
    </div>
  );
}

export default function ApLivePanel({
  apKey,
  wlcHint,
  telemetryMissing,
}: {
  apKey: string;
  wlcHint: string;
  telemetryMissing: boolean;
}) {
  const [nonce, setNonce] = useState(0);
  const [phase, setPhase] = useState<'loading' | 'ready' | 'error'>('loading');
  const [data, setData] = useState<ApLiveResponse | null>(null);
  const [failure, setFailure] = useState<unknown>(null);

  useEffect(() => {
    if (!apKey) return undefined;
    let cancel = false;
    setPhase('loading');
    setFailure(null);
    api.getAccessPointLive(apKey, wlcHint, nonce > 0)
      .then((body) => {
        if (cancel) return;
        setData(body);
        setPhase('ready');
      })
      .catch((error) => {
        if (cancel) return;
        setFailure(error);
        setPhase('error');
      });
    return () => {
      cancel = true;
    };
  }, [apKey, wlcHint, nonce]);

  const error = isApiError(failure) ? failure : null;
  const wlc = (error?.details as { wlc?: { id?: string; name?: string } } | undefined)?.wlc;
  const fields = data?.accessPoint;

  return (
    <section data-testid="ap-live-panel" aria-label="Live from the wireless controller" className="rounded-md border border-border bg-card p-3 text-sm text-foreground shadow-card">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="font-medium">
          {phase === 'ready' && data ? (
            <>
              Live from <span className="font-semibold">{data.wlc.name}</span> ({platformLabel(data.wlc.platform)}) · fetched {formatSast(data.fetchedAt)}
            </>
          ) : phase === 'loading' ? (
            <span data-testid="ap-live-status">{wlcHint ? `Asking ${wlcHint}…` : 'Searching controllers…'}</span>
          ) : (
            <span>Live lookup</span>
          )}
        </p>
        <button
          type="button"
          onClick={() => setNonce((value) => value + 1)}
          className="rounded-md border border-border bg-card px-3 py-1.5 text-sm font-semibold text-foreground hover:bg-muted"
        >
          Refresh
        </button>
      </div>
      {telemetryMissing ? (
        <p data-testid="ap-live-no-prometheus" className="mt-2 text-muted-foreground">Not in Prometheus. Telemetry from this AP is not arriving.</p>
      ) : null}
      {phase === 'error' ? (
        <div role="alert" data-testid={`ap-live-error-${error?.code || 'failed'}`} className="mt-3 rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-foreground">
          <p>{error?.message || 'The live lookup failed.'}</p>
          {error?.code === 'no_ssh_credentials' && wlc?.id ? (
            <Link href={`/device-cli?id=${encodeURIComponent(wlc.id)}&form=wireless-controller`} className="mt-1 inline-block font-semibold text-primary hover:underline">
              Open Device CLI for {wlc.name || 'this controller'}
            </Link>
          ) : null}
        </div>
      ) : null}
      {phase === 'ready' && fields ? (
        <>
          <dl className="mt-3 grid grid-cols-1 gap-x-6 sm:grid-cols-2">
            <Fact label="Name" value={fields.name} />
            <Fact label="MAC" value={fields.mac} />
            <Fact label="IP" value={fields.ip} />
            <Fact label="Model" value={fields.model} />
            <Fact label="Serial" value={fields.serial} />
            <Fact label="Software" value={fields.ios} />
            <Fact label="Mode" value={fields.mode} />
            <Fact label="Admin" value={fields.adminState} />
            <Fact label="Oper" value={fields.operState} />
            <Fact label="Uptime" value={fields.uptime} />
            <Fact label="Join time" value={fields.joinTime} />
            <Fact label="Location" value={fields.location} />
            <Fact label="Country" value={fields.country} />
            <Fact label="Primary controller" value={fields.primaryController} />
            <Fact label="Secondary controller" value={fields.secondaryController} />
            <Fact label="Site tag" value={fields.siteTag} />
            <Fact label="Policy tag" value={fields.policyTag} />
            <Fact label="RF tag" value={fields.rfTag} />
            <Fact label="AP group" value={fields.apGroup} />
            <Fact label="FlexConnect group" value={fields.flexGroup} />
            <Fact label="Power" value={fields.power} />
            <Fact label="CDP switch" value={fields.cdpSwitch} />
            <Fact label="CDP port" value={fields.cdpPort} />
          </dl>
          {fields.radios?.length ? (
            <ul className="mt-3 space-y-1">
              {fields.radios.map((radio) => (
                <li key={radio.slot} className="font-mono-data text-foreground">
                  Slot {radio.slot}: admin {radio.admin || '—'} · oper {radio.oper || '—'} · channel {radio.channel || '—'} · tx {radio.txPower || '—'}
                </li>
              ))}
            </ul>
          ) : null}
          <p className="mt-3 text-muted-foreground">Found by: {foundBy(data)}</p>
        </>
      ) : null}
    </section>
  );
}
