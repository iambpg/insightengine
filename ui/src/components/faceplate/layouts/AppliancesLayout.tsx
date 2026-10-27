'use client';

import React from 'react';
import type { PortInfo } from '@/lib/types';
import ChassisBody, { EngravedText, StatusLeds, VentGrille } from '../Chassis';
import PortGlyph from '../Port';
import type { LayoutCommon } from './SwitchLayout';

interface Props extends LayoutCommon {
  ports: PortInfo[];
}

export const APPL_H = 96;
export const APPL_W = 760;

// Wireless controller: SFP+ cages, MGMT, redundancy port, dual hot-swap PSU bays.
export function ControllerLayout({ ports, uid, selectedId, onHover, onSelect }: Props) {
  const sfp = ports.filter((p) => p.type === 'SFP+');
  const others = ports.filter((p) => p.type !== 'SFP+');
  const anyWarn = ports.some((p) => p.state === 'warning');
  // SFP+ cages: 24px wide x1.15 = 27.6px, pitch 37px leaves a clean 9px gap. Two rows of four.
  const sfpPitch = 37;
  const sfpRowGap = 40;
  const sfpEnd = 92 + 4 * sfpPitch - 9;
  const divX = sfpEnd + 14;
  return (
    <ChassisBody x={0} y={0} w={APPL_W} h={APPL_H + 10} uid={uid}>
      <VentGrille x={10} y={10} w={14} h={36} uid={uid} />
      <StatusLeds x={32} y={10} uid={uid} items={[{ label: 'SYS', color: anyWarn ? 'var(--warning)' : 'var(--success)', blink: anyWarn }, { label: 'PWR', color: 'var(--success)' }, { label: 'HA', color: 'var(--teal)' }]} />
      <EngravedText x={32} y={APPL_H + 2} size={5}>WIRELESS CONTROLLER</EngravedText>
      {sfp.map((p, i) => (
        <PortGlyph key={p.id} port={p} x={92 + (i % 4) * sfpPitch} y={14 + Math.floor(i / 4) * sfpRowGap} size={24} uid={uid} selected={selectedId === p.id} onHover={onHover} onSelect={onSelect} showLabel labelBelow labelText={String(i + 1)} />
      ))}
      <line x1={divX} y1={12} x2={divX} y2={APPL_H - 2} stroke="var(--metal-hi)" strokeOpacity={0.5} />
      {others.map((p, i) => (
        <PortGlyph key={p.id} port={p} x={divX + 16} y={14 + i * sfpRowGap} size={21} uid={uid} selected={selectedId === p.id} onHover={onHover} onSelect={onSelect} showLabel labelBelow labelText={p.name} />
      ))}
      {/* vented air-intake */}
      <g transform="translate(350 12)" aria-hidden="true">
        <rect width={150} height={APPL_H - 20} rx={3} fill={`url(#${uid}-vent)`} stroke="var(--metal-hi)" strokeOpacity={0.4} />
      </g>
      {/* PSU bays */}
      {[0, 1].map((n) => (
        <g key={`psu-${n}`} transform={`translate(${520 + n * 120} 10)`} role="img" aria-label={`Power supply ${n + 1}${n === 1 ? ' warning' : ' ok'}`}>
          <rect width={110} height={APPL_H - 18} rx={3} fill="var(--navy)" stroke={n === 1 ? 'var(--warning)' : 'var(--metal-hi)'} strokeWidth={n === 1 ? 1.6 : 0.8} />
          <rect x={10} y={10} width={64} height={APPL_H - 40} rx={2} fill="var(--metal-3)" />
          {Array.from({ length: 6 }, (_, k) => (
            <rect key={`psu-${n}-slot-${k + 1}`} x={14 + k * 10} y={14} width={5} height={APPL_H - 48} fill="var(--navy)" />
          ))}
          <circle cx={92} cy={16} r={3} fill={n === 1 ? 'var(--warning)' : 'var(--success)'} filter={`url(#${uid}-glow)`} className={n === 1 ? 'led-warn-blink' : undefined} />
          <text x={92} y={44} textAnchor="middle" fontSize={5.4} fill="var(--down)" fontFamily="var(--font-mono)">{`PSU ${n + 1}`}</text>
        </g>
      ))}
    </ChassisBody>
  );
}

// Firewall: 8x RJ45 (two rows of four), 2x SFP+, MGMT, HA, console/USB, big exhaust grille.
export function FirewallLayout({ ports, uid, selectedId, onHover, onSelect }: Props) {
  const rj = ports.filter((p) => p.type === 'RJ45' && p.name.startsWith('Eth'));
  const sfp = ports.filter((p) => p.type === 'SFP+');
  const mgmt = ports.filter((p) => p.type === 'MGMT' || p.name === 'HA');
  const anyFault = ports.some((p) => p.state === 'fault');
  const rowGap = 40;
  const rjPitch = 30; // 21px port + 9px gap
  const rjCols = Math.ceil(rj.length / 2);
  const rjEnd = 64 + rjCols * rjPitch - 9;
  const div1 = rjEnd + 12;
  const sfpX = div1 + 14;
  const sfpPitch = 37; // 24px x1.15 = 27.6px + 9px gap
  const sfpCols = Math.ceil(sfp.length / 2);
  const sfpEnd = sfpX + sfpCols * sfpPitch - 9;
  const div2 = sfpEnd + 12;
  const mgmtX = div2 + 14;
  const mgmtEnd = mgmtX + 21;
  const ventX = mgmtEnd + 18;
  return (
    <ChassisBody x={0} y={0} w={APPL_W} h={APPL_H + 6} uid={uid}>
      <rect x={14} y={52} width={16} height={9} rx={1.5} fill="var(--navy)" stroke="var(--metal-hi)" strokeWidth={0.6} aria-hidden="true" />
      <EngravedText x={14} y={70} size={5}>CONSOLE</EngravedText>
      <StatusLeds x={14} y={10} uid={uid} items={[{ label: 'SYS', color: anyFault ? 'var(--destructive)' : 'var(--success)', blink: anyFault }, { label: 'ALM', color: anyFault ? 'var(--warning)' : 'var(--down)' }]} />
      {rj.map((p, i) => (
        <PortGlyph key={p.id} port={p} x={64 + Math.floor(i / 2) * rjPitch} y={14 + (i % 2) * rowGap} size={21} uid={uid} selected={selectedId === p.id} onHover={onHover} onSelect={onSelect} showLabel labelBelow labelText={String(i + 1)} />
      ))}
      <line x1={div1} y1={12} x2={div1} y2={APPL_H - 2} stroke="var(--metal-hi)" strokeOpacity={0.5} />
      {sfp.map((p, i) => (
        <PortGlyph key={p.id} port={p} x={sfpX + Math.floor(i / 2) * sfpPitch} y={14 + (i % 2) * rowGap} size={24} uid={uid} selected={selectedId === p.id} onHover={onHover} onSelect={onSelect} showLabel labelBelow labelText={`10G-${i + 1}`} />
      ))}
      <line x1={div2} y1={12} x2={div2} y2={APPL_H - 2} stroke="var(--metal-hi)" strokeOpacity={0.5} />
      {mgmt.map((p, i) => (
        <PortGlyph key={p.id} port={p} x={mgmtX} y={14 + i * rowGap} size={21} uid={uid} selected={selectedId === p.id} onHover={onHover} onSelect={onSelect} showLabel labelBelow labelText={p.name} />
      ))}
      <g transform={`translate(${ventX} 12)`} aria-hidden="true">
        <rect width={APPL_W - ventX - 14} height={APPL_H - 18} rx={3} fill={`url(#${uid}-vent)`} stroke="var(--metal-hi)" strokeOpacity={0.4} />
      </g>
    </ChassisBody>
  );
}

// Branch router: fixed RJ45, SFP, a module slot (filled), fan and console/USB/AUX.
export function RouterLayout({ ports, uid, selectedId, onHover, onSelect, filled }: Props & { filled?: boolean }) {
  const fixedRj = ports.filter((p) => p.name.startsWith('Gi0/0/'));
  const sfp = ports.filter((p) => p.type === 'SFP');
  const mod = ports.filter((p) => p.name.startsWith('Gi0/2/'));
  const rjPitch = 30; // 21px port + 9px gap
  const rjEnd = 92 + fixedRj.length * rjPitch - 9;
  const sfpX = rjEnd + 16;
  const sfpPitch = 36; // 23px x1.15 = 26.5px + 9px gap
  const sfpEnd = sfpX + sfp.length * sfpPitch - 9;
  const modX = Math.max(310, sfpEnd + 16);
  return (
    <ChassisBody x={0} y={0} w={APPL_W} h={APPL_H + 22} uid={uid}>
      <VentGrille x={10} y={10} w={14} h={30} uid={uid} />
      <StatusLeds x={32} y={10} uid={uid} items={[{ label: 'SYS', color: 'var(--success)' }, { label: 'ACT', color: 'var(--teal)' }, { label: 'VPN', color: 'var(--success)' }]} />
      <EngravedText x={32} y={APPL_H + 12} size={5}>BRANCH ROUTER</EngravedText>
      {fixedRj.map((p, i) => (
        <PortGlyph key={p.id} port={p} x={92 + i * rjPitch} y={26} size={21} uid={uid} selected={selectedId === p.id} onHover={onHover} onSelect={onSelect} showLabel labelBelow labelText={String(i)} />
      ))}
      {sfp.map((p, i) => (
        <PortGlyph key={p.id} port={p} x={sfpX + i * sfpPitch} y={26} size={23} uid={uid} selected={selectedId === p.id} onHover={onHover} onSelect={onSelect} showLabel labelBelow labelText={`SFP${i}`} />
      ))}
      {/* module slot */}
      <g transform={`translate(${modX} 8)`}>
        <rect width={170} height={APPL_H + 4} rx={3} fill="var(--navy)" stroke="var(--metal-hi)" />
        <text x={8} y={10} fontSize={5} fill="var(--down)" fontFamily="var(--font-mono)">MODULE SLOT 2 · {filled ? 'FILLED' : 'BLANK'}</text>
        {filled ? (
          <>
            <rect x={8} y={16} width={154} height={APPL_H - 24} rx={2} fill="var(--metal-2)" stroke="var(--metal-hi)" strokeOpacity={0.5} />
            {mod.map((p, i) => (
              <PortGlyph key={p.id} port={p} x={22 + i * 34} y={34} size={21} uid={uid} selected={selectedId === p.id} onHover={onHover} onSelect={onSelect} showLabel labelBelow labelText={String(i)} />
            ))}
          </>
        ) : (
          <rect x={8} y={16} width={154} height={APPL_H - 24} rx={2} fill={`url(#${uid}-plate)`} />
        )}
      </g>
      {/* fan */}
      <g transform={`translate(${modX + 190} 14)`} role="img" aria-label="Fan, running">
        <rect width={66} height={66} rx={4} fill="var(--navy)" stroke="var(--metal-hi)" strokeOpacity={0.5} />
        <circle cx={33} cy={33} r={26} fill="var(--metal-3)" stroke="var(--metal-hi)" strokeOpacity={0.5} />
        {[0, 60, 120, 180, 240, 300].map((a) => (
          <path key={`fan-${a}`} d="M33 33 L33 10 A23 23 0 0 1 49 17 Z" fill="var(--metal-1)" transform={`rotate(${a} 33 33)`} />
        ))}
        <circle cx={33} cy={33} r={5} fill="var(--metal-hi)" />
      </g>
      <g transform={`translate(${modX + 276} 20)`}>
        <rect width={14} height={9} rx={1.5} fill="var(--navy)" stroke="var(--metal-hi)" strokeWidth={0.6} />
        <rect x={20} width={14} height={9} rx={1.5} fill="var(--navy)" stroke="var(--metal-hi)" strokeWidth={0.6} />
        <rect x={40} width={14} height={9} rx={1.5} fill="var(--navy)" stroke="var(--metal-hi)" strokeWidth={0.6} />
        <text x={0} y={19} fontSize={4.6} fill="var(--down)" fontFamily="var(--font-mono)">CON  USB  AUX</text>
      </g>
    </ChassisBody>
  );
}