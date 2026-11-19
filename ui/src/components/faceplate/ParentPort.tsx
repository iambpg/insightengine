'use client';

import React from 'react';

// The same jack the chassis draws: copper pins or an SFP cage, green rim and glow when the link is up.
export default function ParentPortPicture({ name, up = true }: { name: string; up?: boolean }) {
  const fiber = /te|hu|fo|twe|sfp|uplink/i.test(name);
  const w = fiber ? 44 : 28;
  const h = fiber ? 26 : 34;
  const rim = up ? '#22c55e' : '#64748b';
  return (
    <div data-testid="parent-port" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <div style={{ position: 'relative', width: w, height: h, flexShrink: 0 }}>
        <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} aria-hidden="true" style={{ display: 'block', overflow: 'visible' }}>
          <defs>
            <linearGradient id="parent-port-bay" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0" stopColor="#0b1220" />
              <stop offset="1" stopColor="#12161f" />
            </linearGradient>
            <filter id="parent-port-glow" x="-80%" y="-80%" width="260%" height="260%">
              <feGaussianBlur stdDeviation="1.8" result="b" />
              <feMerge>
                <feMergeNode in="b" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>
          </defs>
          <rect x={0} y={0} width={w} height={h} rx={fiber ? 1.4 : 2} fill="url(#parent-port-bay)" stroke={rim} strokeWidth={up ? 1.7 : 1} filter={up ? 'url(#parent-port-glow)' : undefined} />
          {fiber ? (
            <>
              <rect x={w * 0.12} y={h * 0.22} width={w * 0.76} height={h * 0.56} rx={1.2} fill="#12161f" stroke="#4a5468" strokeWidth={0.6} />
              <rect x={w * 0.22} y={h * 0.38} width={w * 0.56} height={h * 0.24} rx={0.8} fill={up ? '#22c55e' : '#334155'} opacity={up ? 0.95 : 0.4} />
            </>
          ) : (
            <>
              <rect x={w * 0.12} y={h * 0.16} width={w * 0.76} height={h * 0.46} rx={1} fill="#12161f" />
              {Array.from({ length: 8 }, (_, index) => (
                <rect key={`pin-${index + 1}`} x={w * 0.18 + index * (w * 0.08)} y={h * 0.22} width={w * 0.03} height={h * 0.32} fill="#4a5468" />
              ))}
              <rect x={w * 0.3} y={h * 0.68} width={w * 0.4} height={h * 0.12} rx={0.8} fill="#2a3140" />
            </>
          )}
          <circle cx={w - 3.5} cy={3.4} r={1.7} fill={up ? '#22c55e' : '#8a97ab'} filter={up ? 'url(#parent-port-glow)' : undefined} />
        </svg>
        <span data-port-name={name} style={{ position: 'absolute', left: 0, right: 0, bottom: 0, height: 6 }} />
      </div>
      <span style={{ font: '600 12px/1.2 ui-monospace, monospace', color: '#0f172a', whiteSpace: 'nowrap' }} title={name}>{name}</span>
    </div>
  );
}
