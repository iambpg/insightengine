import React from 'react';
import CollapsiblePanel from '@/components/ui/CollapsiblePanel';
import type { DeviceHealthPanel, HealthGroup } from '@/lib/types';

const TONE: Record<HealthGroup['status'], string> = {
  ok: 'text-success',
  warn: 'text-warning',
  fail: 'text-destructive',
  unknown: 'text-muted-foreground',
  unsupported: 'text-muted-foreground',
};

function Fact({ label, value }: { label: string; value?: string | null }) {
  if (!value) return null;
  return (
    <div className="flex justify-between gap-3">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="font-mono-data">{value}</dd>
    </div>
  );
}

function pct(value: number | null): string {
  if (value === null || Number.isNaN(value)) return '—';
  return `${Math.round(value * 100)}%`;
}

function rate(value: number | null): string {
  if (value === null || Number.isNaN(value)) return '—';
  return value.toFixed(2);
}

function healthSubtitle(panel: DeviceHealthPanel): string {
  const sensors = panel.groups.map((group) => group.label.toLowerCase());
  if (sensors.length === 0) return `${panel.profileLabel}. Busiest interfaces.`;
  return `${panel.profileLabel}. ${sensors.join(', ')} and the busiest interfaces.`;
}

export default function HealthPanel({ panel }: { panel: DeviceHealthPanel }) {
  return (
    <CollapsiblePanel
      title="Health"
      titleId="health-panel-title"
      subtitle={healthSubtitle(panel)}
    >
      {panel.groups.length > 0 ? (
      <ul className="grid grid-cols-1 gap-px bg-border sm:grid-cols-2 xl:grid-cols-4">
        {panel.groups.map((group) => (
          <li key={group.id} className="bg-card px-4 py-3">
            <p className="label-caps text-muted-foreground">{group.label}</p>
            <p className={`mt-1 text-sm font-semibold ${TONE[group.status]}`}>{group.value}</p>
            <p className="mt-1 text-xs text-muted-foreground">{group.detail}</p>
          </li>
        ))}
      </ul>
      ) : null}
      {panel.wlc ? (
        <div className="border-t border-border px-4 py-3 text-sm">
          <p className="font-medium">Controller summary</p>
          <p className="mt-1 text-muted-foreground">
            Joined APs {panel.wlc.joinedAps ?? '—'} · clients {panel.wlc.clients ?? '—'}. {panel.wlc.note}
          </p>
        </div>
      ) : null}
      {panel.accessPoint ? (
        <div className="border-t border-border px-4 py-3 text-sm">
          <p className="font-medium">Access point</p>
          <p className="mt-1 text-muted-foreground">{panel.accessPoint.note}</p>
          <p className="mt-2">
            {panel.accessPoint.wlc ? `Joined WLC ${panel.accessPoint.wlc} · ` : ''}
            status {panel.accessPoint.status} · clients {panel.accessPoint.clients ?? '—'} · uptime{' '}
            {panel.accessPoint.uptimeSeconds === null || panel.accessPoint.uptimeSeconds === undefined
              ? '—'
              : `${Math.round(panel.accessPoint.uptimeSeconds / 60)} min`}
          </p>
          <dl className="mt-2 grid gap-1 text-xs sm:grid-cols-2">
            <Fact label="Model" value={panel.accessPoint.model} />
            <Fact label="Serial" value={panel.accessPoint.serial} />
            <Fact label="IP" value={panel.accessPoint.ip} />
            <Fact label="MAC" value={panel.accessPoint.mac} />
            <Fact label="Location" value={panel.accessPoint.location} />
            <Fact label="Software" value={panel.accessPoint.ios} />
            <Fact label="Site tag" value={panel.accessPoint.siteTag} />
            <Fact label="CDP neighbour" value={panel.accessPoint.neighborSwitch ? `${panel.accessPoint.neighborSwitch} ${panel.accessPoint.neighborPort || ''}`.trim() : ''} />
          </dl>
          {panel.accessPoint.radios.length > 0 ? (
            <ul className="mt-2 space-y-1 font-mono-data text-xs">
              {panel.accessPoint.radios.map((radio) => (
                <li key={radio.slot}>
                  slot {radio.slot || '—'} · channel {radio.channel ?? '—'} · util {pct(radio.utilization)} · clients {radio.clients ?? '—'}
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
      <div className="border-t border-border px-4 py-3">
        <h3 className="text-sm font-semibold">Interface utilization and drops</h3>
        {!panel.interfacesSupported ? (
          <p className="mt-1 text-sm text-muted-foreground">{panel.interfacesNote}</p>
        ) : panel.interfaces.length === 0 ? (
          <p className="mt-1 text-sm text-muted-foreground">No interface sample yet.</p>
        ) : (
          <table className="mt-2 w-full border-collapse text-sm">
            <thead>
              <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-muted-foreground">
                <th className="py-1.5 pr-3 font-semibold">Interface</th>
                <th className="py-1.5 pr-3 font-semibold">Utilization</th>
                <th className="py-1.5 pr-3 font-semibold">Drops/s</th>
                <th className="py-1.5 font-semibold">Path</th>
              </tr>
            </thead>
            <tbody>
              {panel.interfaces.map((row) => (
                <tr key={row.ifIndex || row.name} className="border-b border-border/70">
                  <td className="py-1.5 pr-3 font-mono-data">{row.name}</td>
                  <td className="py-1.5 pr-3 tabular">{pct(row.utilization)}</td>
                  <td className="py-1.5 pr-3 tabular">{rate(row.dropsRate)}</td>
                  <td className="py-1.5">{row.criticalPath ? <span className="font-semibold text-warning">critical-path</span> : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </CollapsiblePanel>
  );
}
