import React from 'react';

interface ChassisProps {
  x: number;
  y: number;
  w: number;
  h: number;
  uid: string;
  rx?: number;
  ears?: boolean;
  charcoal?: boolean;
  children?: React.ReactNode;
}

// Rack-mount body: brushed dark metal, bevel highlight, rack ears and soft shadow.
export default function ChassisBody({ x, y, w, h, uid, rx = 5, ears = true, charcoal = false, children }: ChassisProps) {
  const corner = charcoal ? 8 : rx;
  return (
    <g data-chassis="" transform={`translate(${x} ${y})`}>
      {charcoal ? (
        <linearGradient id={`${uid}-charcoal`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#3d4858" />
          <stop offset="0.42" stopColor="#242c38" />
          <stop offset="1" stopColor="#141a22" />
        </linearGradient>
      ) : null}
      <g filter={`url(#${uid}-shadow)`}>
        <rect width={w} height={h} rx={corner} fill={charcoal ? `url(#${uid}-charcoal)` : `url(#${uid}-metal)`} />
      </g>
      {charcoal ? null : <rect width={w} height={h} rx={rx} fill={`url(#${uid}-brush)`} />}
      <rect x={1} y={1} width={w - 2} height={h - 2} rx={corner} fill="none" stroke={charcoal ? '#9aa6b5' : 'var(--metal-hi)'} strokeOpacity={charcoal ? 0.85 : 0.6} strokeWidth={charcoal ? 1.1 : 1} />
      <rect x={1.5} y={h - 3} width={w - 3} height={1.6} rx={0.8} fill="var(--navy)" opacity={0.7} />
      {ears && (
        <>
          <rect x={-5} y={h * 0.2} width={7} height={h * 0.6} rx={1.5} fill={`url(#${uid}-plate)`} />
          <circle cx={-1.5} cy={h * 0.5} r={1.8} fill="var(--navy)" />
          <rect x={w - 2} y={h * 0.2} width={7} height={h * 0.6} rx={1.5} fill={`url(#${uid}-plate)`} />
          <circle cx={w + 1.5} cy={h * 0.5} r={1.8} fill="var(--navy)" />
        </>
      )}
      {children}
    </g>
  );
}

export function EngravedText({ x, y, children, size = 6, anchor = 'start' }: { x: number; y: number; children: React.ReactNode; size?: number; anchor?: 'start' | 'middle' | 'end' }) {
  return (
    <text x={x} y={y} fontSize={size} fill="var(--down)" fontFamily="var(--font-mono)" textAnchor={anchor} letterSpacing="0.06em" aria-hidden="true">
      {children}
    </text>
  );
}

export function StatusLeds({ x, y, uid, items }: { x: number; y: number; uid: string; items: { label: string; color: string; blink?: boolean }[] }) {
  return (
    <g transform={`translate(${x} ${y})`} aria-hidden="true">
      {items.map((it, i) => (
        <g key={`led-${it.label}`} transform={`translate(0 ${i * 9})`}>
          <circle cx={3} cy={3} r={2.2} fill={it.color} filter={`url(#${uid}-glow)`} className={it.blink ? 'led-warn-blink' : undefined} />
          <text x={9} y={5.2} fontSize={5.2} fill="var(--down)" fontFamily="var(--font-mono)">
            {it.label}
          </text>
        </g>
      ))}
    </g>
  );
}

export function VentGrille({ x, y, w, h, uid }: { x: number; y: number; w: number; h: number; uid: string }) {
  return (
    <g transform={`translate(${x} ${y})`} aria-hidden="true">
      <rect width={w} height={h} rx={2} fill={`url(#${uid}-grille)`} stroke="var(--metal-hi)" strokeOpacity={0.4} />
    </g>
  );
}