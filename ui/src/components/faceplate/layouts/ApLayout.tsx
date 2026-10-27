'use client';

import React from 'react';
import type { PortInfo, RadioInfo, PortState } from '@/lib/types';
import { STATE_COLOR } from '../palette';
import PortGlyph from '../Port';
import type { LayoutCommon } from './SwitchLayout';

interface ApProps extends LayoutCommon {
  ports: PortInfo[];
  radios: RadioInfo[];
  apState: PortState;
  selectedRadioId?: string | null;
  onRadioHover?: (radio: RadioInfo | null, el: SVGGElement | null) => void;
  onRadioSelect?: (radio: RadioInfo) => void;
}

export const AP_W = 470;
export const AP_H = 190;

export default function ApLayout({ ports, radios, apState, uid, selectedId, onHover, onSelect, selectedRadioId = null, onRadioHover, onRadioSelect }: ApProps) {
  const c = STATE_COLOR[apState];
  return (
    <g>
      {/* TOP VIEW */}
      <g transform="translate(10 8)">
        <text x={75} y={0} textAnchor="middle" fontSize={6} fill="var(--down)" fontFamily="var(--font-mono)" letterSpacing="0.1em">TOP VIEW</text>
        <g filter={`url(#${uid}-shadow)`}>
          <rect x={10} y={8} width={130} height={130} rx={34} fill={`url(#${uid}-apbody)`} stroke="var(--input)" />
        </g>
        <circle cx={75} cy={73} r={48} fill="var(--card)" stroke="var(--input)" strokeWidth={1} />
        {/* LED ring shows live state; dashed pattern differs per state so it is not colour only */}
        <circle
          cx={75}
          cy={73}
          r={40}
          fill="none"
          stroke={c.fill}
          strokeWidth={6}
          strokeDasharray={apState === 'up' ? undefined : apState === 'warning' ? '14 6' : apState === 'fault' ? '4 6' : apState === 'disabled' ? '1 8' : '2 12'}
          strokeLinecap="round"
          filter={`url(#${uid}-glow-big)`}
          className={apState === 'warning' ? 'led-warn-blink' : apState === 'fault' ? 'led-fault-blink' : undefined}
        />
        <circle cx={75} cy={73} r={22} fill="var(--secondary)" stroke="var(--input)" />
        <circle cx={75} cy={73} r={8} fill="var(--input)" />
        <text x={75} y={156} textAnchor="middle" fontSize={6.4} fill={c.fill} fontFamily="var(--font-mono)">
          {apState === 'up' ? '● Up' : apState === 'warning' ? '▲ Warning' : apState === 'fault' ? '✕ Fault' : apState === 'disabled' ? '▬ Disabled' : '○ Offline'}
        </text>
      </g>

      {/* SIDE VIEW */}
      <g transform="translate(180 20)">
        <text x={140} y={0} textAnchor="middle" fontSize={6} fill="var(--down)" fontFamily="var(--font-mono)" letterSpacing="0.1em">SIDE VIEW</text>
        <rect x={0} y={14} width={280} height={8} rx={4} fill="var(--input)" />
        <g filter={`url(#${uid}-shadow)`}>
          <rect x={10} y={22} width={260} height={64} rx={9} fill={`url(#${uid}-apbody)`} stroke="var(--input)" />
        </g>
        <circle cx={34} cy={72} r={2.6} fill={c.fill} filter={`url(#${uid}-glow)`} />
        <text x={42} y={74.5} fontSize={5.6} fill="var(--muted-foreground)" fontFamily="var(--font-mono)">STATUS</text>
        <rect x={112} y={34} width={116} height={48} rx={5} fill="var(--navy)" opacity={0.92} />
        {ports.map((p, i) => (
          <PortGlyph key={p.id} port={p} x={126 + i * 48} y={42} size={20} uid={uid} selected={selectedId === p.id} onHover={onHover} onSelect={onSelect} showLabel labelBelow labelText={p.type === 'CONSOLE' ? 'CON' : 'ETH0'} />
        ))}
        <circle cx={248} cy={54} r={5} fill="var(--metal-3)" stroke="var(--metal-hi)" />
        <text x={248} y={74} textAnchor="middle" fontSize={5} fill="var(--down)" fontFamily="var(--font-mono)">DC</text>
      </g>

      {/* RADIOS */}
      <g transform="translate(180 128)">
        <text x={0} y={0} fontSize={6} fill="var(--down)" fontFamily="var(--font-mono)" letterSpacing="0.1em">RADIOS</text>
        {radios.map((r, i) => {
          const rc = STATE_COLOR[r.state];
          const isSel = selectedRadioId === r.id;
          return (
            <g
              key={r.id}
              transform={`translate(${i * 94} 8)`}
              role="button"
              tabIndex={0}
              aria-pressed={isSel}
              aria-label={`${r.band} radio, channel ${r.channel}, ${r.clients} clients, ${r.utilisation}% utilisation. Press Enter for details.`}
              style={{ cursor: 'pointer', outline: 'none' }}
              onMouseEnter={(e) => onRadioHover?.(r, e.currentTarget)}
              onMouseLeave={() => onRadioHover?.(null, null)}
              onFocus={(e) => onRadioHover?.(r, e.currentTarget)}
              onBlur={() => onRadioHover?.(null, null)}
              onClick={() => onRadioSelect?.(r)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault();
                  onRadioSelect?.(r);
                }
              }}
            >
              <rect width={86} height={42} rx={5} fill="var(--card)" stroke={rc.fill} strokeWidth={isSel ? 2.4 : 1.2} />
              <circle cx={9} cy={10} r={3} fill={rc.fill} filter={`url(#${uid}-glow)`} className={r.state === 'warning' ? 'led-warn-blink' : undefined} />
              <text x={16} y={12.5} fontSize={6.6} fontWeight={600} fill="var(--foreground)" fontFamily="var(--font-sans)">{r.band}</text>
              <text x={8} y={25} fontSize={5.6} fill="var(--muted-foreground)" fontFamily="var(--font-mono)">{`ch ${r.channel} · ${r.clients} clients`}</text>
              <rect x={8} y={31} width={70} height={4} rx={2} fill="var(--muted)" />
              <rect x={8} y={31} width={(70 * r.utilisation) / 100} height={4} rx={2} fill={rc.fill} />
            </g>
          );
        })}
      </g>
    </g>
  );
}