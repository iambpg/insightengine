'use client';

import React from 'react';
import type { PortInfo } from '@/lib/types';
import ChassisBody, { EngravedText, StatusLeds, VentGrille } from '../Chassis';
import PortGlyph from '../Port';
import type { LayoutCommon } from './SwitchLayout';

export interface FwModelSpec {
  id: string;
  vendor: 'fortigate' | 'paloalto';
  label: string;
  desktop: boolean;
  rj45: number;
  sfp: number;
  sfpPlus: number;
  qsfp: number;
  mgmt: boolean;
  ha: boolean;
  console: boolean;
  usb: number;
  psu: 1 | 2;
  rjRows: 1 | 2;
}

const S = (
  id: string, vendor: FwModelSpec['vendor'], label: string, desktop: boolean, rj45: number, sfp: number, sfpPlus: number, qsfp: number,
  mgmt: boolean, ha: boolean, usb: number, psu: 1 | 2, rjRows: 1 | 2 = 1,
): FwModelSpec => ({ id, vendor, label, desktop, rj45, sfp, sfpPlus, qsfp, mgmt, ha, console: true, usb, psu, rjRows });

export const FW_MODELS: Record<string, FwModelSpec> = {
  'fg-40f': S('fg-40f', 'fortigate', 'FortiGate 40F', true, 5, 0, 0, 0, false, false, 1, 1),
  'fg-60e': S('fg-60e', 'fortigate', 'FortiGate 60E', true, 10, 0, 0, 0, false, false, 1, 1, 2),
  'fg-60f': S('fg-60f', 'fortigate', 'FortiGate 60F', true, 10, 0, 0, 0, false, false, 1, 1, 2),
  'fg-80f': S('fg-80f', 'fortigate', 'FortiGate 80F', true, 8, 2, 0, 0, false, false, 1, 1, 2),
  'fg-100f': S('fg-100f', 'fortigate', 'FortiGate 100F', false, 16, 0, 4, 0, true, true, 1, 1, 2),
  'fg-200f': S('fg-200f', 'fortigate', 'FortiGate 200F', false, 16, 8, 0, 0, true, true, 1, 2, 2),
  'fg-400e': S('fg-400e', 'fortigate', 'FortiGate 400E', false, 16, 0, 8, 0, true, true, 2, 2, 2),
  'fg-600e': S('fg-600e', 'fortigate', 'FortiGate 600E', false, 16, 0, 8, 0, true, true, 2, 2, 2),
  'fg-1200d': S('fg-1200d', 'fortigate', 'FortiGate 1200D', false, 16, 16, 0, 0, true, true, 2, 2, 2),
  'fg-1800f': S('fg-1800f', 'fortigate', 'FortiGate 1800F', false, 0, 0, 16, 4, true, true, 2, 2),
  'pa-220': S('pa-220', 'paloalto', 'PA-220', true, 8, 0, 0, 0, true, false, 1, 1, 2),
  'pa-440': S('pa-440', 'paloalto', 'PA-440', true, 8, 0, 0, 0, true, false, 1, 1, 2),
  'pa-820': S('pa-820', 'paloalto', 'PA-820', false, 8, 4, 0, 0, true, true, 1, 1, 2),
  'pa-850': S('pa-850', 'paloalto', 'PA-850', false, 4, 8, 4, 0, true, true, 1, 2, 2),
  'pa-3220': S('pa-3220', 'paloalto', 'PA-3220', false, 12, 0, 4, 0, true, true, 1, 2, 2),
  'pa-5220': S('pa-5220', 'paloalto', 'PA-5220', false, 4, 0, 16, 4, true, true, 1, 2),
};

export const FW_MODEL_LIST = Object.values(FW_MODELS);

interface Props extends LayoutCommon {
  ports: PortInfo[];
  model: string;
}

// ---- grid constants: every port sits in a fixed cell so nothing can overlap ----
const GAP = 9; // clear space between neighbouring ports in a row
const ROW_GAP = 40; // vertical distance between row 1 and row 2 (port + state glyph + label)
const Y0 = 16; // baseline of row 1
const LEFT = 74; // where the first port column starts (after LEDs / console)
const BLOCK_GAP = 22; // space between port groups (divider sits in the middle)
const H_DESK = 96;
const H_RACK = 104;
const PSU_W = 78;
const PSU_GAP = 8;
export const FWM_W = 880;
const DESK_W = 440;

export function fwModelHeight(model: string): number {
  return (FW_MODELS[model]?.desktop ? H_DESK : H_RACK) + 8;
}

export function fwModelWidth(model: string): number {
  return FW_MODELS[model]?.desktop ? DESK_W : FWM_W;
}

// Draws one firewall appliance from its spec. Pure artwork: no logos, no brand names.
// Layout rule: ports are placed block by block left to right with a running cursor. Each block
// reserves its full width (cell pitch x columns) before the next block starts, and every block
// shares the same two row baselines, so ports line up in clean rows and can never hide under each other.
export default function FirewallModelLayout({ ports, model, uid, selectedId, onHover, onSelect }: Props) {
  const spec = FW_MODELS[model] ?? FW_MODELS['fg-60e'];
  const h = spec.desktop ? H_DESK : H_RACK;
  const w = fwModelWidth(model);

  const rj = ports.filter((p) => p.type === 'RJ45' && p.name.startsWith('port'));
  const sfp = ports.filter((p) => p.type === 'SFP');
  const sfpp = ports.filter((p) => p.type === 'SFP+');
  const qsfp = ports.filter((p) => p.type === 'QSFP');
  const mgmt = ports.filter((p) => p.type === 'MGMT');
  const ha = ports.filter((p) => p.name === 'HA');
  const anyFault = ports.some((p) => p.state === 'fault');
  const anyWarn = ports.some((p) => p.state === 'warning');

  const common = { uid, onHover, onSelect };
  const sel = (p: PortInfo) => selectedId === p.id;
  const nodes: React.ReactNode[] = [];
  const dividers: number[] = [];

  let cursor = LEFT;

  // Places a block of ports in a column-major grid (odd numbers on the top row, even below).
  // Returns nothing; advances the shared cursor by the exact width the block used.
  const placeBlock = (
    list: PortInfo[],
    size: number,
    fiber: boolean,
    rows: 1 | 2,
    label: (p: PortInfo, i: number) => string,
  ) => {
    if (list.length === 0) return;
    const cellW = (fiber ? size * 1.15 : size) + GAP;
    const cols = Math.ceil(list.length / rows);
    list.forEach((p, i) => {
      const col = rows === 2 ? Math.floor(i / 2) : i;
      const row = rows === 2 ? i % 2 : 0;
      nodes.push(
        <PortGlyph
          key={p.id}
          port={p}
          x={cursor + col * cellW}
          y={Y0 + row * ROW_GAP}
          size={size}
          selected={sel(p)}
          showLabel
          labelBelow
          labelText={label(p, i)}
          {...common}
        />,
      );
    });
    cursor += cols * cellW - GAP;
  };

  const startGroup = (hasPrev: boolean) => {
    if (hasPrev) {
      cursor += BLOCK_GAP / 2;
      dividers.push(cursor);
      cursor += BLOCK_GAP / 2;
    }
  };

  // 1. copper block
  placeBlock(rj, 20, false, spec.rjRows, (_, i) => String(i + 1));

  // 2. fiber blocks. Always two rows when the chassis has two rows so they sit on the same baselines as copper.
  const fiberRows: 1 | 2 = spec.rjRows === 2 || !spec.desktop ? 2 : 1;
  let placed = rj.length > 0;
  if (sfp.length > 0) {
    startGroup(placed);
    placeBlock(sfp, 20, true, fiberRows, (_, i) => `S${i + 1}`);
    placed = true;
  }
  if (sfpp.length > 0) {
    startGroup(placed);
    placeBlock(sfpp, 20, true, fiberRows, (_, i) => `X${i + 1}`);
    placed = true;
  }
  if (qsfp.length > 0) {
    startGroup(placed);
    placeBlock(qsfp, 24, true, fiberRows, (_, i) => `Q${i + 1}`);
    placed = true;
  }

  // 3. management: MGMT on row 1, HA on row 2, same column so they stack neatly
  if (mgmt.length + ha.length > 0) {
    startGroup(placed);
    const cellW = 20 + GAP;
    mgmt.forEach((p, i) => {
      nodes.push(
        <PortGlyph key={p.id} port={p} x={cursor + i * cellW} y={Y0} size={20} selected={sel(p)} showLabel labelBelow labelText="MGMT" {...common} />,
      );
    });
    ha.forEach((p, i) => {
      nodes.push(
        <PortGlyph key={p.id} port={p} x={cursor + i * cellW} y={Y0 + ROW_GAP} size={20} selected={sel(p)} showLabel labelBelow labelText="HA" {...common} />,
      );
    });
    cursor += Math.max(mgmt.length, ha.length, 1) * cellW - GAP;
    placed = true;
  }

  const portsEnd = cursor;

  // 4. right-hand hardware (PSUs / vent), sized from the space that is actually left
  const psuCount = spec.desktop ? 0 : spec.psu;
  const psuBlockW = psuCount * PSU_W + Math.max(0, psuCount - 1) * PSU_GAP;
  const psuX0 = w - 14 - psuBlockW;
  const ventX = portsEnd + 20;
  const ventRight = (psuCount > 0 ? psuX0 : w - 14) - 10;
  const ventW = ventRight - ventX;

  return (
    <ChassisBody x={0} y={0} w={w} h={h} uid={uid} ears={!spec.desktop}>
      <StatusLeds
        x={12}
        y={10}
        uid={uid}
        items={[
          { label: 'PWR', color: 'var(--success)' },
          { label: 'STS', color: anyFault ? 'var(--destructive)' : anyWarn ? 'var(--warning)' : 'var(--success)', blink: anyFault },
          ...(spec.ha ? [{ label: 'HA', color: 'var(--teal)' }] : []),
        ]}
      />
      {/* console + usb */}
      <g transform={`translate(12 ${h - 28})`} aria-hidden="true">
        <rect width={14} height={8} rx={1.5} fill="var(--navy)" stroke="var(--metal-hi)" strokeWidth={0.6} />
        <EngravedText x={0} y={16} size={4.6}>CON</EngravedText>
        {Array.from({ length: spec.usb }, (_, i) => (
          <rect key={`usb-${i + 1}`} x={22 + i * 14} y={0} width={10} height={8} rx={1} fill="var(--navy)" stroke="var(--metal-hi)" strokeWidth={0.6} />
        ))}
        {spec.usb > 0 && <EngravedText x={22} y={16} size={4.6}>USB</EngravedText>}
      </g>

      {dividers.map((x) => (
        <line key={`div-${x}`} x1={x} y1={10} x2={x} y2={h - 10} stroke="var(--metal-hi)" strokeOpacity={0.5} />
      ))}

      {nodes}

      {ventW >= 24 && (
        <VentGrille x={ventX} y={12} w={ventW} h={h - 24} uid={uid} />
      )}

      {Array.from({ length: psuCount }, (_, n) => (
        <g key={`psu-${n + 1}`} transform={`translate(${psuX0 + n * (PSU_W + PSU_GAP)} 12)`} aria-hidden="true">
          <rect width={PSU_W} height={h - 24} rx={3} fill="var(--navy)" stroke="var(--metal-hi)" strokeOpacity={0.6} />
          <rect x={8} y={8} width={46} height={h - 40} rx={2} fill="var(--metal-3)" />
          {Array.from({ length: 5 }, (_, k) => (
            <rect key={`psu-${n}-s-${k + 1}`} x={11 + k * 8} y={11} width={4} height={h - 46} fill="var(--navy)" />
          ))}
          <circle cx={66} cy={14} r={3} fill="var(--success)" filter={`url(#${uid}-glow)`} />
          <text x={39} y={h - 28} textAnchor="middle" fontSize={5} fill="var(--down)" fontFamily="var(--font-mono)">{`PSU${n + 1}`}</text>
        </g>
      ))}
    </ChassisBody>
  );
}
