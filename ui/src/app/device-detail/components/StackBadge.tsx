'use client';

import React from 'react';
import type { DeviceStack, StackMemberInfo } from '@/lib/types';

const SWITCH_FORMS = new Set(['access-switch-24', 'access-switch-48', 'switch-stack']);

/** Tile colour follows the member number, so 01 stays teal on every stack. */
export const STACK_TONES = [
  { name: 'teal', deep: '#0f766e', mid: '#14b8a6', light: '#99f6e4' },
  { name: 'amber', deep: '#b45309', mid: '#f59e0b', light: '#fde68a' },
  { name: 'green', deep: '#15803d', mid: '#22c55e', light: '#bbf7d0' },
  { name: 'slate', deep: '#475569', mid: '#94a3b8', light: '#e2e8f0' },
  { name: 'blue', deep: '#1d4ed8', mid: '#3b82f6', light: '#bfdbfe' },
  { name: 'purple', deep: '#6d28d9', mid: '#a855f7', light: '#e9d5ff' },
  { name: 'coral', deep: '#e11d48', mid: '#fb7185', light: '#fecdd3' },
  { name: 'cyan', deep: '#0e7490', mid: '#22d3ee', light: '#cffafe' },
] as const;

export function memberLabel(number: number): string {
  return String(number).padStart(2, '0');
}

export function memberTooltip(member: StackMemberInfo): string {
  const parts = [`Member ${memberLabel(member.number)}`, member.role || 'member'];
  if (member.model) parts.push(member.model);
  if (member.serial) parts.push(member.serial);
  if (member.state) parts.push(member.state);
  return parts.join(' · ');
}

export function stackGrid(count: number): { cols: number; rows: number } {
  const total = Math.max(count, 1);
  if (total === 1) return { cols: 1, rows: 1 };
  if (total === 2) return { cols: 2, rows: 1 };
  if (total <= 4) return { cols: 2, rows: 2 };
  return { cols: 4, rows: Math.ceil(total / 4) };
}

/** Fit the cluster inside the existing header button box (about 72×86). */
export function tileMetrics(count: number, maxW = 72, maxH = 86) {
  const { cols, rows } = stackGrid(count);
  const many = count > 1;
  for (let base = 48; base >= 12; base -= 1) {
    const big = many ? Math.round(base * 1.4) : base;
    const overlap = Math.max(2, Math.round(base * 0.22));
    const extra = big - base;
    const width = cols * base - overlap * Math.max(cols - 1, 0) + extra;
    const height = rows * base - overlap * Math.max(rows - 1, 0) + extra;
    if (width <= maxW && height <= maxH) return { base, big, overlap, cols, rows };
  }
  return { base: 12, big: many ? 17 : 12, overlap: 2, cols, rows };
}

export function isSwitchDevice(device: { role?: string; faceplate?: { form_factor?: string } }): boolean {
  const form = device.faceplate?.form_factor || '';
  if (SWITCH_FORMS.has(form)) return true;
  return (device.role || '').toLowerCase().includes('switch');
}

export function stackMembersFor(device: {
  role?: string;
  modelFamily?: string;
  faceplate?: { form_factor?: string; modelName?: string };
  stack?: DeviceStack | null;
}): StackMemberInfo[] | null {
  if (!isSwitchDevice(device)) return null;
  const members = (device.stack?.members || []).filter((member) => member && member.number >= 1);
  if (members.length) return [...members].sort((a, b) => a.number - b.number);
  return [{
    number: 1,
    role: 'active',
    model: device.faceplate?.modelName || device.modelFamily || '',
    serial: '',
    state: '',
    master: true,
  }];
}

function pebbleRadius(number: number): string {
  const a = 44 + (number % 3) * 3;
  const b = 56 - (number % 4);
  return `${a}% ${b}% ${50 + (number % 5)}% 48% / 52% ${46 + (number % 3)}% 54% 50%`;
}

export default function StackBadge({ members }: { members: StackMemberInfo[] }) {
  const ordered = [...members].filter((member) => member.number >= 1).sort((a, b) => a.number - b.number);
  const shown = ordered.length ? ordered : [{ number: 1, role: 'active', master: true }];
  const { base, big, overlap, cols, rows } = tileMetrics(shown.length);
  return (
    <div
      data-testid="stack-badge"
      role="group"
      aria-label="Stack members"
      className="grid h-full w-[4.5rem] shrink-0 content-center justify-center"
      style={{
        display: 'grid',
        width: '4.5rem',
        height: '100%',
        flexShrink: 0,
        alignContent: 'center',
        justifyContent: 'center',
        gridTemplateColumns: `repeat(${cols}, max-content)`,
        gridTemplateRows: `repeat(${rows}, max-content)`,
      }}
    >
      {shown.map((member, index) => {
        const tone = STACK_TONES[(member.number - 1) % STACK_TONES.length];
        const size = member.master ? big : base;
        const tip = memberTooltip(member);
        const column = (index % cols) + 1;
        const row = Math.floor(index / cols) + 1;
        return (
          <span
            key={member.number}
            role="img"
            data-testid={`stack-member-${memberLabel(member.number)}`}
            data-master={member.master ? 'true' : 'false'}
            data-role={member.role || 'member'}
            data-tone={tone.name}
            title={tip}
            aria-label={tip}
            style={{
              gridColumn: column,
              gridRow: row,
              width: size,
              height: size,
              marginLeft: column === 1 ? 0 : -overlap,
              marginTop: row === 1 ? 0 : -overlap,
              zIndex: member.master ? 30 : index + 1,
              borderRadius: pebbleRadius(member.number),
              background: `radial-gradient(circle at 32% 28%, ${tone.light} 0%, ${tone.mid} 46%, ${tone.deep} 100%)`,
              boxShadow: [
                'inset 0 1px 0 rgba(255,255,255,.8)',
                '0 1px 2px rgba(15,23,42,.28)',
                member.role === 'standby' ? '0 0 0 1.5px #0f172a' : '',
              ].filter(Boolean).join(', '),
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontWeight: 800,
              color: '#1c1917',
              fontSize: Math.max(9, Math.round(size * 0.34)),
              lineHeight: 1,
              fontFamily: 'ui-sans-serif, system-ui, sans-serif',
            }}
          >
            {memberLabel(member.number)}
          </span>
        );
      })}
    </div>
  );
}
