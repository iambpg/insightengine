'use client';

import React from 'react';

export type DeviceKind =
  | 'switch' |'stack' |'ap' |'firewall' |'router' |'controller' |'chassis' |'cloud';

interface DeviceArtProps {
  kind: DeviceKind;
  x: number;
  y: number;
  w?: number;
  h?: number;
}

function Port({ x, y, on = true }: { x: number; y: number; on?: boolean }) {
  return (
    <g>
      <rect x={x} y={y} width="5" height="4.5" rx="0.6" fill="#0b1220" stroke="#4b5563" strokeWidth="0.4" />
      <rect x={x + 1.2} y={y + 3.4} width="2.6" height="0.9" fill={on ? '#22c55e' : '#374151'} />
    </g>
  );
}

function Led({ x, y, color }: { x: number; y: number; color: string }) {
  return <circle cx={x} cy={y} r="1.4" fill={color} />;
}

function Rack({ w, h, gradId }: { w: number; h: number; gradId: string }) {
  return (
    <g>
      <rect x="0" y="0" width={w} height={h} rx="2.5" fill={`url(#${gradId})`} stroke="#0f172a" strokeWidth="1" />
      <rect x="0" y="0" width="7" height={h} rx="2" fill="#94a3b8" opacity="0.55" />
      <rect x={w - 7} y="0" width="7" height={h} rx="2" fill="#94a3b8" opacity="0.55" />
      <circle cx="3.5" cy="5" r="1.4" fill="#475569" />
      <circle cx="3.5" cy={h - 5} r="1.4" fill="#475569" />
      <circle cx={w - 3.5} cy="5" r="1.4" fill="#475569" />
      <circle cx={w - 3.5} cy={h - 5} r="1.4" fill="#475569" />
    </g>
  );
}

function PortRow({ x, y, count, gap = 7 }: { x: number; y: number; count: number; gap?: number }) {
  return (
    <g>
      {Array.from({ length: count }, (_, i) => (
        <Port key={`pr-${x}-${y}-${i}`} x={x + i * gap} y={y} on={(i * 7 + count) % 5 !== 0} />
      ))}
    </g>
  );
}

export default function DeviceArt({ kind, x, y, w = 128, h = 40 }: DeviceArtProps) {
  const cx = x + w / 2;
  const cy = y + h / 2;

  if (kind === 'cloud') {
    return (
      <g transform={`translate(${cx - 40}, ${cy - 24})`}>
        <path
          d="M22 40 C8 40 4 24 18 21 C18 8 38 4 44 16 C54 8 72 14 68 28 C80 28 80 42 68 42 Z"
          fill="url(#art-cloud)"
          stroke="#64748b"
          strokeWidth="1.4"
        />
        <ellipse cx="40" cy="26" rx="14" ry="6" fill="none" stroke="#475569" strokeWidth="1" opacity="0.7" />
        <path d="M26 26 H54 M40 20 V32" stroke="#475569" strokeWidth="0.8" opacity="0.7" />
      </g>
    );
  }

  const body = (() => {
    switch (kind) {
      case 'switch': {
        return (
          <g>
            <Rack w={w} h={h} gradId="art-metal" />
            <rect x="10" y="6" width="34" height="8" rx="1" fill="#0b1220" />
            <text x="12" y="12" fontSize="5" fill="#38bdf8" fontFamily="monospace">SWITCH</text>
            <Led x={50} y={10} color="#22c55e" />
            <Led x={56} y={10} color="#22c55e" />
            <Led x={62} y={10} color="#f59e0b" />
            <PortRow x={10} y={19} count={12} />
            <PortRow x={10} y={27} count={12} />
            <rect x={w - 30} y="18" width="18" height="14" rx="1.2" fill="#0b1220" stroke="#4b5563" strokeWidth="0.5" />
            <Port x={w - 28} y={21} />
            <Port x={w - 21} y={21} />
            <Port x={w - 28} y={27} />
            <Port x={w - 21} y={27} on={false} />
          </g>
        );
      }
      case 'stack': {
        const unit = (oy: number, k: string) => (
          <g key={k} transform={`translate(0, ${oy})`}>
            <Rack w={w} h={17} gradId="art-metal" />
            <PortRow x={10} y={6} count={13} gap={6.5} />
            <Led x={w - 40} y={8.5} color="#22c55e" />
            <Led x={w - 34} y={8.5} color="#22c55e" />
            <rect x={w - 28} y="5" width="16" height="7" rx="1" fill="#0b1220" />
          </g>
        );
        return (
          <g>
            {unit(0, 'u1')}
            {unit(11.5, 'u2')}
            {unit(23, 'u3')}
            <path d={`M${w - 9} 14 C${w + 1} 14 ${w + 1} 30 ${w - 9} 30`} fill="none" stroke="#f59e0b" strokeWidth="1.4" />
          </g>
        );
      }
      case 'firewall': {
        return (
          <g>
            <Rack w={w} h={h} gradId="art-dark" />
            <rect x="10" y="6" width="26" height="9" rx="1" fill="#7f1d1d" />
            <path d="M23 7.5 l5 2 v3 c0 2 -2 3 -5 4 c-3 -1 -5 -2 -5 -4 v-3 z" fill="#fca5a5" opacity="0.9" transform="translate(0,-1) scale(1)" />
            <text x="40" y="12" fontSize="5" fill="#fca5a5" fontFamily="monospace">FIREWALL</text>
            <Led x={w - 40} y={10} color="#22c55e" />
            <Led x={w - 34} y={10} color="#22c55e" />
            <Led x={w - 28} y={10} color="#f59e0b" />
            <PortRow x={10} y={22} count={8} gap={8} />
            <rect x={w - 50} y="20" width="38" height="14" rx="1.2" fill="#0b1220" stroke="#4b5563" strokeWidth="0.5" />
            <rect x={w - 46} y="23" width="7" height="8" rx="0.8" fill="#1f2937" stroke="#6b7280" strokeWidth="0.4" />
            <rect x={w - 36} y="23" width="7" height="8" rx="0.8" fill="#1f2937" stroke="#6b7280" strokeWidth="0.4" />
            <rect x={w - 26} y="23" width="7" height="8" rx="0.8" fill="#1f2937" stroke="#6b7280" strokeWidth="0.4" />
          </g>
        );
      }
      case 'router': {
        return (
          <g>
            <Rack w={w} h={h} gradId="art-metal" />
            <rect x="10" y="6" width="30" height="8" rx="1" fill="#0b1220" />
            <text x="12" y="12" fontSize="5" fill="#a78bfa" fontFamily="monospace">ROUTER</text>
            <Led x={48} y={10} color="#22c55e" />
            <Led x={54} y={10} color="#22c55e" />
            <PortRow x={10} y={21} count={6} gap={9} />
            <rect x={w - 52} y="18" width="14" height="14" rx="1.2" fill="#0b1220" stroke="#4b5563" strokeWidth="0.5" />
            <circle cx={w - 45} cy="25" r="4" fill="#111827" stroke="#6b7280" strokeWidth="0.5" />
            <rect x={w - 32} y="18" width="20" height="14" rx="1.2" fill="#0b1220" stroke="#4b5563" strokeWidth="0.5" />
            <Port x={w - 29} y={21} />
            <Port x={w - 21} y={21} />
            <Port x={w - 29} y={26} on={false} />
            <Port x={w - 21} y={26} />
          </g>
        );
      }
      case 'controller': {
        return (
          <g>
            <Rack w={w} h={h} gradId="art-metal" />
            <rect x="10" y="6" width="36" height="8" rx="1" fill="#0b1220" />
            <text x="12" y="12" fontSize="5" fill="#34d399" fontFamily="monospace">WLC</text>
            <g stroke="#34d399" fill="none" strokeWidth="1" strokeLinecap="round">
              <path d="M36 12 a4 4 0 0 1 4 -3" />
              <path d="M34 12 a6 6 0 0 1 7 -5" />
            </g>
            <Led x={w - 40} y={10} color="#22c55e" />
            <Led x={w - 34} y={10} color="#22c55e" />
            <PortRow x={10} y={20} count={10} gap={8} />
            <PortRow x={10} y={28} count={4} gap={8} />
            <rect x={w - 56} y="27" width="44" height="7" rx="1" fill="#0b1220" />
          </g>
        );
      }
      case 'chassis': {
        return (
          <g>
            <Rack w={w} h={h + 6} gradId="art-dark" />
            {[0, 1, 2, 3].map((i) => (
              <g key={`blade-${i}`}>
                <rect x={11 + i * 24} y="5" width="21" height={h - 4} rx="1.5" fill="#111827" stroke="#475569" strokeWidth="0.6" />
                <Led x={14 + i * 24} y={9} color={i === 1 ? '#ef4444' : '#22c55e'} />
                <PortRow x={13 + i * 24} y={15} count={3} gap={6} />
                <PortRow x={13 + i * 24} y={22} count={3} gap={6} />
                <PortRow x={13 + i * 24} y={29} count={3} gap={6} />
              </g>
            ))}
            <rect x={w - 28} y="5" width="18" height={h - 4} rx="1.5" fill="#1e293b" stroke="#475569" strokeWidth="0.6" />
            <text x={w - 26} y="14" fontSize="4.5" fill="#38bdf8" fontFamily="monospace">SUP</text>
          </g>
        );
      }
      case 'ap': {
        const r = Math.min(w, h) / 2;
        return (
          <g transform={`translate(${w / 2}, ${h / 2})`}>
            <ellipse cx="0" cy={r * 0.55} rx={r * 0.95} ry={r * 0.2} fill="#000" opacity="0.18" />
            <ellipse cx="0" cy="2" rx={r * 1.05} ry={r * 0.62} fill="url(#art-ap)" stroke="#94a3b8" strokeWidth="1" />
            <ellipse cx="0" cy="-1" rx={r * 0.6} ry={r * 0.32} fill="#f8fafc" stroke="#cbd5e1" strokeWidth="0.8" />
            <circle cx="0" cy="-1" r="2.6" fill="#22c55e" />
            <circle cx="0" cy="-1" r="4.6" fill="none" stroke="#22c55e" strokeWidth="0.6" opacity="0.6" />
            <g stroke="#38bdf8" fill="none" strokeWidth="1.1" strokeLinecap="round" opacity="0.85">
              <path d={`M${-r * 0.45} ${-r * 0.55} a${r * 0.7} ${r * 0.5} 0 0 1 ${r * 0.9} 0`} />
              <path d={`M${-r * 0.7} ${-r * 0.8} a${r} ${r * 0.7} 0 0 1 ${r * 1.4} 0`} />
            </g>
          </g>
        );
      }
      default:
        return null;
    }
  })();

  return <g transform={`translate(${x}, ${y})`}>{body}</g>;
}

export function ArtDefs() {
  return (
    <defs>
      <linearGradient id="art-metal" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stopColor="#e2e8f0" />
        <stop offset="0.5" stopColor="#cbd5e1" />
        <stop offset="1" stopColor="#94a3b8" />
      </linearGradient>
      <linearGradient id="art-dark" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stopColor="#475569" />
        <stop offset="1" stopColor="#1e293b" />
      </linearGradient>
      <radialGradient id="art-ap" cx="0.5" cy="0.35" r="0.8">
        <stop offset="0" stopColor="#ffffff" />
        <stop offset="1" stopColor="#cbd5e1" />
      </radialGradient>
      <linearGradient id="art-cloud" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stopColor="#f1f5f9" />
        <stop offset="1" stopColor="#cbd5e1" />
      </linearGradient>
    </defs>
  );
}
