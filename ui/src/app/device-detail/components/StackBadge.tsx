'use client';

import React from 'react';
import type { DeviceHealth, DeviceStack, StackMemberInfo } from '@/lib/types';

const SWITCH_FORMS = new Set(['access-switch-24', 'access-switch-48', 'switch-stack']);

export type TileHealth = DeviceHealth | 'unknown';

/** Glossy pebble in the same colour the device health badge uses. */
export const HEALTH_TONES: Record<TileHealth, { name: string; deep: string; mid: string; light: string; ink: string }> = {
  healthy: { name: 'green', deep: '#15803d', mid: '#22c55e', light: '#dcfce7', ink: '#14532d' },
  warning: { name: 'amber', deep: '#b45309', mid: '#f59e0b', light: '#fef3c7', ink: '#451a03' },
  critical: { name: 'red', deep: '#991b1b', mid: '#ef4444', light: '#fecaca', ink: '#fffef8' },
  unreachable: { name: 'grey', deep: '#334155', mid: '#64748b', light: '#e2e8f0', ink: '#0f172a' },
  unknown: { name: 'grey', deep: '#64748b', mid: '#94a3b8', light: '#f8fafc', ink: '#0f172a' },
};

export function memberLabel(number: number): string {
  return String(number).padStart(2, '0');
}

export function memberTooltip(member: StackMemberInfo): string {
  const parts = [`Member ${memberLabel(member.number)}`, member.role || 'member'];
  if (member.model) parts.push(member.model);
  if (member.serial) parts.push(member.serial);
  if (member.state) parts.push(member.state);
  if (member.healthReason) parts.push(member.healthReason);
  return parts.join(' · ');
}

/** Same rule as the API: own state wins, otherwise the device badge, otherwise grey. */
export function tileHealth(
  member: StackMemberInfo,
  members: StackMemberInfo[],
  deviceHealth?: DeviceHealth,
  deviceReason?: string,
): { health: TileHealth; reason: string } {
  if (member.health) {
    const health = member.health in HEALTH_TONES ? member.health : 'unknown';
    return { health, reason: member.healthReason || member.health };
  }
  const state = (member.state || '').trim();
  const anyState = members.some((item) => (item.state || '').trim());
  if (state) {
    if (state.toLowerCase() !== 'ready') return { health: 'critical', reason: `Member state is ${state}` };
    return { health: 'healthy', reason: 'Member state is ready' };
  }
  if (anyState) return { health: 'unknown', reason: 'No data pulled from this member' };
  if (deviceHealth && deviceHealth in HEALTH_TONES) {
    return { health: deviceHealth, reason: deviceReason || `Device is ${deviceHealth}` };
  }
  return { health: 'unknown', reason: 'No data pulled from this member' };
}

export function stackGrid(count: number): { cols: number; rows: number } {
  const total = Math.max(count, 1);
  if (total === 1) return { cols: 1, rows: 1 };
  if (total === 2) return { cols: 2, rows: 1 };
  if (total <= 4) return { cols: 2, rows: 2 };
  return { cols: 4, rows: Math.ceil(total / 4) };
}

/** Small pebbles centred in the stack box, with a 4px gap. Master is about 1.3×. */
export function tileMetrics(count: number) {
  const { cols, rows } = stackGrid(count);
  const base = 26;
  const big = count > 1 ? 34 : 26;
  const gap = 4;
  const font = 12;
  const boxW = cols * base + gap * Math.max(cols - 1, 0);
  return { base, big, gap, cols, rows, font, boxW };
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

export default function StackBadge({
  members,
  deviceHealth,
  deviceReason,
}: {
  members: StackMemberInfo[];
  deviceHealth?: DeviceHealth;
  deviceReason?: string;
}) {
  const ordered = [...members].filter((member) => member.number >= 1).sort((a, b) => a.number - b.number);
  const shown = ordered.length ? ordered : [{ number: 1, role: 'active', master: true }];
  const { base, big, gap, cols, rows, font } = tileMetrics(shown.length);
  return (
    <div
      data-testid="stack-badge"
      role="group"
      aria-label="Stack members"
      className="grid h-full shrink-0 content-center justify-center"
      style={{
        display: 'grid',
        height: '100%',
        flexShrink: 0,
        alignContent: 'center',
        justifyContent: 'center',
        padding: 8,
        boxSizing: 'border-box',
        columnGap: gap,
        rowGap: gap,
        gridTemplateColumns: `repeat(${cols}, ${base}px)`,
        gridTemplateRows: `repeat(${rows}, ${base}px)`,
      }}
    >
      {shown.map((member, index) => {
        const resolved = tileHealth(member, shown, deviceHealth, deviceReason);
        const tone = HEALTH_TONES[resolved.health];
        const size = member.master ? big : base;
        const extra = size - base;
        const tip = memberTooltip({ ...member, healthReason: resolved.reason });
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
            data-health={resolved.health}
            title={tip}
            aria-label={tip}
            style={{
              gridColumn: column,
              gridRow: row,
              width: size,
              height: size,
              marginLeft: extra ? -extra / 2 : 0,
              marginTop: extra ? -extra / 2 : 0,
              zIndex: member.master ? 30 : index + 1,
              borderRadius: '40%',
              backgroundColor: tone.mid,
              backgroundImage: `linear-gradient(180deg, rgba(255,255,255,.75) 0%, rgba(255,255,255,0) 32%), linear-gradient(180deg, ${tone.light} 0%, ${tone.mid} 48%, ${tone.deep} 100%)`,
              boxShadow: [
                'inset 0 1px 0 rgba(255,255,255,.9)',
                '0 1px 2px rgba(15,23,42,.2)',
                member.role === 'standby' ? '0 0 0 1.5px #0f172a' : '',
              ].filter(Boolean).join(', '),
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontWeight: 600,
              color: tone.ink,
              textShadow: resolved.health === 'critical' ? '0 1px 1px rgba(0,0,0,.45)' : 'none',
              fontSize: font,
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
