import type { AlertItem, DeviceHealth, DeviceRow, SiteRow } from '@/lib/types';

export type LaneId = 'shop' | 'wifi' | 'wan' | 'other';
export type LaneState = 'working' | 'attention' | 'down' | 'absent';

export interface LaneView {
  id: LaneId;
  title: string;
  state: LaneState;
  status: string;
  detail: string;
  notes: { title: string; detail: string; meta: string }[];
}

export interface ProblemView {
  id: string;
  title: string;
  detail: string;
  devices: { id: string; hostname: string; formFactor: string }[];
}

export interface SiteStory {
  verdict: { heading: string; detail: string };
  lanes: LaneView[];
  problems: ProblemView[];
  about: { label: string; value: string }[];
}

const LANE_META: { id: LaneId; title: string; noun: string; nouns: string }[] = [
  { id: 'shop', title: 'LAN Network', noun: 'switch', nouns: 'switches' },
  { id: 'wifi', title: 'Wi-Fi Network', noun: 'wireless device', nouns: 'wireless devices' },
  { id: 'wan', title: 'SDWAN/WAN Network', noun: 'WAN device', nouns: 'WAN devices' },
  { id: 'other', title: 'Other equipment', noun: 'device', nouns: 'devices' },
];

export function laneOf(device: Pick<DeviceRow, 'role' | 'formFactor'>): LaneId {
  const blob = `${device.role} ${device.formFactor}`.toLowerCase();
  if (/access point|ceiling-ap|wireless/.test(blob)) return 'wifi';
  if (/firewall|sd-?wan|router/.test(blob)) return 'wan';
  if (/switch|chassis/.test(blob)) return 'shop';
  return 'other';
}

function count(n: number, singular: string, plural = `${singular}s`): string {
  return `${n} ${n === 1 ? singular : plural}`;
}

function answering(devices: DeviceRow[]): DeviceRow[] {
  return devices.filter((device) => device.health !== 'unreachable');
}

function laneState(devices: DeviceRow[]): LaneState {
  if (devices.length === 0) return 'absent';
  const silent = devices.filter((device) => device.health === 'unreachable').length;
  const faults = answering(devices).reduce((sum, device) => sum + device.portsFault, 0);
  const flagged = answering(devices).some((device) => device.health === 'critical' || device.health === 'warning');
  if (silent === devices.length) return 'down';
  if (silent > 0 || faults > 0 || flagged) return 'attention';
  return 'working';
}

const STATUS: Record<LaneState, string> = {
  working: 'Working',
  attention: 'Needs attention',
  down: 'Not answering',
  absent: 'Not monitored',
};

function laneDetail(id: LaneId, devices: DeviceRow[], noun: string, nouns: string): string {
  if (devices.length === 0) {
    if (id === 'shop') return 'No switches are recorded at this site.';
    if (id === 'wifi') return 'No wireless devices are recorded at this site.';
    if (id === 'wan') return 'No SD-WAN or WAN device is recorded at this site, so the path out of the store is not monitored here.';
    return 'No other equipment is recorded at this site.';
  }
  const silent = devices.filter((device) => device.health === 'unreachable');
  const live = answering(devices);
  const faults = live.reduce((sum, device) => sum + device.portsFault, 0);
  if (silent.length === devices.length) {
    const lead = devices.length === 1
      ? `The ${noun} is not answering.`
      : `None of the ${count(devices.length, noun, nouns)} are answering.`;
    return `${lead} Prometheus has no fresh probe or SNMP sample, so this part of the site cannot be confirmed.`;
  }
  const parts: string[] = [];
  if (silent.length === 0) {
    parts.push(devices.length === 1 ? `The ${noun} is answering.` : `All ${count(devices.length, noun, nouns)} are answering.`);
  } else {
    const silentVerb = silent.length === 1 ? 'is' : 'are';
    const liveVerb = live.length === 1 ? 'is' : 'are';
    parts.push(`${count(silent.length, noun, nouns)} of ${devices.length} ${silentVerb} not answering. ${count(live.length, noun, nouns)} ${liveVerb} answering.`);
  }
  if (faults > 0) parts.push(`${count(faults, 'port')} on the answering devices ${faults === 1 ? 'is' : 'are'} faulted.`);
  else if (id === 'shop' && live.some((device) => device.portsTotal > 0)) parts.push('No faulted ports on the switches that answered.');
  const flagged = live.filter((device) => device.health === 'critical' || device.health === 'warning');
  if (flagged.length > 0) {
    const word = flagged.some((device) => device.health === 'critical') ? 'a critical state' : 'a warning';
    parts.push(`${count(flagged.length, noun, nouns)} ${flagged.length === 1 ? 'is' : 'are'} still reporting ${word}.`);
  }
  return parts.join(' ');
}

function groupProblems(devices: DeviceRow[], health: DeviceHealth, title: (role: string, rows: DeviceRow[]) => string, detail: string): ProblemView[] {
  const groups = new Map<string, DeviceRow[]>();
  devices.filter((device) => device.health === health).forEach((device) => {
    const rows = groups.get(device.role) ?? [];
    rows.push(device);
    groups.set(device.role, rows);
  });
  return Array.from(groups.entries()).map(([role, rows]) => ({
    id: `${health}-${role}`,
    title: title(role, rows),
    detail,
    devices: rows.map((device) => ({ id: device.id, hostname: device.hostname, formFactor: device.formFactor })),
  }));
}

export function describeSite(site: SiteRow, devices: DeviceRow[], alerts: AlertItem[]): SiteStory {
  const open = alerts.filter((alert) => alert.status === 'open' && (alert.siteId === site.id || alert.site.toLowerCase() === site.name.toLowerCase()));
  const lanes = LANE_META.filter((meta) => meta.id !== 'other' || devices.some((device) => laneOf(device) === 'other')).map((meta) => {
    const rows = devices.filter((device) => laneOf(device) === meta.id);
    const state = laneState(rows);
    return {
      id: meta.id,
      title: meta.title,
      state,
      status: STATUS[state],
      detail: laneDetail(meta.id, rows, meta.noun, meta.nouns),
      notes: rows
        .filter((device) => device.health !== 'healthy' || device.portsFault > 0)
        .map((device) => ({
          title: device.hostname,
          detail: device.portsFault > 0 ? `${device.role} · ${device.portsFault} faulted ports` : device.role,
          meta: device.health,
        })),
    };
  });

  const silent = devices.filter((device) => device.health === 'unreachable');
  const live = answering(devices);
  const faults = live.filter((device) => device.portsFault > 0);
  const flagged = live.filter((device) => device.health === 'critical' || device.health === 'warning');
  const problems: ProblemView[] = [
    ...groupProblems(devices, 'unreachable', (role, rows) => `${role}: ${count(rows.length, 'device')} not answering`, 'Prometheus has no fresh probe or SNMP sample for these devices.'),
    ...faults.map((device) => ({
      id: `fault-${device.id}`,
      title: `${device.hostname} has ${count(device.portsFault, 'faulted port')}`,
      detail: device.role,
      devices: [{ id: device.id, hostname: device.hostname, formFactor: device.formFactor }],
    })),
    ...flagged.map((device) => ({
      id: `health-${device.id}`,
      title: `${device.hostname} is ${device.health}`,
      detail: device.role,
      devices: [{ id: device.id, hostname: device.hostname, formFactor: device.formFactor }],
    })),
    ...open.map((alert) => ({
      id: `alert-${alert.id}`,
      title: alert.title,
      detail: [alert.deviceHostname, alert.detail].filter(Boolean).join(' · '),
      devices: alert.deviceId ? [{ id: alert.deviceId, hostname: alert.deviceHostname, formFactor: alert.formFactor }] : [],
    })),
  ];

  const roles = new Map<string, number>();
  devices.forEach((device) => roles.set(device.role, (roles.get(device.role) ?? 0) + 1));
  const about = [
    { label: 'Region', value: site.region || '—' },
    { label: 'City', value: site.city && site.city !== site.name ? site.city : '—' },
    { label: 'Devices', value: String(devices.length) },
    { label: 'Roles', value: roles.size ? Array.from(roles.entries()).map(([role, n]) => `${role} ${n}`).join(', ') : '—' },
    { label: 'Open alerts', value: String(open.length) },
    { label: 'Last discovery', value: site.lastDiscovery || '—' },
  ];

  return { verdict: verdict(devices, silent.length, faults.length, flagged, open.length), lanes, problems, about };
}

function verdict(devices: DeviceRow[], silent: number, faultDevices: number, flagged: DeviceRow[], openAlerts: number): { heading: string; detail: string } {
  if (devices.length === 0) {
    return {
      heading: 'Nothing to judge yet',
      detail: 'This site has no devices yet, so whether the store is working cannot be seen from here.',
    };
  }
  const live = devices.length - silent;
  if (silent > 0) {
    return {
      heading: 'Not working as expected',
      detail: `${count(silent, 'device')} ${silent === 1 ? 'is' : 'are'} not answering, so that part of the store cannot be confirmed. ${count(live, 'device')} ${live === 1 ? 'is' : 'are'} answering.`,
    };
  }
  if (flagged.some((device) => device.health === 'critical')) {
    return {
      heading: 'Needs attention now',
      detail: `${count(flagged.filter((device) => device.health === 'critical').length, 'device')} ${flagged.filter((device) => device.health === 'critical').length === 1 ? 'is' : 'are'} critical. The rest of the site is still answering.`,
    };
  }
  if (flagged.length > 0 || faultDevices > 0 || openAlerts > 0) {
    const bits = [
      flagged.length ? count(flagged.length, 'warning') : '',
      faultDevices ? `${count(faultDevices, 'device')} with faulted ports` : '',
      openAlerts ? count(openAlerts, 'open alert') : '',
    ].filter(Boolean);
    return {
      heading: 'Working, with issues',
      detail: `Devices are answering. ${bits.join(', ')} still need a look.`,
    };
  }
  return {
    heading: 'Working as expected',
    detail: 'Every device is answering, no ports are faulted, and there are no open alerts for this site.',
  };
}
