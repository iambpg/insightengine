'use client';

import React, { useState } from 'react';
import { Skeleton } from '@/components/ui/Skeleton';
import type { SiteBriefing, SiteNotice } from '@/lib/types';
import InspectNote from '@/components/ui/InspectNote';

type Tab = 'story' | 'talkers';

export default function SiteActivity({
  data,
  error,
  loading,
  updated,
}: {
  data: SiteBriefing | null;
  error: string | null;
  loading: boolean;
  updated: Date | null;
}) {
  const [tab, setTab] = useState<Tab>('story');

  return (
    <article className="rounded-md border border-border bg-card p-4 shadow-card" aria-label="What happened at this site">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold">What is happening at this site</h3>
          <p className="mt-1 text-xs text-muted-foreground">Live, covering the last 4 hours. Device state on this page refreshes about every 30 seconds.</p>
        </div>
        <p className="inline-flex items-center gap-2 text-xs font-medium text-success">
          <span className="h-2 w-2 rounded-full bg-success" aria-hidden="true" />
          Live · last 4 hours{updated ? ` · updated ${updated.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}` : ''}
        </p>
      </div>

      <div role="tablist" aria-label="Site account" className="mt-3 flex gap-2">
        <TabButton selected={tab === 'story'} onClick={() => setTab('story')}>Right now</TabButton>
        <TabButton selected={tab === 'talkers'} onClick={() => setTab('talkers')}>Top talkers</TabButton>
      </div>

      {error ? <p role="alert" className="mt-3 text-sm text-destructive">{error}</p> : null}
      {loading && !data ? <Skeleton className="mt-3 h-28 w-full" /> : null}
      {data && tab === 'story' ? <Story data={data} busy={loading} /> : null}
      {data && tab === 'talkers' ? <Talkers data={data} busy={loading} /> : null}
    </article>
  );
}

function Story({ data, busy }: { data: SiteBriefing; busy: boolean }) {
  return (
    <div className={busy ? 'opacity-70' : ''} aria-busy={busy}>
      <p className="mt-3 text-sm leading-6">{data.summary}</p>
      <div className="mt-3 space-y-3">
        {data.sections.map((section) => (
          <section key={section.id}>
            <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{section.title}</h4>
            <div className="mt-1 text-sm leading-6 text-muted-foreground">
              {section.text}{' '}
              {(section.notices || []).map((notice, index) => (
                <React.Fragment key={notice.id}>
                  {index > 0 ? ' ' : null}
                  <LogNotice notice={notice} />
                </React.Fragment>
              ))}
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}

function LogNotice({ notice }: { notice: SiteNotice }) {
  return (
    <InspectNote label={notice.label} tone={notice.tone} total={notice.total} items={notice.items} />
  );
}

function Talkers({ data, busy }: { data: SiteBriefing; busy: boolean }) {
  return (
    <div className={busy ? 'mt-3 opacity-70' : 'mt-3'} aria-busy={busy}>
      <p className="text-sm text-muted-foreground">{data.talkerNote}</p>
      {data.talkers.length === 0 ? (
        <p className="mt-3 text-sm text-muted-foreground">No interface traffic was returned for {data.window}.</p>
      ) : (
        <table className="mt-3 w-full text-left text-sm">
          <thead>
            <tr className="text-xs text-muted-foreground">
              <th className="py-1 font-medium">Device</th>
              <th className="py-1 font-medium">Port</th>
              <th className="py-1 text-right font-medium">In</th>
              <th className="py-1 text-right font-medium">Out</th>
            </tr>
          </thead>
          <tbody>
            {data.talkers.map((row) => (
              <tr key={`${row.device}-${row.port}`} className="border-t border-border/70">
                <td className="py-1.5 font-mono-data text-xs">{row.device}</td>
                <td className="py-1.5 font-mono-data text-xs">{row.port}</td>
                <td className="py-1.5 text-right tabular">{rate(row.inMbps)}</td>
                <td className="py-1.5 text-right tabular">{rate(row.outMbps)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function rate(mbps: number): string {
  if (mbps >= 1000) return `${(mbps / 1000).toFixed(1)} Gbps`;
  if (mbps >= 10) return `${Math.round(mbps)} Mbps`;
  if (mbps >= 0.1) return `${mbps.toFixed(1)} Mbps`;
  const kbps = mbps * 1000;
  if (kbps >= 1) return `${Math.round(kbps)} Kbps`;
  return `${kbps.toFixed(1)} Kbps`;
}

function TabButton({ selected, onClick, children }: { selected: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={selected}
      onClick={onClick}
      className={`rounded-md px-3 py-1.5 text-sm font-medium ${selected ? 'bg-primary/10 text-foreground' : 'text-muted-foreground hover:bg-muted'}`}
    >
      {children}
    </button>
  );
}
