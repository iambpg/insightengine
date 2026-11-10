'use client';

import React from 'react';
import type { PortInfo } from '@/lib/types';
import ChassisBody, { EngravedText, StatusLeds, VentGrille } from '../Chassis';
import PortGlyph from '../Port';

export interface LayoutCommon {
  uid: string;
  selectedId: string | null;
  onHover: (p: PortInfo | null, el: SVGGElement | null) => void;
  onSelect: (p: PortInfo) => void;
}

interface SwitchProps extends LayoutCommon {
  ports: PortInfo[];
  originX?: number;
  originY?: number;
  memberNumber?: number;
  memberHealthColor?: string;
  stackPorts?: boolean;
}

// Cable ports sit in two rows, odd above even, the way a switch face is built.
export const SW_H = 96;

const CABLE_TYPES = new Set(['RJ45', 'SFP', 'SFP+', 'QSFP', 'MGMT']);

function portNumbers(name: string): number[] {
  const found = name.match(/\d+/g);
  return found ? found.map((part) => Number(part)) : [];
}

export function cablePorts(ports: PortInfo[]): PortInfo[] {
  const copper = ports.filter((port) => port.type === 'RJ45' || port.type === 'MGMT');
  const fiber = ports.filter((port) => port.type === 'SFP' || port.type === 'SFP+' || port.type === 'QSFP');
  const rest = ports.filter((port) => !CABLE_TYPES.has(port.type) && port.type !== 'CONSOLE' && port.type !== 'USB');
  const ordered = [...copper, ...fiber, ...rest];
  return ordered.sort((left, right) => {
    const a = portNumbers(left.name);
    const b = portNumbers(right.name);
    const length = Math.max(a.length, b.length);
    for (let index = 0; index < length; index += 1) {
      const delta = (a[index] ?? -1) - (b[index] ?? -1);
      if (delta) return delta;
    }
    return left.name.localeCompare(right.name);
  });
}

export function switchWidth(portCount: number) {
  const cols = Math.max(1, Math.ceil(portCount / 2));
  const groups = Math.ceil(cols / 4);
  return 150 + cols * 24 + Math.max(0, groups - 1) * 6 + 48;
}

export default function SwitchLayout({ ports, uid, selectedId, onHover, onSelect, originX = 0, originY = 0, memberNumber, memberHealthColor, stackPorts }: SwitchProps) {
  const laid = cablePorts(ports);
  const cols = Math.max(1, Math.ceil(laid.length / 2));
  const W = switchWidth(laid.length);
  const startX = 74;

  const colX = (c: number) => startX + c * 24 + Math.floor(c / 4) * 6;

  const anyFault = ports.some((p) => p.state === 'fault');
  const anyWarn = ports.some((p) => p.state === 'warning');

  return (
    <g transform={`translate(${originX} ${originY})`}>
      <ChassisBody x={0} y={0} w={W} h={SW_H} uid={uid}>
        {/* left: vent, LEDs, console, number */}
        <VentGrille x={10} y={10} w={14} h={30} uid={uid} />
        <rect x={10} y={48} width={16} height={9} rx={1.5} fill="var(--navy)" stroke="var(--metal-hi)" strokeWidth={0.6} />
        <EngravedText x={10} y={66} size={5}>CONSOLE</EngravedText>
        {memberNumber ? (
          <g aria-label={`Stack member ${memberNumber}`}>
            <rect x={10} y={72} width={16} height={14} rx={2} fill="var(--navy)" stroke={memberHealthColor ?? 'var(--success)'} strokeWidth={1.2} />
            <text x={18} y={83} textAnchor="middle" fontSize={10} fontWeight={700} fill={memberHealthColor ?? 'var(--success)'} fontFamily="var(--font-mono)">
              {memberNumber}
            </text>
          </g>
        ) : null}
        <StatusLeds
          x={34}
          y={12}
          uid={uid}
          items={[
            { label: 'SYS', color: anyFault ? 'var(--destructive)' : anyWarn ? 'var(--warning)' : 'var(--success)', blink: anyWarn && !anyFault },
            { label: 'PWR', color: 'var(--success)' },
            { label: 'STK', color: stackPorts ? 'var(--teal)' : 'var(--down)' },
            { label: 'POE', color: laid.some((p) => p.poe) ? 'var(--success)' : 'var(--down)' },
          ]}
        />
        <EngravedText x={34} y={SW_H - 8} size={4.8}>{memberNumber ? `MEMBER ${memberNumber}` : 'ACCESS SWITCH'}</EngravedText>

        {/* Two rows: port 1 above port 2, then the next pair, including fiber on the same baselines. */}
        {Array.from({ length: cols }, (_, c) => {
          const top = laid[c * 2];
          const bottom = laid[c * 2 + 1];
          return (
            <React.Fragment key={`${uid}-col-${c + 1}`}>
              {top && (
                <PortGlyph port={top} x={colX(c)} y={20} size={19} uid={uid} selected={selectedId === top.id} onHover={onHover} onSelect={onSelect} />
              )}
              {bottom && (
                <PortGlyph port={bottom} x={colX(c)} y={52} size={19} uid={uid} selected={selectedId === bottom.id} onHover={onHover} onSelect={onSelect} />
              )}
              <text x={colX(c) + 9.5} y={14} textAnchor="middle" fontSize={5} fill="var(--down)" fontFamily="var(--font-mono)" aria-hidden="true">
                {c * 2 + 1}
              </text>
              <text x={colX(c) + 9.5} y={SW_H - 8} textAnchor="middle" fontSize={5} fill="var(--down)" fontFamily="var(--font-mono)" aria-hidden="true">
                {bottom ? c * 2 + 2 : ''}
              </text>
            </React.Fragment>
          );
        })}

        {/* stack ports: two cages on the right edge (STACK 1 top, STACK 2 bottom) */}
        {stackPorts && (
          <g aria-hidden="true">
            <line x1={W - 40} y1={14} x2={W - 40} y2={SW_H - 14} stroke="var(--metal-hi)" strokeOpacity={0.5} />
            <EngravedText x={W - 34} y={14} size={5}>STACK</EngravedText>
            {[0, 1].map((k) => (
              <g key={`${uid}-stk-${k}`} transform={`translate(${W - 34} ${22 + k * 32})`}>
                <rect width={22} height={22} rx={2.5} fill="var(--navy)" stroke="var(--metal-hi)" strokeWidth={0.8} />
                <rect x={3} y={3} width={16} height={16} rx={1.5} fill="#05080f" stroke="var(--teal)" strokeWidth={0.9} />
                <rect x={6} y={7} width={10} height={8} rx={1} fill="var(--teal)" opacity={0.35} />
                <circle cx={19} cy={3} r={1.6} fill="var(--teal)" filter={`url(#${uid}-glow)`} />
              </g>
            ))}
          </g>
        )}
      </ChassisBody>
    </g>
  );
}