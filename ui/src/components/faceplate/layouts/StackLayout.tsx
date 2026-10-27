'use client';

import React from 'react';
import type { StackMember } from '@/lib/types';
import SwitchLayout, { SW_H, switchWidth, type LayoutCommon } from './SwitchLayout';

interface StackProps extends LayoutCommon {
  members: StackMember[];
}

const GAP = 26;

const HEALTH_COLOR = {
  healthy: 'var(--success)',
  warning: 'var(--warning)',
  fault: 'var(--destructive)',
};

export function stackSize(members: StackMember[]) {
  const w = switchWidth(members[0]?.ports.filter((p) => p.type === 'RJ45').length ?? 24);
  return { w: w + 36, h: members.length * SW_H + (members.length - 1) * GAP + 6 };
}

// One cable: a dark rounded sleeve with a lighter core and two plugs.
function Cable({ d, x1, y1, x2, y2, id }: { d: string; x1: number; y1: number; x2: number; y2: number; id: string }) {
  return (
    <g key={id}>
      <path d={d} fill="none" stroke="#05080f" strokeWidth={6.5} strokeLinecap="round" opacity={0.9} />
      <path d={d} fill="none" stroke="var(--teal)" strokeWidth={3.4} strokeLinecap="round" />
      <path d={d} fill="none" stroke="#ffffff" strokeOpacity={0.35} strokeWidth={0.9} strokeLinecap="round" transform="translate(-0.6 -0.6)" />
      {[
        [x1, y1],
        [x2, y2],
      ].map(([cx, cy], i) => (
        <rect key={`${id}-plug-${i}`} x={cx - 7} y={cy - 4} width={9} height={8} rx={1.5} fill="var(--navy)" stroke="var(--metal-hi)" strokeWidth={0.7} />
      ))}
    </g>
  );
}

export default function StackLayout({ members, uid, selectedId, onHover, onSelect }: StackProps) {
  const copperLen = members[0]?.ports.filter((p) => p.type === 'RJ45').length ?? 24;
  const w = switchWidth(copperLen);
  const rowY = (i: number) => i * (SW_H + GAP);
  // stack-port centres on the right edge of each member
  const topY = (i: number) => rowY(i) + 22 + 11;
  const botY = (i: number) => rowY(i) + 54 + 11;
  const px = w - 34 + 11;

  const cables: React.ReactNode[] = [];
  members.forEach((m, i) => {
    const next = members[i + 1];
    if (!next) return;
    // bottom stack port of member i -> top stack port of member i+1
    const y1 = botY(i);
    const y2 = topY(i + 1);
    const bulge = 18;
    cables.push(
      <Cable
        key={`cable-${m.id}-${next.id}`}
        id={`cable-${m.id}-${next.id}`}
        d={`M ${px} ${y1} C ${px + bulge} ${y1 + 4}, ${px + bulge} ${y2 - 4}, ${px} ${y2}`}
        x1={px + 4}
        y1={y1}
        x2={px + 4}
        y2={y2}
      />
    );
  });
  // return cable: top port of first -> bottom port of last, looped around the outside (ring)
  if (members.length > 2) {
    const last = members.length - 1;
    const y1 = topY(0);
    const y2 = botY(last);
    const out = 40;
    cables.push(
      <Cable
        key="cable-return"
        id="cable-return"
        d={`M ${px} ${y1} C ${px + out} ${y1 - 6}, ${px + out} ${y2 + 6}, ${px} ${y2}`}
        x1={px + 4}
        y1={y1}
        x2={px + 4}
        y2={y2}
      />
    );
  }

  return (
    <g>
      {members.map((m, i) => (
        <SwitchLayout
          key={m.id}
          ports={m.ports}
          uid={`${uid}-m${m.number}`}
          selectedId={selectedId}
          onHover={onHover}
          onSelect={onSelect}
          originY={rowY(i)}
          originX={0}
          memberNumber={m.number}
          memberHealthColor={HEALTH_COLOR[m.health]}
          stackPorts
        />
      ))}
      <g aria-label="Stack cables" role="img">
        {cables}
      </g>
      {/* per-member health call-outs */}
      {members.map((m, i) => (
        <g key={`note-${m.id}`} transform={`translate(0 ${rowY(i) + SW_H + 13})`} aria-hidden="true">
          <text x={0} y={0} fontSize={6.2} fill={HEALTH_COLOR[m.health]} fontFamily="var(--font-mono)">
            {m.health === 'healthy' ? '● ' : m.health === 'warning' ? '▲ ' : '✕ '}
            {`Member ${m.number} · ${m.note}`}
          </text>
        </g>
      ))}
    </g>
  );
}