'use client';

import React, { useId, useLayoutEffect, useMemo, useRef, useState } from 'react';
import type { FaceplateDevice, PortInfo, RadioInfo } from '@/lib/types';
import FaceplateDefs from './FaceplateDefs';
import PortTooltip from './PortTooltip';
import RadioTooltip from './RadioTooltip';
import FortiGateLayout from './layouts/FortiGateLayout';
import SwitchLayout, { switchCanvas } from './layouts/SwitchLayout';
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
  selectedRadioId?: string | null;
  onSelectRadio?: (radio: RadioInfo) => void;
  className?: string;
  compact?: boolean;
  caption?: boolean;
  health?: string;
  chassisLabel?: string;
  activeMember?: number;
  /** Pixel width of the grey panel up to the parent divider. The chassis fills it. */
  spanWidth?: number;
}

function allPorts(d: FaceplateDevice): PortInfo[] {
  if (d.members) return d.members.flatMap((m) => m.ports);
  if (d.modules) return d.modules.flatMap((m) => m.ports);
  return d.ports ?? [];
}

// Reusable faceplate. Everything is drawn from the JSON description; nothing is a fixed image.
function memberLed(health: string | undefined): string {
  if (health === 'fault' || health === 'critical') return 'critical';
  if (health === 'warning') return 'warning';
  if (health === 'healthy') return 'healthy';
  return 'unknown';
}

function memberInk(health: string | undefined): string {
  if (health === 'fault' || health === 'critical') return '#ef4444';
  if (health === 'warning') return '#f59e0b';
  if (health === 'healthy') return '#22c55e';
  return '#94a3b8';
}

export default function Faceplate({ device, selectedPortId = null, onSelectPort, selectedRadioId = null, onSelectRadio, className = '', compact = false, caption = true, health, chassisLabel, activeMember, spanWidth = 0 }: FaceplateProps) {
  const rawId = useId();
  const uid = `fp${rawId.replace(/[^a-zA-Z0-9]/g, '')}`;
  const wrapRef = useRef<HTMLDivElement>(null);
  const [measured, setMeasured] = useState(0);
  const [hover, setHover] = useState<{ port: PortInfo; left: number; top: number } | null>(null);
  const [radioHover, setRadioHover] = useState<{ radio: RadioInfo; left: number; top: number } | null>(null);
  const [localRadioId, setLocalRadioId] = useState<string | null>(null);
  const activeRadioId = onSelectRadio ? selectedRadioId : localRadioId;

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
  const onRadioSelect = (radio: RadioInfo) => {
    if (onSelectRadio) onSelectRadio(radio);
    else setLocalRadioId((cur) => (cur === radio.id ? null : radio.id));
  };

  useLayoutEffect(() => {
    const el = wrapRef.current;
    if (!el || spanWidth > 0) return undefined;
    const read = () => setMeasured(el.clientWidth);
    read();
    if (typeof ResizeObserver === 'undefined') return undefined;
    const observer = new ResizeObserver(read);
    observer.observe(el);
    return () => observer.disconnect();
  }, [spanWidth, device.form_factor, activeMember]);

  const onSelect = (p: PortInfo) => onSelectPort?.(selectedPortId === p.id ? null : p);
  const common = { uid, selectedId: selectedPortId, onHover, onSelect };
  const art = useFaceplateModel(device);
  const shown = device.form_factor === 'switch-stack' && device.members?.length
    ? {
        ...device,
        members: [device.members.find((member) => member.number === activeMember) ?? device.members[0]],
      }
    : device;

  const span = spanWidth > 0 ? spanWidth : measured;
  const { vbW, vbH, body, rowCount } = useMemo(() => {
    const pad = 8;
    const frame = lockedChassis(pad);
    // The drawn chassis fills the grey panel from its left edge to the parent divider.
    const fit = (naturalWidth: number, naturalHeight: number) => {
      const boxH = naturalHeight + pad * 2;
      const natural = naturalWidth + pad * 2;
      const slotH = FACEPLATE_HEIGHT - 26;
      const filled = span > 8 ? (span / slotH) * boxH : natural;
      const width = Math.max(natural, filled);
      return { vbW: width, vbH: boxH, canvasWidth: width - pad * 2 };
    };
    if (device.form_factor === 'ceiling-ap') {
      const scale = Math.min(frame.innerW / AP_W, frame.innerH / AP_H);
      const x = pad + (frame.innerW - AP_W * scale) / 2;
      const y = pad + (frame.innerH - AP_H * scale) / 2;
        return {
        vbW: frame.vbW,
        vbH: frame.vbH,
        rowCount: 1,
        body: (
          <g transform={`translate(${x} ${y}) scale(${scale})`}>
            <ApLayout ports={device.ports ?? []} radios={device.radios ?? []} apState={device.apState ?? 'up'} selectedRadioId={activeRadioId} onRadioHover={onRadioHover} onRadioSelect={onRadioSelect} {...common} />
          </g>
        ),
      };
    }
    if (art && (isFortiGateModel(art) || isFortiSwitchModel(art)) && art.ports.length > 0) {
      const ports = device.modules?.length ? device.modules.flatMap((module) => module.ports) : (device.ports ?? []);
        return {
        vbW: frame.vbW,
        vbH: frame.vbH,
        rowCount: 1,
        body: (
          <g transform={`translate(${pad} ${pad})`}>
            <FortiGateLayout model={art} ports={ports} {...common} />
          </g>
        ),
      };
    }
    switch (shown.form_factor) {
      case 'access-switch-24': case 'access-switch-48': case 'generic':
      case 'firewall': case 'branch-router': case 'wireless-controller': case 'modular-chassis': {
        const ports = device.modules?.length ? device.modules.flatMap((module) => module.ports) : (device.ports ?? []);
        const canvas = switchCanvas(ports);
        const box = fit(canvas.width, canvas.height);
        return {
          vbW: box.vbW,
          vbH: box.vbH,
          rowCount: 1,
          body: (
            <SwitchLayout
              ports={ports}
              originX={pad}
              originY={pad}
              canvasWidth={box.canvasWidth}
              {...common}
              ledHealth={health}
              modelLabel={chassisLabel || device.modelName || device.model || ''}
            />
          ),
        };
      }
      case 'switch-stack': {
        const member = shown.members?.[0];
        const ports = member?.ports ?? [];
        const canvas = switchCanvas(ports);
        const box = fit(canvas.width, canvas.height);
        return {
          vbW: box.vbW,
          vbH: box.vbH,
          rowCount: 1,
          body: member ? (
            <SwitchLayout
              ports={member.ports}
              originX={pad}
              originY={pad}
              canvasWidth={box.canvasWidth}
              {...common}
              memberNumber={member.number}
              memberHealthColor={memberInk(member.health)}
              ledHealth={memberLed(member.health)}
              modelLabel={chassisLabel || device.modelName || device.model || ''}
            />
          ) : null,
        };
      }
      default:
        return { vbW: 400, vbH: 120, rowCount: 1, body: null };
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [shown, art, selectedPortId, activeRadioId, health, chassisLabel, span]);

  const ports = allPorts(shown);
  const counts = countPorts(ports);
  const summary = faceplateSummaryLine(counts, device.snmpAt);
  const snmpHint = device.snmpMissing ? SNMP_MISSING_HINT : '';

  const stackRows = rowCount || 1;

  if (art && art.front && art.source !== 'drawn' && !compact && !isFortiGateModel(art) && device.form_factor !== 'ceiling-ap' && device.form_factor !== 'switch-stack') {
    return (
      <div ref={wrapRef} className={`relative w-full min-w-0 ${className}`}>
        <RealisticFaceplate device={device} model={art} selectedPortId={selectedPortId} onHover={onHover} onSelect={onSelect} caption={caption} />
        {hover && <PortTooltip port={hover.port} left={hover.left} top={hover.top} />}
        {radioHover && <RadioTooltip radio={radioHover.radio} left={radioHover.left} top={radioHover.top} />}
      </div>
    );
  }

  // The panel stays 168px. This slot is the metal; the strip below it is the parent cable.
  const chassisSlot = FACEPLATE_HEIGHT - 26;
  const drawnHeight = stackRows > 4 ? Math.round((stackRows / 4) * chassisSlot) : chassisSlot;

  return (
    <div ref={wrapRef} className={`relative w-full min-w-0 ${className}`} style={stackRows > 4 ? { height: chassisSlot, overflowY: 'auto' } : undefined}>
      <div className="w-full min-w-0">
        <svg
          viewBox={`0 0 ${vbW} ${vbH}`}
          role="group"
          aria-label={`${device.role} faceplate, ${ports.length} ports: ${summary}${snmpHint ? `. ${snmpHint}` : ''}. Use Tab to move between ports and Enter to open the port graph.`}
          className={`block min-w-0 w-full ${compact ? 'max-h-24' : ''}`}
          style={compact ? undefined : device.form_factor === 'ceiling-ap' ? { aspectRatio: `${CHASSIS_WIDTH} / ${FACEPLATE_HEIGHT}`, width: '100%' } : { width: '100%', height: drawnHeight }}
          preserveAspectRatio="xMinYMid meet"
        >
          <FaceplateDefs uid={uid} />
          {body}
        </svg>
      </div>
      {hover && <PortTooltip port={hover.port} left={hover.left} top={hover.top} />}
      {radioHover && <RadioTooltip radio={radioHover.radio} left={radioHover.left} top={radioHover.top} />}
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