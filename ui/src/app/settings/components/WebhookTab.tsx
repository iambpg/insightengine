'use client';

import React, { useState } from 'react';
import { toast } from 'sonner';
import Icon from '@/components/ui/AppIcon';
import Badge from '@/components/ui/Badge';
import Toggle from '@/components/ui/Toggle';
import { WEBHOOK_DELIVERIES } from '@/lib/mockData';

const ENDPOINT = 'https://insight.customer.example/api/v1/alertmanager/webhook';

const SNIPPET = `route:
  receiver: insightengine
  group_by: [alertname, device, site]
  group_wait: 20s
  repeat_interval: 4h

receivers:
  - name: insightengine
    webhook_configs:
      - url: ${ENDPOINT}
        send_resolved: true
        http_config:
          authorization:
            type: Bearer
            credentials: <paste the webhook secret>`;

export default function WebhookTab() {
  const [enabled, setEnabled] = useState(true);
  const [resolved, setResolved] = useState(true);
  const [reveal, setReveal] = useState(false);
  const [secret, setSecret] = useState('ie_whsec_9f2c7a41d0b84e6aa3c15b78e02d49f1');
  const [rotating, setRotating] = useState(false);
  const [testing, setTesting] = useState(false);
  const [confirmRotate, setConfirmRotate] = useState(false);

  const copy = (text: string, what: string) => {
    navigator.clipboard?.writeText(text);
    toast.success(`${what} copied to clipboard`);
  };

  const rotate = () => {
    setRotating(true);
    setTimeout(() => {
      setSecret('ie_whsec_' + Array.from({ length: 32 }, (_, i) => '0123456789abcdef'[(i * 7 + 3) % 16]).join(''));
      setRotating(false);
      setConfirmRotate(false);
      setReveal(true);
      toast.success('Secret rotated — update Alertmanager before the next alert');
    }, 700);
  };

  const test = () => {
    setTesting(true);
    setTimeout(() => {
      setTesting(false);
      toast.success('Test alert delivered — HTTP 200 in 43 ms');
    }, 900);
  };

  return (
    <div className="space-y-5">
      <section className="rounded-none border-x-0 border-y border-border bg-card shadow-card" aria-labelledby="wh-title">
        <header className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-5 py-3">
          <div>
            <h2 id="wh-title" className="text-base font-semibold">Alertmanager webhook</h2>
            <p className="text-xs text-muted-foreground">Receives firing and resolved alerts and attaches them to the matching device and port.</p>
          </div>
          <Badge tone={enabled ? 'success' : 'neutral'} icon={enabled ? 'CheckCircleIcon' : 'PauseCircleIcon'}>{enabled ? 'Receiving' : 'Paused'}</Badge>
        </header>

        <div className="space-y-5 p-5">
          <div>
            <label htmlFor="wh-url" className="text-sm font-medium">Endpoint URL</label>
            <p className="text-xs text-muted-foreground">Paste this into the webhook_configs of your Alertmanager receiver.</p>
            <div className="mt-1.5 flex gap-2">
              <input id="wh-url" readOnly value={ENDPOINT} className="h-9 min-w-0 flex-1 rounded-md border border-input bg-muted px-3 font-mono-data text-xs outline-none" />
              <button type="button" onClick={() => copy(ENDPOINT, 'Endpoint URL')} className="inline-flex h-9 items-center gap-1.5 rounded-md border border-border bg-card px-3 text-sm font-medium transition-all hover:bg-muted active:scale-95">
                <Icon name="ClipboardDocumentIcon" size={16} /> Copy
              </button>
            </div>
          </div>

          <div>
            <label htmlFor="wh-secret" className="text-sm font-medium">Shared secret</label>
            <p className="text-xs text-muted-foreground">Sent as a bearer token. Rotating it invalidates the old secret immediately.</p>
            <div className="mt-1.5 flex flex-wrap gap-2">
              <input
                id="wh-secret"
                readOnly
                type={reveal ? 'text' : 'password'}
                value={secret}
                className="h-9 min-w-[240px] flex-1 rounded-md border border-input bg-muted px-3 font-mono-data text-xs outline-none"
              />
              <button type="button" onClick={() => setReveal((v) => !v)} aria-label={reveal ? 'Hide secret' : 'Reveal secret'} className="inline-flex h-9 w-9 items-center justify-center rounded-md border border-border bg-card transition-all hover:bg-muted active:scale-95">
                <Icon name={reveal ? 'EyeSlashIcon' : 'EyeIcon'} size={16} />
              </button>
              <button type="button" onClick={() => copy(secret, 'Secret')} className="inline-flex h-9 items-center gap-1.5 rounded-md border border-border bg-card px-3 text-sm font-medium transition-all hover:bg-muted active:scale-95">
                <Icon name="ClipboardDocumentIcon" size={16} /> Copy
              </button>
              <button type="button" onClick={() => setConfirmRotate(true)} className="inline-flex h-9 items-center gap-1.5 rounded-md border border-destructive/40 px-3 text-sm font-medium text-destructive transition-all hover:bg-destructive/10 active:scale-95">
                <Icon name="KeyIcon" size={16} /> Rotate
              </button>
            </div>
            {confirmRotate && (
              <div role="alert" className="slide-up mt-2 flex flex-wrap items-center justify-between gap-3 rounded-md border border-warning/40 bg-warning/10 px-3 py-2 text-sm">
                <span className="flex items-center gap-2"><Icon name="ExclamationTriangleIcon" size={16} variant="solid" className="text-warning" /> Alerts are rejected until Alertmanager uses the new secret. Rotate now?</span>
                <span className="flex gap-2">
                  <button type="button" onClick={() => setConfirmRotate(false)} className="rounded-md border border-border bg-card px-2.5 py-1 text-xs font-medium active:scale-95">Cancel</button>
                  <button type="button" disabled={rotating} onClick={rotate} className="inline-flex min-w-[96px] items-center justify-center gap-1.5 rounded-md bg-destructive px-2.5 py-1 text-xs font-semibold text-destructive-foreground active:scale-95 disabled:opacity-70">
                    {rotating ? <Icon name="ArrowPathIcon" size={12} className="animate-spin" /> : null}
                    {rotating ? 'Rotating…' : 'Rotate secret'}
                  </button>
                </span>
              </div>
            )}
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="flex items-center justify-between gap-4 rounded-md border border-border p-3">
              <div>
                <p className="text-sm font-medium">Accept alerts</p>
                <p className="text-xs text-muted-foreground">Turn off to pause ingestion during maintenance.</p>
              </div>
              <Toggle checked={enabled} onChange={setEnabled} label="Accept alerts" />
            </div>
            <div className="flex items-center justify-between gap-4 rounded-md border border-border p-3">
              <div>
                <p className="text-sm font-medium">Process resolved alerts</p>
                <p className="text-xs text-muted-foreground">Clear issues on the device page when Alertmanager resolves them.</p>
              </div>
              <Toggle checked={resolved} onChange={setResolved} label="Process resolved alerts" />
            </div>
          </div>

          <div className="flex justify-end">
            <button type="button" disabled={testing || !enabled} onClick={test} className="inline-flex min-w-[170px] items-center justify-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-all hover:opacity-90 active:scale-95 disabled:cursor-not-allowed disabled:opacity-50">
              {testing ? <Icon name="ArrowPathIcon" size={16} className="animate-spin" /> : <Icon name="PaperAirplaneIcon" size={16} />}
              {testing ? 'Sending…' : 'Send test alert'}
            </button>
          </div>
        </div>
      </section>

      <section className="rounded-none border-x-0 border-y border-border bg-card shadow-card" aria-labelledby="snippet-title">
        <header className="flex items-center justify-between border-b border-border px-5 py-3">
          <div>
            <h2 id="snippet-title" className="text-base font-semibold">Alertmanager configuration</h2>
            <p className="text-xs text-muted-foreground">Add this receiver and route to alertmanager.yml.</p>
          </div>
          <button type="button" onClick={() => copy(SNIPPET, 'Configuration')} className="inline-flex items-center gap-1.5 rounded-md border border-border bg-card px-3 py-1.5 text-sm font-medium transition-all hover:bg-muted active:scale-95">
            <Icon name="ClipboardDocumentIcon" size={16} /> Copy
          </button>
        </header>
        <pre className="scroll-thin overflow-x-auto bg-navy p-5 font-mono-data text-xs leading-relaxed text-primary-foreground">{SNIPPET}</pre>
      </section>

      <section className="rounded-none border-x-0 border-y border-border bg-card shadow-card" aria-labelledby="deliv-title">
        <header className="border-b border-border px-5 py-3">
          <h2 id="deliv-title" className="text-base font-semibold">Recent deliveries</h2>
          <p className="text-xs text-muted-foreground">Last 6 requests received today (UTC).</p>
        </header>
        <div className="scroll-thin overflow-x-auto">
          <table className="w-full min-w-[560px] text-sm">
            <thead>
              <tr className="border-b border-border bg-muted/60 text-left text-xs uppercase tracking-wide text-muted-foreground">
                <th scope="col" className="px-5 py-2.5">Time</th>
                <th scope="col" className="px-3 py-2.5">Alert</th>
                <th scope="col" className="px-3 py-2.5">Result</th>
                <th scope="col" className="px-3 py-2.5 text-right">Duration</th>
              </tr>
            </thead>
            <tbody>
              {WEBHOOK_DELIVERIES.map((d) => (
                <tr key={d.id} className="border-b border-border even:bg-muted/20 hover:bg-accent/10">
                  <td className="px-5 py-2.5 font-mono-data text-xs">{d.at}</td>
                  <td className="px-3 py-2.5 font-mono-data text-xs font-semibold">{d.alertname}</td>
                  <td className="px-3 py-2.5">
                    {d.status === 200 ? (
                      <Badge tone="success" icon="CheckCircleIcon">200 OK</Badge>
                    ) : (
                      <Badge tone="destructive" icon="XCircleIcon">{d.status} Error</Badge>
                    )}
                  </td>
                  <td className={`px-3 py-2.5 text-right font-mono-data text-xs tabular ${d.durationMs > 1000 ? 'font-semibold text-destructive' : 'text-muted-foreground'}`}>{d.durationMs} ms</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}