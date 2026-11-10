'use client';

import React, { useId, useMemo, useRef, useState } from 'react';
import type { FaceplateDevice, PortInfo, RadioInfo } from '@/lib/types';
import FaceplateDefs from './FaceplateDefs';
import PortTooltip from './PortTooltip';
import RadioTooltip from './RadioTooltip';
import FortiGateLayout from './layouts/FortiGateLayout';
import SwitchLayout from './layouts/SwitchLayout';
import { CHASSIS_WIDTH, FACEPLATE_HEIGHT, lockedChassis } from './size';

export { FACEPLATE_HEIGHT };
import { isFortiGateModel, isFortiSwitchModel } from './library/fortigate';
import { STATE_GLYPH, STATE_LABEL } from './palette';
import { countPorts, faceplateSummaryLine, SNMP_MISSING_HINT } from './summary';
import ApLayout, { AP_H, AP_W } from './layouts/ApLayout';
import RealisticFaceplate from './RealisticFaceplate';
import { useFaceplateModel } from './library/catalog';

interface FaceplateProps {
  device: FaceplateDevice;
  selectedPortId?: string | null;
  onSelectPort?: (port: PortInfo | null) => void;
  className?: string;
  compact?: boolean;
  caption?: boolean;
}

function allPorts(d: FaceplateDevice): PortInfo[] {
  if (d.members) return d.members.flatMap((m) => m.ports);
  if (d.modules) return d.modules.flatMap((m) => m.ports);
  return d.ports ?? [];
}

// Reusable faceplate. Everything is drawn from the JSON description; nothing is a fixed image.
export default function Faceplate({ device, selectedPortId = null, onSelectPort, className = '', compact = false, caption = true }: FaceplateProps) {
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
  const art = useFaceplateModel(device);

  const { vbW, vbH, body } = useMemo(() => {
    const pad = 8;
    const frame = lockedChassis(pad);
    if (device.form_factor === 'ceiling-ap') {
      const scale = Math.min(frame.innerW / AP_W, frame.innerH / AP_H);
      const x = pad + (frame.innerW - AP_W * scale) / 2;
      const y = pad + (frame.innerH - AP_H * scale) / 2;
      return {
        vbW: frame.vbW,
        vbH: frame.vbH,
        body: (
          <g transform={`translate(${x} ${y}) scale(${scale})`}>
            <ApLayout ports={device.ports ?? []} radios={device.radios ?? []} apState={device.apState ?? 'up'} selectedRadioId={selectedRadioId} onRadioHover={onRadioHover} onRadioSelect={onRadioSelect} {...common} />
          </g>
        ),
      };
    }
    if (art && (isFortiGateModel(art) || isFortiSwitchModel(art)) && art.ports.length > 0) {
      const ports = device.modules?.length ? device.modules.flatMap((module) => module.ports) : (device.ports ?? []);
      return {
        vbW: frame.vbW,
        vbH: frame.vbH,
        body: (
          <g transform={`translate(${pad} ${pad})`}>
            <FortiGateLayout model={art} ports={ports} {...common} />
          </g>
        ),
      };
    }
    switch (device.form_factor) {
      case 'access-switch-24': case 'access-switch-48': case 'generic':
      case 'firewall': case 'branch-router': case 'wireless-controller': case 'modular-chassis': {
        const ports = device.modules?.length ? device.modules.flatMap((module) => module.ports) : (device.ports ?? []);
        return { vbW: frame.vbW, vbH: frame.vbH, body: <SwitchLayout ports={ports} originX={pad} originY={pad} {...common} /> };
      }
      case 'switch-stack': {
        const members = device.members ?? [];
        const current = members.find((m) => m.number === activeMember) ?? members[0];
        if (!current) return { vbW: frame.vbW, vbH: frame.vbH, body: null };
        return {
          vbW: frame.vbW,
          vbH: frame.vbH,
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
      default:
        return { vbW: 400, vbH: 120, body: null };
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [device, art, selectedPortId, activeMember, selectedRadioId]);

  const ports = allPorts(device);
  const counts = countPorts(ports);
  const summary = faceplateSummaryLine(counts, device.snmpAt);
  const snmpHint = device.snmpMissing ? SNMP_MISSING_HINT : '';

  const stackMembers = device.form_factor === 'switch-stack' ? device.members ?? [] : [];
  const selectedRadio = (device.radios ?? []).find((r) => r.id === selectedRadioId) ?? null;
  const shownMember = stackMembers.find((m) => m.number === activeMember) ?? stackMembers[0];
  const memberCounts = (shownMember?.ports ?? []).reduce<Record<string, number>>((acc, p) => {
    acc[p.state] = (acc[p.state] ?? 0) + 1;
    return acc;
  }, {});
  const memberSummary = (['up', 'down', 'not-connected', 'warning', 'fault', 'disabled', 'unknown'] as const)
    .filter((s) => memberCounts[s])
    .map((s) => `${memberCounts[s]} ${STATE_LABEL[s].toLowerCase()}`)
    .join(' · ');

  const stackSwitcher = stackMembers.length > 0 ? (
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
  ) : null;

  // A photo or stencil is shown only when its port map sat on the cages in the
  // picture. Anything else, including a failed alignment, uses the drawn faceplate.
  // A stack uses the same faceplate for the member that is selected.
  const pictured = shownMember
    ? { ...device, members: undefined, modules: undefined, ports: shownMember.ports }
    : device;
  if (art && art.front && art.source !== 'drawn' && !compact && !isFortiGateModel(art) && device.form_factor !== 'ceiling-ap') {
    return (
      <div ref={wrapRef} className={`relative w-full min-w-0 ${className}`}>
        <div className={stackSwitcher ? 'flex w-full min-w-0 items-stretch gap-3' : 'w-full min-w-0'}>
          <div className="min-w-0 flex-1">
            <RealisticFaceplate device={pictured} model={art} selectedPortId={selectedPortId} onHover={onHover} onSelect={onSelect} caption={caption} />
          </div>
          {stackSwitcher}
        </div>
        {hover && <PortTooltip port={hover.port} left={hover.left} top={hover.top} />}
        {radioHover && <RadioTooltip radio={radioHover.radio} left={radioHover.left} top={radioHover.top} />}
      </div>
    );
  }

  return (
    <div ref={wrapRef} className={`relative w-full min-w-0 ${className}`}>
      <div className={stackMembers.length > 0 ? 'flex w-full min-w-0 items-stretch gap-3' : 'w-full min-w-0'}>
        <svg
          viewBox={`0 0 ${vbW} ${vbH}`}
          role="group"
          aria-label={`${device.role} faceplate, ${ports.length} ports: ${summary}${snmpHint ? `. ${snmpHint}` : ''}. Use Tab to move between ports and Enter to open the port graph.`}
          className={`block h-auto min-w-0 ${stackMembers.length > 0 ? 'flex-1' : 'w-full'} ${compact ? 'max-h-24 w-full' : ''}`}
          style={compact ? undefined : { aspectRatio: `${CHASSIS_WIDTH} / ${FACEPLATE_HEIGHT}`, width: '100%' }}
          preserveAspectRatio="xMidYMid meet"
        >
          <FaceplateDefs uid={uid} />
          {body}
        </svg>
        {stackSwitcher}
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
          ['not-connected', 'var(--down)'],
          ['disabled', 'var(--disabled)'],
          ['unknown', 'var(--unknown)'],
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