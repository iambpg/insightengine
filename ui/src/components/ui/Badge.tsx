import React from 'react';
import Link from 'next/link';
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

export function StatusBadge({ status }: { status?: string }) {
  const value = (status || '').trim();
  if (!value) return null;
  const key = value.toLowerCase();
  const tone: Tone = key === 'active' ? 'success' : key === 'offline' || key === 'failed' || key === 'netdisco-only' ? 'warning' : 'neutral';
  const label = key === 'netdisco-only' ? 'Netdisco only' : value;
  return <Badge tone={tone}>{label}</Badge>;
}

export function HealthBadge({ health, href }: { health: DeviceHealth; href?: string }) {
  const m = HEALTH_META[health] ?? HEALTH_META.healthy;
  const badge = (
    <Badge tone={m.tone} icon={m.icon}>
      {m.label}
    </Badge>
  );
  if (!href) return badge;
  return (
    <Link
      href={href}
      className="inline-flex rounded-full focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
      aria-label={`${m.label}. Open health details`}
    >
      {badge}
    </Link>
  );
}

export const PORT_STATE_META: Record<PortState, { tone: Tone; icon: string; label: string; glyph: string }> = {
  up: { tone: 'success', icon: 'CheckCircleIcon', label: 'Up', glyph: '●' },
  down: { tone: 'neutral', icon: 'MinusCircleIcon', label: 'Down', glyph: '○' },
  warning: { tone: 'warning', icon: 'ExclamationTriangleIcon', label: 'Warning', glyph: '▲' },
  fault: { tone: 'destructive', icon: 'XCircleIcon', label: 'Fault', glyph: '✕' },
  disabled: { tone: 'info', icon: 'NoSymbolIcon', label: 'Disabled', glyph: '▬' },
  unknown: { tone: 'neutral', icon: 'QuestionMarkCircleIcon', label: 'Unknown', glyph: '?' },
};

export function PortStateBadge({ state }: { state: PortState }) {
  const m = PORT_STATE_META[state];
  return (
    <Badge tone={m.tone} icon={m.icon}>
      {m.label}
    </Badge>
  );
}