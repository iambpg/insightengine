'use client';

import React, { useId, useMemo, useRef, useState } from 'react';
import type { FaceplateDevice, PortInfo, RadioInfo } from '@/lib/types';
import FaceplateDefs from './FaceplateDefs';
import PortTooltip from './PortTooltip';
import RadioTooltip from './RadioTooltip';
import SwitchLayout, { SW_H, switchWidth } from './layouts/SwitchLayout';
import { STATE_GLYPH, STATE_LABEL } from './palette';
import ApLayout, { AP_H, AP_W } from './layouts/ApLayout';
import { ControllerLayout, FirewallLayout, RouterLayout, APPL_H, APPL_W } from './layouts/AppliancesLayout';
import ModularLayout, { CH_W, chassisHeight } from './layouts/ModularLayout';
import FirewallModelLayout, { FW_MODELS, fwModelHeight, fwModelWidth } from './layouts/FirewallModels';

interface FaceplateProps {
  device: FaceplateDevice;
  selectedPortId?: string | null;
  onSelectPort?: (port: PortInfo | null) => void;
  className?: string;
  compact?: boolean;
}

function allPorts(d: FaceplateDevice): PortInfo[] {
  if (d.members) return d.members.flatMap((m) => m.ports);
  if (d.modules) return d.modules.flatMap((m) => m.ports);
  return d.ports ?? [];
}

// Reusable faceplate. Everything is drawn from the JSON description; nothing is a fixed image.
export default function Faceplate({ device, selectedPortId = null, onSelectPort, className = '', compact = false }: FaceplateProps) {
  const rawId = useId();
  const uid = `fp${rawId.replace(/[^a-zA-Z0-9]/g, '')}`;
  const wrapRef = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<{ port: PortInfo; left: number; top: number } | null>(null);
  const [radioHover, setRadioHover] = useState<{ radio: RadioInfo; left: number; top: number } | null>(null);
  const [selectedRadioId, setSelectedRadioId] = useState<string | null>(null);
  const [activeMember, setActiveMember] = useState<number | null>(null);

  const onHover = (port: PortInfo | null, el: SVGGElement | null) => {
    if (!port || !el) {
      setHover(null);
      return;
    }
    const r = el.getBoundingClientRect();
    const half = 120;
    const left = Math.min(Math.max(r.left + r.width / 2, half + 8), window.innerWidth - half - 8);
    setHover({ port, left, top: r.top - 8 });
  };

  const onRadioHover = (radio: RadioInfo | null, el: SVGGElement | null) => {
    if (!radio || !el) {
      setRadioHover(null);
      return;
    }
    const r = el.getBoundingClientRect();
    const half = 120;
    const left = Math.min(Math.max(r.left + r.width / 2, half + 8), window.innerWidth - half - 8);
    setRadioHover({ radio, left, top: r.top - 8 });
  };
  const onRadioSelect = (radio: RadioInfo) => setSelectedRadioId((cur) => (cur === radio.id ? null : radio.id));

  const onSelect = (p: PortInfo) => onSelectPort?.(selectedPortId === p.id ? null : p);
  const common = { uid, selectedId: selectedPortId, onHover, onSelect };

  const { vbW, vbH, body } = useMemo(() => {
    const pad = 24;
    switch (device.form_factor) {
      case 'access-switch-24': case'access-switch-48': case'generic': {
        const ports = device.ports ?? [];
        const copperCount = ports.filter((p) => p.type === 'RJ45').length;
        const w = switchWidth(copperCount);
        return { vbW: w + pad * 2, vbH: SW_H + pad * 2, body: <SwitchLayout ports={ports} originX={pad} originY={pad} {...common} /> };
      }
      case 'switch-stack': {
        const members = device.members ?? [];
        const current = members.find((m) => m.number === activeMember) ?? members[0];
        if (!current) return { vbW: 400, vbH: 120, body: null };
        const copperCount = current.ports.filter((p) => p.type === 'RJ45').length;
        const w = switchWidth(copperCount);
        return {
          vbW: w + pad * 2,
          vbH: SW_H + pad * 2,
          body: (
            <SwitchLayout
              ports={current.ports}
              originX={pad}
              originY={pad}
              {...common}
              memberNumber={current.number}
              memberHealthColor={
                current.health === 'healthy' ? 'var(--success)' : current.health === 'warning' ? 'var(--warning)' : 'var(--destructive)'
              }
              stackPorts
            />
          ),
        };
      }
      case 'ceiling-ap':
        return {
          vbW: AP_W + pad,
          vbH: AP_H + pad,
          body: (
            <g transform={`translate(${pad / 2} ${pad / 2})`}>
              <ApLayout ports={device.ports ?? []} radios={device.radios ?? []} apState={device.apState ?? 'up'} selectedRadioId={selectedRadioId} onRadioHover={onRadioHover} onRadioSelect={onRadioSelect} {...common} />
            </g>
          ),
        };
      case 'wireless-controller':
        return { vbW: APPL_W + pad * 2, vbH: APPL_H + 10 + pad * 2, body: (<g transform={`translate(${pad} ${pad})`}><ControllerLayout ports={device.ports ?? []} {...common} /></g>) };
      case 'firewall':
        if (device.model && FW_MODELS[device.model]) {
          const fwW = fwModelWidth(device.model);
          return { vbW: fwW + pad * 2, vbH: fwModelHeight(device.model) + pad * 2, body: (<g transform={`translate(${pad} ${pad})`}><FirewallModelLayout ports={device.ports ?? []} model={device.model} {...common} /></g>) };
        }
        return { vbW: APPL_W + pad * 2, vbH: APPL_H + 6 + pad * 2, body: (<g transform={`translate(${pad} ${pad})`}><FirewallLayout ports={device.ports ?? []} {...common} /></g>) };
      case 'branch-router':
        return { vbW: APPL_W + pad * 2, vbH: APPL_H + 22 + pad * 2, body: (<g transform={`translate(${pad} ${pad})`}><RouterLayout ports={device.ports ?? []} filled={device.moduleSlotFilled} {...common} /></g>) };
      case 'modular-chassis': {
        const mods = device.modules ?? [];
        return { vbW: CH_W + pad * 2 + 12, vbH: chassisHeight(mods) + pad * 2, body: (<g transform={`translate(${pad + 6} ${pad})`}><ModularLayout modules={mods} {...common} /></g>) };
      }
      default:
        return { vbW: 400, vbH: 120, body: null };
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [device, selectedPortId, activeMember, selectedRadioId]);

  const ports = allPorts(device);
  const counts = ports.reduce<Record<string, number>>((acc, p) => {
    acc[p.state] = (acc[p.state] ?? 0) + 1;
    return acc;
  }, {});
  const summary = (['up', 'down', 'warning', 'fault', 'disabled'] as const)
    .filter((s) => counts[s])
    .map((s) => `${counts[s]} ${STATE_LABEL[s].toLowerCase()}`)
    .join(', ');

  const stackMembers = device.form_factor === 'switch-stack' ? device.members ?? [] : [];
  const selectedRadio = (device.radios ?? []).find((r) => r.id === selectedRadioId) ?? null;
  const shownMember = stackMembers.find((m) => m.number === activeMember) ?? stackMembers[0];
  const memberCounts = (shownMember?.ports ?? []).reduce<Record<string, number>>((acc, p) => {
    acc[p.state] = (acc[p.state] ?? 0) + 1;
    return acc;
  }, {});
  const memberSummary = (['up', 'down', 'warning', 'fault', 'disabled'] as const)
    .filter((s) => memberCounts[s])
    .map((s) => `${memberCounts[s]} ${STATE_LABEL[s].toLowerCase()}`)
    .join(' · ');

  return (
    <div ref={wrapRef} className={`relative ${className}`}>
      <div className={stackMembers.length > 0 ? 'flex items-stretch gap-3' : ''}>
        <svg
          viewBox={`0 0 ${vbW} ${vbH}`}
          role="group"
          aria-label={`${device.role} faceplate, ${ports.length} ports: ${summary}. Use Tab to move between ports and Enter to open the port graph.`}
          className={`block h-auto ${stackMembers.length > 0 ? 'min-w-0 flex-1' : 'w-full'} ${compact ? 'max-h-24' : ''}`}
          preserveAspectRatio="xMidYMid meet"
        >
          <FaceplateDefs uid={uid} />
          {body}
        </svg>
        {stackMembers.length > 0 && (
          <div className="flex shrink-0 flex-col items-center justify-center gap-1.5" aria-label="Stack members">
            <span className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">Stack</span>
            <div className="grid grid-cols-4 gap-1.5" role="tablist" aria-label="Stack members">
              {stackMembers.map((m, i) => {
                const active = shownMember?.number === m.number;
                const color = m.health === 'healthy' ? 'var(--success)' : m.health === 'warning' ? 'var(--warning)' : 'var(--destructive)';
                return (
                  <button
                    key={m.id}
                    type="button"
                    role="tab"
                    aria-selected={active}
                    aria-label={`Stack member ${m.number}${i === 0 ? ' (master)' : ''}, ${m.health}`}
                    title={`Member ${m.number}${i === 0 ? ' (master)' : ''} · ${m.note}`}
                    onClick={() => {
                      setActiveMember(m.number);
                      onSelectPort?.(null);
                    }}
                    className={`flex h-7 w-7 items-center justify-center rounded border text-xs font-bold font-mono-data transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-ring ${
                      active ? 'bg-primary text-primary-foreground' : 'bg-card text-foreground hover:bg-muted'
                    }`}
                    style={{ borderColor: color }}
                  >
                    {m.number}
                  </button>
                );
              })}
            </div>
            {shownMember && (
              <p className="mt-1 max-w-[150px] text-center text-[10px] leading-snug text-muted-foreground">
                Member {shownMember.number} · {shownMember.ports.length} ports
                {memberSummary ? <><br />{memberSummary}</> : null}
              </p>
            )}
          </div>
        )}
      </div>
      {hover && <PortTooltip port={hover.port} left={hover.left} top={hover.top} />}
      {radioHover && <RadioTooltip radio={radioHover.radio} left={radioHover.left} top={radioHover.top} />}
      {selectedRadio && (
        <div className="mt-3 rounded-lg border bg-card p-4" role="region" aria-label={`${selectedRadio.band} radio details`}>
          <div className="flex items-center justify-between gap-2">
            <h3 className="text-sm font-semibold text-foreground">
              {selectedRadio.band} radio · {STATE_LABEL[selectedRadio.state]}
            </h3>
            <button
              type="button"
              onClick={() => setSelectedRadioId(null)}
              className="rounded border px-2 py-0.5 text-xs text-muted-foreground hover:bg-muted focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              Close
            </button>
          </div>
          <dl className="mt-3 grid grid-cols-2 gap-x-6 gap-y-2 text-xs sm:grid-cols-3">
            {([
              ['Standard', selectedRadio.standard],
              ['Channel', `${selectedRadio.channel}${selectedRadio.channelWidth ? ` (${selectedRadio.channelWidth})` : ''}`],
              ['Clients', String(selectedRadio.clients)],
              ['Utilisation', `${selectedRadio.utilisation}%`],
              ['Throughput', selectedRadio.throughput],
              ['Tx power', selectedRadio.txPower],
              ['Noise floor', selectedRadio.noiseFloor],
              ['Avg client RSSI', selectedRadio.avgRssi],
              ['Retry rate', selectedRadio.retryRate !== undefined ? `${selectedRadio.retryRate}%` : undefined],
              ['SSIDs', selectedRadio.ssids?.join(', ')],
            ] as [string, string | undefined][])
              .filter(([, v]) => v)
              .map(([k, v]) => (
                <div key={k}>
                  <dt className="text-muted-foreground">{k}</dt>
                  <dd className="font-mono-data font-medium text-foreground">{v}</dd>
                </div>
              ))}
          </dl>
        </div>
      )}
    </div>
  );
}

export function FaceplateLegend() {
  return (
    <ul className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs text-muted-foreground" aria-label="Port state legend">
      {(
        [
          ['up', 'var(--success)'],
          ['down', 'var(--down)'],
          ['warning', 'var(--warning)'],
          ['fault', 'var(--destructive)'],
          ['disabled', 'var(--info)'],
        ] as const
      ).map(([s, color]) => (
        <li key={`legend-${s}`} className="flex items-center gap-1.5">
          <span className="inline-block h-3 w-3 rounded-sm border" style={{ backgroundColor: color, borderColor: color }} />
          <span className="font-mono-data" aria-hidden="true" style={{ color }}>
            {STATE_GLYPH[s]}
          </span>
          <span className="font-medium text-foreground">{STATE_LABEL[s]}</span>
        </li>
      ))}
    </ul>
  );
}