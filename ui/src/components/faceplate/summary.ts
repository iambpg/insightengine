import type { PortState } from '@/lib/types';

export const SNMP_MISSING_HINT = 'no SNMP interface data from Prometheus for this device';

export const SUMMARY_STATES = ['up', 'down', 'disabled', 'unknown'] as const;

export function countPorts(ports: { state: string }[]): Record<string, number> {
  return ports.reduce<Record<string, number>>((acc, port) => {
    acc[port.state] = (acc[port.state] ?? 0) + 1;
    return acc;
  }, {});
}

/** Visible faceplate line: up, down, disabled, unknown, then the SNMP sample time. */
export function faceplateSummaryLine(counts: Record<string, number>, snmpAt?: string): string {
  const parts = SUMMARY_STATES.map((state) => `${counts[state] || 0} ${state}`);
  if (counts.fault) parts.push(`${counts.fault} fault`);
  if (counts.warning) parts.push(`${counts.warning} warning`);
  let text = parts.join(' · ');
  if (snmpAt) text += ` · SNMP ${snmpAt}`;
  return text;
}

export function isPortState(value: string): value is PortState {
  return value === 'up' || value === 'down' || value === 'warning' || value === 'fault' || value === 'disabled' || value === 'unknown';
}
