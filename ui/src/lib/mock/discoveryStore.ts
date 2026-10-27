import { ApiError } from '@/lib/apiError';
import type { ApproveBody, DiscoveryScan, UnapprovedDevice } from '@/lib/contract';
import { DISCOVERED_SEED } from '@/lib/mock/discoveredSeed';

let devices: UnapprovedDevice[] = [];
let scans: DiscoveryScan[] = [];

export function resetDiscoveryStore(): void {
  devices = DISCOVERED_SEED.map((device) => ({ ...device, suggested: { ...device.suggested } }));
  scans = [
    {
      id: 'scan-100',
      target: 'prefix',
      value: '10.22.14.0/24',
      status: 'finished',
      startedAt: '2026-10-27T06:00:00Z',
      finishedAt: '2026-10-27T06:04:12Z',
      message: 'Scheduled scan of NetBox prefixes tagged ie-scan.',
    },
  ];
}

resetDiscoveryStore();

export function listUnapproved(): UnapprovedDevice[] {
  return devices.map((device) => ({ ...device, suggested: { ...device.suggested } }));
}

export function approveUnapproved(id: string, body: ApproveBody): { id: string; ok: boolean } {
  if (!body.role?.trim() || !body.site?.trim()) {
    throw new ApiError(
      400,
      'invalid_approve',
      'Role and site are required to create the device in NetBox.'
    );
  }
  const device = devices.find((item) => item.id === id);
  if (!device)
    throw new ApiError(404, 'not_found', 'That discovered device is no longer in the queue.');
  devices = devices.filter((item) => item.id !== id);
  return { id, ok: true };
}

export function rejectUnapproved(id: string): { id: string; ok: boolean } {
  const device = devices.find((item) => item.id === id);
  if (!device)
    throw new ApiError(404, 'not_found', 'That discovered device is no longer in the queue.');
  devices = devices.filter((item) => item.id !== id);
  return { id, ok: true };
}

export function listScans(): DiscoveryScan[] {
  return scans.map((scan) => ({ ...scan }));
}

export function startScan(target: string, value: string): DiscoveryScan {
  const trimmed = value.trim();
  if (target !== 'ip' && target !== 'prefix') {
    throw new ApiError(400, 'invalid_scan', 'Target must be ip or prefix.');
  }
  const ip = /^(?:\d{1,3}\.){3}\d{1,3}$/;
  const prefix = /^(?:\d{1,3}\.){3}\d{1,3}\/\d{1,2}$/;
  if (target === 'ip' && !ip.test(trimmed))
    throw new ApiError(400, 'invalid_scan', 'Enter an IPv4 address.');
  if (target === 'prefix' && !prefix.test(trimmed)) {
    throw new ApiError(400, 'invalid_scan', 'Enter an IPv4 prefix, for example 10.22.14.0/24.');
  }
  const scan: DiscoveryScan = {
    id: `scan-${scans.length + 101}`,
    target,
    value: trimmed,
    status: 'finished',
    startedAt: new Date().toISOString(),
    finishedAt: new Date().toISOString(),
    message:
      target === 'prefix'
        ? 'Queued a Netdisco walk of that prefix. Devices that are not in NetBox will show up here.'
        : 'Probed that address. If it answers SNMP and is not in NetBox, it will show up here.',
  };
  scans = [scan, ...scans].slice(0, 20);
  if (target === 'ip' && !devices.some((device) => device.ip === trimmed)) {
    const now = new Date().toISOString();
    devices = [
      {
        id: `disc-${trimmed.split('.').join('-')}`,
        ip: trimmed,
        sysName: undefined,
        hostname: undefined,
        firstSeen: now,
        lastSeen: now,
        suggested: {},
      },
      ...devices,
    ];
  }
  return scan;
}
