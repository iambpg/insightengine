'use client';

import React from 'react';
import type { PortInfo } from '@/lib/types';
import ChassisBody, { EngravedText, StatusLeds, VentGrille } from '../Chassis';
import PortGlyph from '../Port';
import { lockedChassis } from '../size';

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

/** The number printed on the jack: Gi0/1, Fa0/1 and Gi1/0/1 are all face port 1. */
export function faceNumber(name: string): number | null {
  const found = name.match(/\d+/g);
  if (!found?.length) return null;
  return Number(found[found.length - 1]);
}

/** Uplink cages named like Te1/1/1 through Te1/1/4. They are not access port 1. */
const UPLINK_END = /(\d+)\/1\/([1-4])$/;

export function uplinkEnd(name: string): { member: number; port: number } | null {
  const match = name.trim().match(UPLINK_END);
  if (!match) return null;
  return { member: Number(match[1]), port: Number(match[2]) };
}

export function silkLabel(name: string): string {
  const uplink = uplinkEnd(name);
  if (uplink) return `${uplink.member}/1/${uplink.port}`;
  const number = faceNumber(name);
  return number == null ? '' : String(number);
}

function byFace(left: PortInfo, right: PortInfo): number {
  const a = faceNumber(left.name);
  const b = faceNumber(right.name);
  if (a === 0 && b !== 0) return 1;
  if (b === 0 && a !== 0) return -1;
  if (a !== b) return (a ?? Number.MAX_SAFE_INTEGER) - (b ?? Number.MAX_SAFE_INTEGER);
  return left.name.localeCompare(right.name);
}

export function cablePorts(ports: PortInfo[]): PortInfo[] {
  const uplinks: PortInfo[] = [];
  const body = ports.filter((port) => {
    if (!uplinkEnd(port.name)) return true;
    uplinks.push(port);
    return false;
  });
  const copper = body.filter((port) => port.type === 'RJ45' || port.type === 'MGMT');
  const fiber = body.filter((port) => port.type === 'SFP' || port.type === 'SFP+' || port.type === 'QSFP');
  const rest = body.filter((port) => !CABLE_TYPES.has(port.type) && port.type !== 'CONSOLE' && port.type !== 'USB');
  const zeros: PortInfo[] = [];
  const keep = (list: PortInfo[]) => {
    const numbered: PortInfo[] = [];
    for (const port of list) {
      if (faceNumber(port.name) === 0) zeros.push(port);
      else numbered.push(port);
    }
    return numbered.sort(byFace);
  };
  uplinks.sort((left, right) => {
    const a = uplinkEnd(left.name)!;
    const b = uplinkEnd(right.name)!;
    if (a.member !== b.member) return a.member - b.member;
    return a.port - b.port;
  });
  return [...keep(copper), ...keep(fiber), ...keep(rest), ...zeros.sort(byFace), ...uplinks];
}

export function switchWidth(portCount: number) {
  const cols = Math.max(1, Math.ceil(portCount / 2));
  const groups = Math.ceil(cols / 4);
  return 150 + cols * 24 + Math.max(0, groups - 1) * 6 + 48;
}

export default function SwitchLayout({ ports, uid, selectedId, onHover, onSelect, originX = 0, originY = 0, memberNumber, memberHealthColor, stackPorts }: SwitchProps) {
  const laid = cablePorts(ports);
  const cols = Math.max(1, Math.ceil(laid.length / 2));
  const W = lockedChassis().innerW;
  const startX = 74;
  const right = stackPorts ? 78 : 28;
  const usable = Math.max(22, W - startX - right);
  const pitch = usable / cols;
  const glyph = Math.min(19, Math.max(12, pitch - 5));
  const colX = (c: number) => startX + c * pitch + Math.max(0, (pitch - glyph) / 2);

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
                <PortGlyph port={top} x={colX(c)} y={20} size={glyph} uid={uid} selected={selectedId === top.id} onHover={onHover} onSelect={onSelect} silk={silkLabel(top.name)} />
              )}
              {bottom && (
                <PortGlyph port={bottom} x={colX(c)} y={52} size={glyph} uid={uid} selected={selectedId === bottom.id} onHover={onHover} onSelect={onSelect} silk={silkLabel(bottom.name)} silkBelow />
              )}
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