'use client';

import React from 'react';
import type { PortInfo } from '@/lib/types';
import { STATE_COLOR, STATE_GLYPH, STATE_LABEL } from './palette';

interface PortGlyphProps {
  port: PortInfo;
  x: number;
  y: number;
  size?: number;
  uid: string;
  selected: boolean;
  showLabel?: boolean;
  labelBelow?: boolean;
  labelText?: string;
  onHover: (port: PortInfo | null, el: SVGGElement | null) => void;
  onSelect: (port: PortInfo) => void;
}

// A single port cutout: recessed housing, inner pins/cage, coloured status rim, state glyph and LED.
export default function PortGlyph({ port, x, y, size = 20, uid, selected, showLabel, labelBelow, labelText, onHover, onSelect }: PortGlyphProps) {
  const c = STATE_COLOR[port.state];
  const isFiber = port.type === 'SFP' || port.type === 'SFP+' || port.type === 'QSFP';
  const w = isFiber ? size * 1.15 : size;
  const h = isFiber ? size * 0.85 : size * 0.9;
  const active = port.state !== 'down';
  const label = `${port.name}, ${STATE_LABEL[port.state]}, ${port.speed}, ${port.utilisation}% utilisation, ${port.errors} errors`;

  return (
    <g
      transform={`translate(${x} ${y})`}
      tabIndex={0}
      role="button"
      aria-label={label}
      aria-pressed={selected}
      className="cursor-pointer outline-none"
      onMouseEnter={(e) => onHover(port, e.currentTarget)}
      onMouseLeave={() => onHover(null, null)}
      onFocus={(e) => onHover(port, e.currentTarget)}
      onBlur={() => onHover(null, null)}
      onClick={() => onSelect(port)}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          onSelect(port);
        }
      }}
    >
      {/* recessed housing with depth */}
      <rect x={-1.5} y={-1.5} width={w + 3} height={h + 3} rx={3} fill="var(--navy)" opacity={0.85} />
      <rect x={0} y={0} width={w} height={h} rx={2.2} fill={`url(#${uid}-bay)`} stroke={c.rim} strokeWidth={active ? 1.6 : 1} strokeOpacity={active ? 0.95 : 0.55} filter={port.state === 'fault' || port.state === 'warning' ? `url(#${uid}-glow)` : undefined} />
      {/* inner cage */}
      {isFiber ? (
        <>
          <rect x={w * 0.12} y={h * 0.2} width={w * 0.76} height={h * 0.6} rx={1.2} fill="var(--metal-3)" stroke="var(--metal-hi)" strokeWidth={0.5} />
          <rect x={w * 0.2} y={h * 0.38} width={w * 0.6} height={h * 0.24} rx={0.8} fill={c.fill} opacity={port.state === 'down' ? 0.25 : 0.9} />
        </>
      ) : (
        <>
          <rect x={w * 0.1} y={h * 0.14} width={w * 0.8} height={h * 0.5} rx={1} fill="var(--metal-3)" />
          {Array.from({ length: 8 }, (_, i) => (
            <rect key={`${port.id}-pin-${i + 1}`} x={w * 0.17 + i * (w * 0.082)} y={h * 0.2} width={w * 0.032} height={h * 0.34} fill="var(--metal-hi)" opacity={0.75} />
          ))}
          <rect x={w * 0.3} y={h * 0.68} width={w * 0.4} height={h * 0.14} rx={0.8} fill="var(--metal-1)" />
        </>
      )}
      {/* LED with glow */}
      <circle cx={w - 3.2} cy={3.2} r={1.9} fill={c.fill} filter={active ? `url(#${uid}-glow)` : undefined} className={port.state === 'warning' ? 'led-warn-blink' : port.state === 'fault' ? 'led-fault-blink' : undefined} />
      {/* state glyph so colour is never the only cue */}
      <text x={w / 2} y={h + 6.5} textAnchor="middle" fontSize={5.4} fill={c.fill} fontFamily="var(--font-mono)" aria-hidden="true">
        {STATE_GLYPH[port.state]}
      </text>
      {selected && (
        <rect x={-3.5} y={-3.5} width={w + 7} height={h + 7} rx={4.5} fill="none" stroke="var(--cyan)" strokeWidth={1.8} strokeDasharray="3 2" />
      )}
      {showLabel && (
        <text x={w / 2} y={labelBelow ? h + 14 : -4} textAnchor="middle" fontSize={5.6} fill="var(--down)" fontFamily="var(--font-mono)">
          {labelText ?? port.name.replace(/^\D+[\d/]*\//, '')}
        </text>
      )}
    </g>
  );
}