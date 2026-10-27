import type { PortState } from '@/lib/types';

export const STATE_COLOR: Record<PortState, { fill: string; glow: string; rim: string }> = {
  up: { fill: 'var(--success)', glow: 'var(--success)', rim: 'var(--success)' },
  down: { fill: 'var(--down)', glow: 'var(--down)', rim: 'var(--down)' },
  warning: { fill: 'var(--warning)', glow: 'var(--warning)', rim: 'var(--warning)' },
  fault: { fill: 'var(--destructive)', glow: 'var(--destructive)', rim: 'var(--destructive)' },
  disabled: { fill: 'var(--info)', glow: 'var(--info)', rim: 'var(--info)' },
};

// state glyph drawn inside the port cutout so state is never colour alone
export const STATE_GLYPH: Record<PortState, string> = {
  up: '●',
  down: '○',
  warning: '▲',
  fault: '✕',
  disabled: '▬',
};

export const STATE_LABEL: Record<PortState, string> = {
  up: 'Up',
  down: 'Down',
  warning: 'Warning',
  fault: 'Fault',
  disabled: 'Disabled',
};