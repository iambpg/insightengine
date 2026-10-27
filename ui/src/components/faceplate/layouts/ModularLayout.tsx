'use client';

import React from 'react';
import type { ChassisModule } from '@/lib/types';
import { STATE_COLOR } from '../palette';
import PortGlyph from '../Port';
import type { LayoutCommon } from './SwitchLayout';

interface Props extends LayoutCommon {
  modules: ChassisModule[];
}

export const CH_W = 980;
const ROW_H = 44;

function rowHeight(m: ChassisModule) {
  if (m.kind === 'fan') return 24;
  if (m.kind === 'psu') return 0;
  return ROW_H;
}

export function chassisHeight(modules: ChassisModule[]) {
  const body = modules.filter((m) => m.kind !== 'psu').reduce((s, m) => s + rowHeight(m) + 6, 0);
  return body + 66;
}

// Modular chassis: fan trays, supervisors, line cards with dense port rows, and PSU bays at the bottom.
export default function ModularLayout({ modules, uid, selectedId, onHover, onSelect }: Props) {
  const rows = modules.filter((m) => m.kind !== 'psu');
  const psus = modules.filter((m) => m.kind === 'psu');
  let y = 14;
  const H = chassisHeight(modules);

  return (
    <g>
      <g filter={`url(#${uid}-shadow)`}>
        <rect width={CH_W} height={H} rx={6} fill={`url(#${uid}-metal)`} />
      </g>
      <rect width={CH_W} height={H} rx={6} fill={`url(#${uid}-brush)`} />
      <rect x={0.5} y={0.5} width={CH_W - 1} height={H - 1} rx={6} fill="none" stroke="var(--metal-hi)" strokeOpacity={0.6} />
      <rect x={-6} y={H * 0.15} width={8} height={H * 0.7} rx={2} fill={`url(#${uid}-plate)`} />
      <rect x={CH_W - 2} y={H * 0.15} width={8} height={H * 0.7} rx={2} fill={`url(#${uid}-plate)`} />

      {rows.map((m) => {
        const top = y;
        const h = rowHeight(m);
        y += h + 6;
        const sc = STATE_COLOR[m.state];
        if (m.kind === 'fan') {
          return (
            <g key={m.id} transform={`translate(14 ${top})`} role="img" aria-label={`${m.label}, ${m.state === 'up' ? 'running' : m.state}`}>
              <rect width={CH_W - 28} height={h} rx={3} fill="var(--navy)" stroke="var(--metal-hi)" strokeOpacity={0.4} />
              <circle cx={12} cy={h / 2} r={2.6} fill={sc.fill} filter={`url(#${uid}-glow)`} />
              <text x={22} y={h / 2 + 2.2} fontSize={5.6} fill="var(--down)" fontFamily="var(--font-mono)">{m.label.toUpperCase()}</text>
              {Array.from({ length: 6 }, (_, i) => (
                <g key={`${m.id}-fan-${i + 1}`} transform={`translate(${130 + i * 140} ${h / 2})`}>
                  <circle r={9} fill="var(--metal-3)" stroke="var(--metal-hi)" strokeOpacity={0.5} />
                  {[0, 90, 180, 270].map((a) => (
                    <path key={`${m.id}-${i}-b-${a}`} d="M0 0 L0 -7 A7 7 0 0 1 5 -5 Z" fill="var(--metal-1)" transform={`rotate(${a})`} />
                  ))}
                </g>
              ))}
            </g>
          );
        }
        const isSup = m.kind === 'supervisor';
        const copper = m.ports.filter((p) => p.type === 'RJ45');
        const cols = Math.ceil(copper.length / 2);
        return (
          <g key={m.id} transform={`translate(14 ${top})`}>
            <rect width={CH_W - 28} height={h} rx={3} fill={`url(#${uid}-bay)`} stroke={m.state === 'fault' ? 'var(--destructive)' : m.state === 'warning' ? 'var(--warning)' : 'var(--metal-hi)'} strokeOpacity={m.state === 'up' ? 0.4 : 0.95} strokeWidth={m.state === 'up' ? 0.8 : 1.5} />
            <text x={8} y={13} fontSize={6.4} fontWeight={700} fill="var(--down)" fontFamily="var(--font-mono)">{`SLOT ${m.slot}`}</text>
            <text x={8} y={22} fontSize={4.8} fill="var(--down)" fontFamily="var(--font-mono)">{m.label.toUpperCase()}</text>
            <circle cx={12} cy={31} r={2.2} fill={sc.fill} filter={`url(#${uid}-glow)`} className={m.state === 'warning' ? 'led-warn-blink' : m.state === 'fault' ? 'led-fault-blink' : undefined} />
            <text x={18} y={33} fontSize={4.8} fill={sc.fill} fontFamily="var(--font-mono)">{m.state === 'up' ? 'OK' : m.state === 'warning' ? 'WARN' : 'FAULT'}</text>
            {isSup ? (
              <>
                {m.ports.map((p, i) => (
                  <PortGlyph key={p.id} port={p} x={110 + i * 42} y={7} size={22} uid={uid} selected={selectedId === p.id} onHover={onHover} onSelect={onSelect} />
                ))}
                <rect x={300} y={6} width={CH_W - 28 - 310} height={h - 12} rx={2} fill={`url(#${uid}-vent)`} stroke="var(--metal-hi)" strokeOpacity={0.4} aria-hidden="true" />
              </>
            ) : (
              copper.map((p, i) => {
                const col = Math.floor(i / 2);
                const row = i % 2;
                return (
                  <PortGlyph
                    key={p.id}
                    port={p}
                    x={86 + col * 18.5 + Math.floor(col / 6) * 5}
                    y={5 + row * 17}
                    size={13}
                    uid={uid}
                    selected={selectedId === p.id}
                    onHover={onHover}
                    onSelect={onSelect}
                  />
                );
              })
            )}
            {!isSup && <text x={CH_W - 28 - 8} y={h - 4} textAnchor="end" fontSize={4.6} fill="var(--down)" fontFamily="var(--font-mono)" aria-hidden="true">{`${cols * 2} PORTS`}</text>}
          </g>
        );
      })}

      {/* PSU bays */}
      <g transform={`translate(14 ${H - 50})`}>
        {psus.map((m, i) => {
          const sc = STATE_COLOR[m.state];
          return (
            <g key={m.id} transform={`translate(${i * 236} 0)`} role="img" aria-label={`${m.label}, ${m.state === 'up' ? 'ok' : m.state}`}>
              <rect width={226} height={40} rx={3} fill="var(--navy)" stroke={m.state === 'warning' ? 'var(--warning)' : 'var(--metal-hi)'} strokeOpacity={m.state === 'warning' ? 1 : 0.5} strokeWidth={m.state === 'warning' ? 1.6 : 0.8} />
              <rect x={10} y={8} width={150} height={24} rx={2} fill="var(--metal-3)" />
              {Array.from({ length: 12 }, (_, k) => (
                <rect key={`${m.id}-v-${k + 1}`} x={14 + k * 12} y={11} width={6} height={18} fill="var(--navy)" />
              ))}
              <circle cx={176} cy={14} r={3} fill={sc.fill} filter={`url(#${uid}-glow)`} className={m.state === 'warning' ? 'led-warn-blink' : undefined} />
              <text x={170} y={30} fontSize={5.4} fill={sc.fill} fontFamily="var(--font-mono)">{`${m.state === 'up' ? '● ' : '▲ '}${m.slot}`}</text>
              <rect x={196} y={10} width={22} height={20} rx={2} fill="var(--metal-2)" stroke="var(--metal-hi)" strokeOpacity={0.5} />
            </g>
          );
        })}
      </g>
    </g>
  );
}