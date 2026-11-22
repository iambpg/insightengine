import type { DeviceHealth } from '@/lib/types';
import { devicePath } from '@/lib/apiMode';

/** Device page with the Health section open, pre-filtered when the badge has a chip. */
export function deviceHealthPath(id: string, formFactor: string, health: DeviceHealth): string {
  const base = devicePath(id, formFactor);
  const severity = health === 'critical' || health === 'warning' ? health : health === 'unreachable' ? 'critical' : '';
  const extra = severity ? `tab=health&severity=${severity}` : 'tab=health';
  const join = base.includes('?') ? '&' : '?';
  return `${base}${join}${extra}`;
}

export function accessPointId(netboxId: string | undefined, name: string): string {
  const id = (netboxId || '').trim();
  if (id) return id;
  return `ap:${name}`;
}
