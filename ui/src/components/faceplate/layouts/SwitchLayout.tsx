'use client';

import React from 'react';
import type { PortInfo } from '@/lib/types';
import ChassisBody from '../Chassis';
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
  modelLabel?: string;
  ledHealth?: string;
  canvasWidth?: number;
}

// Cable ports sit in two rows, odd above even, the way a switch face is built.
// Height includes the port numbers above the top row and below the bottom row.
export const SW_H = 124;
const START_X = 86;
const PITCH = 28;
const GROUP_GAP = 10;
const TOP_Y = 16;
const BOTTOM_Y = 70;

const CABLE_TYPES = new Set(['RJ45', 'SFP', 'SFP+', 'QSFP', 'MGMT']);

// Jacks grow with the stretched chassis, and stop before the two rows or the silk overlap.
const PORT_MAX = 32;
const FIBER_COL = 42;

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
  const groups = Math.ceil(cols / 6);
  return START_X + cols * PITCH + Math.max(0, groups - 1) * GROUP_GAP + 48;
}

export function switchCanvas(ports: PortInfo[]) {
  const laid = cablePorts(ports);
  const copper = laid.filter((port) => !isFiber(port));
  const fiber = laid.filter(isFiber);
  const cols = Math.max(1, Math.ceil(copper.length / 2));
  const groups = Math.ceil(cols / 6);
  const fiberCols = Math.max(1, Math.ceil(fiber.length / 2));
  const fiberW = fiber.length ? fiberCols * FIBER_COL + 12 : 8;
  const width = START_X + cols * PITCH + Math.max(0, groups - 1) * GROUP_GAP + fiberW + 8;
  return { width, height: SW_H, cols, groups, fiberCols, fiberW, copper, fiber };
}

function isFiber(port: PortInfo): boolean {
  return port.type === 'SFP' || port.type === 'SFP+' || port.type === 'QSFP';
}

function ledFill(health: string | undefined): string {
  if (health === 'critical' || health === 'unreachable' || health === 'fault') return '#ef4444';
  if (health === 'warning') return '#f59e0b';
  if (health === 'healthy') return '#22c55e';
  return '#94a3b8';
}

export default function SwitchLayout({ ports, uid, selectedId, onHover, onSelect, originX = 0, originY = 0, memberNumber, memberHealthColor, modelLabel, ledHealth, canvasWidth }: SwitchProps) {
  const canvas = switchCanvas(ports);
  const { copper, fiber, cols, fiberCols, fiberW } = canvas;
  const W = canvasWidth && canvasWidth > canvas.width ? canvasWidth : canvas.width;
  const usable = Math.max(PITCH, W - START_X - fiberW - GROUP_GAP * Math.max(0, canvas.groups - 1));
  const pitch = usable / cols;
  const glyph = Math.min(PORT_MAX, Math.max(11, pitch - 8));
  const fiberSize = Math.min(glyph, (FIBER_COL - 6) / 1.25);
  const colX = (c: number) => START_X + c * pitch + Math.floor(c / 6) * GROUP_GAP + Math.max(0, (pitch - glyph) / 2);
  const led = ledFill(ledHealth);
  const accent = memberHealthColor || led;

  return (
    <g transform={`translate(${originX} ${originY})`}>
      <ChassisBody x={0} y={0} w={W} h={SW_H} uid={`${uid}-${memberNumber || 'sw'}`} charcoal ears={false}>
        <g aria-hidden="true">
          {['SYS', 'RPS', 'STAT', 'MST'].map((label, index) => (
            <g key={label} transform={`translate(${8 + index * 18} 8)`}>
              <circle data-led={label} cx={5} cy={4} r={2.3} fill={led} />
              <text x={5} y={13} textAnchor="middle" fontSize={4.2} fill="#94a3b8" fontFamily="var(--font-mono)">{label}</text>
            </g>
          ))}
          <rect x={8} y={20} width={28} height={8} rx={1.5} fill="#0b1016" stroke="#9aa6b5" strokeWidth={0.6} />
          <text x={22} y={26} textAnchor="middle" fontSize={3.6} fill="#94a3b8" fontFamily="var(--font-mono)">CON</text>
          <rect x={40} y={20} width={16} height={8} rx={1.5} fill="#0b1016" stroke="#9aa6b5" strokeWidth={0.6} />
          <text x={48} y={26} textAnchor="middle" fontSize={3.4} fill="#94a3b8" fontFamily="var(--font-mono)">USB</text>
          <rect x={60} y={18} width={12} height={10} rx={1.2} fill="#0b1016" stroke="#9aa6b5" strokeWidth={0.7} />
          <text x={66} y={34} textAnchor="middle" fontSize={3.4} fill="#94a3b8" fontFamily="var(--font-mono)">MGMT</text>
        </g>
        {memberNumber ? (
          <g aria-label={`Stack member ${memberNumber}`}>
            <rect x={8} y={40} width={18} height={16} rx={4} fill={accent} opacity={0.9} />
            <text x={17} y={51} textAnchor="middle" fontSize={8} fontWeight={700} fill="#0f172a" fontFamily="var(--font-mono)">
              {String(memberNumber).padStart(2, '0')}
            </text>
          </g>
        ) : null}
        <text x={8} y={SW_H - 6} fontSize={6} fill="#94a3b8" fontFamily="var(--font-mono)">
          {modelLabel || ''}
        </text>

        {Array.from({ length: cols }, (_, c) => {
          const top = copper[c * 2];
          const bottom = copper[c * 2 + 1];
          return (
            <React.Fragment key={`${uid}-col-${c + 1}`}>
              {top && (
                <PortGlyph port={top} x={colX(c)} y={TOP_Y} size={glyph} uid={uid} selected={selectedId === top.id} onHover={onHover} onSelect={onSelect} silk={silkLabel(top.name)} />
              )}
              {bottom && (
                <PortGlyph port={bottom} x={colX(c)} y={BOTTOM_Y} size={glyph} uid={uid} selected={selectedId === bottom.id} onHover={onHover} onSelect={onSelect} silk={silkLabel(bottom.name)} silkBelow />
              )}
            </React.Fragment>
          );
        })}

        {fiber.map((port, index) => {
          const column = index % fiberCols;
          const row = Math.floor(index / fiberCols);
          const x = W - fiberW + 6 + column * FIBER_COL;
          const y = row === 0 ? TOP_Y : BOTTOM_Y;
          return (
            <PortGlyph
              key={port.id}
              port={port}
              x={x}
              y={y}
              size={fiberSize}
              uid={uid}
              selected={selectedId === port.id}
              onHover={onHover}
              onSelect={onSelect}
              silk={silkLabel(port.name)}
              silkBelow={row > 0}
            />
          );
        })}
      </ChassisBody>
    </g>
  );
}