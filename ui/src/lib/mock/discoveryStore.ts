import { ApiError } from '@/lib/apiError';
import type { ApproveBody, DeviceDiscoveryJob, DiscoveryScan, UnapprovedDevice } from '@/lib/contract';
import { DISCOVERED_SEED } from '@/lib/mock/discoveredSeed';

let devices: UnapprovedDevice[] = [];
let scans: DiscoveryScan[] = [];
let deviceJobs: DeviceDiscoveryJob[] = [];

export function resetDiscoveryStore(): void {
  deviceJobs = [];
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

export function setSites(ids: string[], site: string): { ok: boolean; site: string; updated: string[] } {
  const chosen = site.trim();
  if (!chosen) throw new ApiError(400, 'bad_body', 'site is required');
  const updated: string[] = [];
  for (const id of ids) {
    const device = devices.find((item) => item.id === id);
    if (!device) continue;
    device.suggested = { ...device.suggested, site: chosen };
    updated.push(id);
  }
  return { ok: true, site: chosen, updated };
}

export function setTenants(ids: string[], tenant: string): { ok: boolean; tenant: string; updated: string[] } {
  const chosen = tenant.trim();
  const updated: string[] = [];
  for (const id of ids) {
    const device = devices.find((item) => item.id === id);
    if (!device) continue;
    device.suggested = { ...device.suggested, tenant: chosen };
    updated.push(id);
  }
  return { ok: true, tenant: chosen, updated };
}

export function setRoles(ids: string[], role: string): { ok: boolean; role: string; updated: string[] } {
  const chosen = role.trim();
  if (!chosen) throw new ApiError(400, 'bad_body', 'role is required');
  const updated: string[] = [];
  for (const id of ids) {
    const device = devices.find((item) => item.id === id);
    if (!device) continue;
    device.suggested = { ...device.suggested, role: chosen };
    updated.push(id);
  }
  return { ok: true, role: chosen, updated };
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

export function discoverDevice(ip: string, neighbours = false): DeviceDiscoveryJob {
  const trimmed = ip.trim();
  if (!/^(?:\d{1,3}\.){3}\d{1,3}$/.test(trimmed)) {
    throw new ApiError(400, 'invalid_scan', 'Enter an IPv4 address.');
  }
  const now = new Date().toISOString();
  const job: DeviceDiscoveryJob = {
    id: `job-${deviceJobs.length + 1}`,
    ip: trimmed,
    status: 'done',
    neighbours,
    startedAt: now,
    finishedAt: now,
    message: 'SNMP reachable via profile default',
    steps: [
      { name: 'snmp', status: 'done', message: 'SNMP reachable via profile default' },
      { name: 'discover', status: 'done', message: 'Discover finished.' },
      { name: 'macsuck', status: 'done', message: 'MAC suck finished.' },
      { name: 'arpnip', status: 'done', message: 'ARP collection finished.' },
    ],
  };
  deviceJobs = [job, ...deviceJobs];
  if (!devices.some((device) => device.ip === trimmed)) {
    devices = [
      {
        id: `disc-${trimmed.split('.').join('-')}`,
        ip: trimmed,
        firstSeen: now,
        lastSeen: now,
        suggested: {},
      },
      ...devices,
    ];
  }
  return { ...job, steps: job.steps.map((step) => ({ ...step })) };
}

export function getDeviceDiscovery(id: string): DeviceDiscoveryJob {
  const job = deviceJobs.find((item) => item.id === id);
  if (!job) throw new ApiError(404, 'not_found', 'unknown discovery job');
  return { ...job, steps: job.steps.map((step) => ({ ...step })) };
}
