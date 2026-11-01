import type { PortState } from '@/lib/types';

export const STATE_COLOR: Record<PortState, { fill: string; glow: string; rim: string }> = {
  up: { fill: 'var(--success)', glow: 'var(--success)', rim: 'var(--success)' },
  down: { fill: 'var(--down)', glow: 'var(--down)', rim: 'var(--down)' },
  warning: { fill: 'var(--warning)', glow: 'var(--warning)', rim: 'var(--warning)' },
  fault: { fill: 'var(--destructive)', glow: 'var(--destructive)', rim: 'var(--destructive)' },
  disabled: { fill: 'var(--disabled)', glow: 'var(--disabled)', rim: 'var(--disabled)' },
  unknown: { fill: 'var(--unknown)', glow: 'var(--unknown)', rim: 'var(--unknown)' },
};

// state glyph drawn inside the port cutout so state is never colour alone
export const STATE_GLYPH: Record<PortState, string> = {
  up: '●',
  down: '○',
  warning: '▲',
  fault: '✕',
  disabled: '▬',
  unknown: '?',
};

export const STATE_LABEL: Record<PortState, string> = {
  up: 'Up',
  down: 'Down',
  warning: 'Warning',
  fault: 'Fault',
  disabled: 'Disabled',
  unknown: 'Unknown',
};