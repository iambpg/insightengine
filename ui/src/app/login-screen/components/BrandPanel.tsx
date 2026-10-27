import React from 'react';
import AppLogo from '@/components/ui/AppLogo';
import Faceplate from '@/components/faceplate/Faceplate';
import { buildFaceplateFor } from '@/lib/mockData';
import Icon from '@/components/ui/AppIcon';

const POINTS = [
  { icon: 'CpuChipIcon', text: 'Faceplates drawn from live device data, down to the port' },
  { icon: 'ChartBarIcon', text: 'Zoomable utilisation and error graphs for every panel' },
  { icon: 'BellAlertIcon', text: 'Alertmanager alerts attached to the exact device and port' },
];

export default function BrandPanel() {
  const device = buildFaceplateFor('firewall');
  return (
    <aside className="relative hidden overflow-hidden bg-navy text-primary-foreground lg:flex lg:flex-col lg:justify-between lg:p-12 grid-bg-navy" aria-label="About InsightEngine">
      <div className="gradient-blob pointer-events-none absolute -right-24 -top-24 h-96 w-96" aria-hidden="true" />
      <div className="relative flex items-center gap-3">
        <AppLogo size={44} />
        <div className="leading-tight">
          <p className="text-lg font-semibold tracking-tight">InsightEngine</p>
          <p className="text-xs text-cyan">Network observability</p>
        </div>
      </div>

      <div className="relative">
        <h2 className="max-w-lg text-4xl font-semibold leading-tight tracking-tight">
          From a ticket to the failing port in <span className="text-cyan">two clicks</span>.
        </h2>
        <ul className="mt-6 space-y-3">
          {POINTS?.map((p) => (
            <li key={p?.text} className="flex items-start gap-3 text-sm text-primary-foreground/85">
              <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-navy-3 text-teal">
                <Icon name={p?.icon} size={16} />
              </span>
              {p?.text}
            </li>
          ))}
        </ul>

        <div className="mt-8 max-w-xl rounded-xl border border-navy-3 bg-navy-2/70 p-4 shadow-pop">
          <div className="mb-2 flex items-center justify-between text-xs">
            <span className="font-mono-data text-down">fw-ams01-a · Firewall</span>
            <span className="inline-flex items-center gap-1 rounded-full border border-destructive/50 px-2 py-0.5 font-semibold text-destructive">✕ 1 port faulted</span>
          </div>
          <Faceplate device={device} />
        </div>
      </div>

      <p className="relative text-xs text-down">Example data. Generic artwork — no vendor logos, trademarks or model names.</p>
    </aside>
  );
}