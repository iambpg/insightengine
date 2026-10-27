import React from 'react';
import Icon from '@/components/ui/AppIcon';
import type { DeviceHealth, PortState } from '@/lib/types';

type Tone = 'success' | 'warning' | 'destructive' | 'info' | 'neutral' | 'cyan';

const TONE: Record<Tone, string> = {
  success: 'bg-success/10 text-success border-success/30',
  warning: 'bg-warning/15 text-foreground border-warning/40',
  destructive: 'bg-destructive/10 text-destructive border-destructive/30',
  info: 'bg-info/10 text-info border-info/30',
  neutral: 'bg-muted text-muted-foreground border-border',
  cyan: 'bg-accent/15 text-foreground border-accent/40',
};

interface BadgeProps {
  tone?: Tone;
  icon?: string;
  children: React.ReactNode;
  className?: string;
}

export default function Badge({ tone = 'neutral', icon, children, className = '' }: BadgeProps) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium leading-5 ${TONE[tone]} ${className}`}
    >
      {icon ? <Icon name={icon} size={12} variant="solid" /> : null}
      {children}
    </span>
  );
}

const HEALTH_META: Record<DeviceHealth, { tone: Tone; icon: string; label: string }> = {
  healthy: { tone: 'success', icon: 'CheckCircleIcon', label: 'Healthy' },
  warning: { tone: 'warning', icon: 'ExclamationTriangleIcon', label: 'Warning' },
  critical: { tone: 'destructive', icon: 'XCircleIcon', label: 'Critical' },
  unreachable: { tone: 'neutral', icon: 'SignalSlashIcon', label: 'Unreachable' },
};

export function HealthBadge({ health }: { health: DeviceHealth }) {
  const m = HEALTH_META[health];
  return (
    <Badge tone={m.tone} icon={m.icon}>
      {m.label}
    </Badge>
  );
}

export const PORT_STATE_META: Record<PortState, { tone: Tone; icon: string; label: string; glyph: string }> = {
  up: { tone: 'success', icon: 'CheckCircleIcon', label: 'Up', glyph: '●' },
  down: { tone: 'neutral', icon: 'MinusCircleIcon', label: 'Down', glyph: '○' },
  warning: { tone: 'warning', icon: 'ExclamationTriangleIcon', label: 'Warning', glyph: '▲' },
  fault: { tone: 'destructive', icon: 'XCircleIcon', label: 'Fault', glyph: '✕' },
  disabled: { tone: 'info', icon: 'NoSymbolIcon', label: 'Disabled', glyph: '▬' },
};

export function PortStateBadge({ state }: { state: PortState }) {
  const m = PORT_STATE_META[state];
  return (
    <Badge tone={m.tone} icon={m.icon}>
      {m.label}
    </Badge>
  );
}