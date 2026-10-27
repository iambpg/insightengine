import type {
  AlertItem,
  ChassisModule,
  DeviceDetailData,
  DeviceHealth,
  DeviceRow,
  FaceplateDevice,
  FormFactor,
  PortInfo,
  PortState,
  PortType,
  RadioInfo,
  SeriesPoint,
  SiteRow,
  StackMember,
  UserRow,
  WebhookDelivery,
} from './types';
import { FW_MODELS, FW_MODEL_LIST } from '@/components/faceplate/layouts/FirewallModels';

// ---------- deterministic pseudo-random (SSR/CSR safe) ----------
function seeded(seed: number) {
  let s = seed % 2147483647;
  if (s <= 0) s += 2147483646;
  return () => {
    s = (s * 16807) % 2147483647;
    return (s - 1) / 2147483646;
  };
}

const NEIGHBOURS = [
  'dist-sw-01', 'dist-sw-02', 'core-rtr-01', 'ap-fl2-014', 'srv-esx-07',
  'cam-gw-03', 'ups-mgmt-01', 'wlc-edge-01', 'printer-hub-02', 'voip-gw-01',
];

function pickState(r: number, bias: 'clean' | 'mixed' | 'rough'): PortState {
  if (bias === 'clean') {
    if (r < 0.62) return 'up';
    if (r < 0.9) return 'down';
    if (r < 0.96) return 'warning';
    return 'disabled';
  }
  if (bias === 'mixed') {
    if (r < 0.5) return 'up';
    if (r < 0.72) return 'down';
    if (r < 0.86) return 'warning';
    if (r < 0.93) return 'fault';
    return 'disabled';
  }
  if (r < 0.34) return 'up';
  if (r < 0.52) return 'down';
  if (r < 0.7) return 'warning';
  if (r < 0.88) return 'fault';
  return 'disabled';
}

export function buildPorts(
  count: number,
  opts: {
    prefix: string;
    type: PortType;
    speed: string;
    seed: number;
    bias: 'clean' | 'mixed' | 'rough';
    poe?: boolean;
    startAt?: number;
  }
): PortInfo[] {
  const rnd = seeded(opts.seed);
  const start = opts.startAt ?? 1;
  return Array.from({ length: count }, (_, i) => {
    const state = pickState(rnd(), opts.bias);
    const n = start + i;
    const utilBase = state === 'up' ? 4 + rnd() * 70 : state === 'warning' ? 60 + rnd() * 35 : state === 'fault' ? rnd() * 15 : 0;
    const errors =
      state === 'warning' ? Math.floor(3 + rnd() * 140) : state === 'fault' ? Math.floor(200 + rnd() * 4800) : state === 'up' ? Math.floor(rnd() * 2) : 0;
    const neighbour =
      state === 'up' || state === 'warning'
        ? { device: NEIGHBOURS[Math.floor(rnd() * NEIGHBOURS.length)], port: `Gi1/0/${Math.floor(1 + rnd() * 47)}` }
        : undefined;
    return {
      id: `${opts.prefix}-${n}`,
      name: `${opts.prefix}${n}`,
      type: opts.type,
      speed: state === 'down' || state === 'disabled' ? '—' : opts.speed,
      state,
      utilisation: Math.round(utilBase * 10) / 10,
      errors,
      neighbour,
      poe: opts.poe,
    };
  });
}

// ---------- faceplate descriptions ----------
function sw24(seed = 24): FaceplateDevice {
  const copper = buildPorts(24, { prefix: 'Gi1/0/', type: 'RJ45', speed: '1 Gbps', seed, bias: 'mixed', poe: true });
  const uplinks = buildPorts(4, { prefix: 'Te1/1/', type: 'SFP+', speed: '10 Gbps', seed: seed + 3, bias: 'clean' });
  uplinks[0].state = 'up';
  uplinks[0].speed = '10 Gbps';
  uplinks[0].utilisation = 62;
  uplinks[0].neighbour = { device: 'dist-sw-02', port: 'Te1/0/13' };
  return { form_factor: 'access-switch-24', role: 'Access switch', ports: [...copper, ...uplinks] };
}

function sw48(seed = 48): FaceplateDevice {
  const copper = buildPorts(48, { prefix: 'Gi1/0/', type: 'RJ45', speed: '1 Gbps', seed, bias: 'mixed', poe: false });
  const uplinks = buildPorts(4, { prefix: 'Te1/1/', type: 'SFP+', speed: '10 Gbps', seed: seed + 5, bias: 'clean' });
  uplinks[1].state = 'warning';
  uplinks[1].errors = 38;
  return { form_factor: 'access-switch-48', role: 'Access switch', ports: [...copper, ...uplinks] };
}

function stack3(): FaceplateDevice {
  const mk = (n: number, bias: 'clean' | 'mixed' | 'rough', seed: number): PortInfo[] => {
    const copper = buildPorts(24, { prefix: `Gi${n}/0/`, type: 'RJ45', speed: '1 Gbps', seed, bias, poe: true });
    const up = buildPorts(4, { prefix: `Te${n}/1/`, type: 'SFP+', speed: '10 Gbps', seed: seed + 9, bias: 'clean' });
    return [...copper, ...up];
  };
  const members: StackMember[] = [
    { id: 'm1', number: 1, health: 'healthy', note: 'Healthy', ports: mk(1, 'clean', 11) },
    { id: 'm2', number: 2, health: 'warning', note: 'Warning: fan, 3 ports with errors', ports: mk(2, 'mixed', 22), fanWarning: true },
    { id: 'm3', number: 3, health: 'fault', note: 'Fault: PSU, 4 ports faulted', ports: mk(3, 'rough', 33), psuFault: true },
  ];
  return { form_factor: 'switch-stack', role: 'Switch stack', members };
}

function ap(): FaceplateDevice {
  const radios: RadioInfo[] = [
    { id: 'r1', band: '2.4 GHz', channel: 6, state: 'up', clients: 14, utilisation: 38, standard: '802.11ax (Wi-Fi 6)', channelWidth: '20 MHz', txPower: '14 dBm', noiseFloor: '-94 dBm', avgRssi: '-58 dBm', retryRate: 6, ssids: ['Corp-WiFi', 'IoT'], throughput: '42 Mbps' },
    { id: 'r2', band: '5 GHz', channel: 100, state: 'warning', clients: 41, utilisation: 83, standard: '802.11ax (Wi-Fi 6)', channelWidth: '80 MHz', txPower: '17 dBm', noiseFloor: '-90 dBm', avgRssi: '-64 dBm', retryRate: 19, ssids: ['Corp-WiFi', 'Guest'], throughput: '388 Mbps' },
    { id: 'r3', band: '6 GHz', channel: 37, state: 'up', clients: 6, utilisation: 12, standard: '802.11be (Wi-Fi 7)', channelWidth: '160 MHz', txPower: '15 dBm', noiseFloor: '-96 dBm', avgRssi: '-55 dBm', retryRate: 2, ssids: ['Corp-WiFi'], throughput: '96 Mbps' },
  ];
  const ports: PortInfo[] = [
    { id: 'eth0', name: 'ETH0/PoE', type: 'RJ45', speed: '2.5 Gbps', state: 'up', utilisation: 34, errors: 0, poe: true, neighbour: { device: 'edge-sw-14', port: 'Gi1/0/12' } },
    { id: 'console', name: 'CONSOLE', type: 'CONSOLE', speed: '—', state: 'down', utilisation: 0, errors: 0 },
  ];
  return { form_factor: 'ceiling-ap', role: 'Ceiling access point', ports, radios, apState: 'up' };
}

function wlc(): FaceplateDevice {
  const sfp = buildPorts(8, { prefix: 'Te0/', type: 'SFP+', speed: '10 Gbps', seed: 77, bias: 'clean' });
  sfp[0].state = 'up'; sfp[0].utilisation = 48; sfp[1].state = 'up'; sfp[1].utilisation = 51;
  sfp[2].state = 'warning'; sfp[2].errors = 22; sfp[2].utilisation = 74;
  const mgmt: PortInfo = { id: 'mgmt', name: 'MGMT', type: 'MGMT', speed: '1 Gbps', state: 'up', utilisation: 2, errors: 0 };
  const ha: PortInfo = { id: 'ha', name: 'HA', type: 'RJ45', speed: '1 Gbps', state: 'up', utilisation: 1, errors: 0, label: 'Redundancy' };
  return { form_factor: 'wireless-controller', role: 'Wireless controller', ports: [...sfp, mgmt, ha] };
}

function fw(): FaceplateDevice {
  const rj = buildPorts(8, { prefix: 'Eth', type: 'RJ45', speed: '1 Gbps', seed: 91, bias: 'clean' });
  rj[0].state = 'up'; rj[0].utilisation = 66;
  const sfp = buildPorts(2, { prefix: 'Te', type: 'SFP+', speed: '10 Gbps', seed: 92, bias: 'clean' });
  sfp[0].state = 'up'; sfp[0].utilisation = 41; sfp[1].state = 'fault'; sfp[1].errors = 912;
  const mgmt: PortInfo = { id: 'mgmt', name: 'MGMT', type: 'MGMT', speed: '1 Gbps', state: 'up', utilisation: 1, errors: 0 };
  const ha: PortInfo = { id: 'ha', name: 'HA', type: 'RJ45', speed: '1 Gbps', state: 'up', utilisation: 3, errors: 0 };
  return { form_factor: 'firewall', role: 'Firewall', ports: [...rj, ...sfp, mgmt, ha] };
}

// Model-specific firewall: port counts follow the model's own layout. Artwork carries no brand marks.
function fwModel(modelId: string): FaceplateDevice {
  const spec = FW_MODELS[modelId];
  const seed = 200 + modelId.length * 17 + modelId.charCodeAt(modelId.length - 1);
  const isFg = spec.vendor === 'fortigate';
  const ports: PortInfo[] = [];
  const rjPrefix = isFg ? 'port' : 'ethernet1/';
  const rj = buildPorts(spec.rj45, { prefix: rjPrefix, type: 'RJ45', speed: '1 Gbps', seed, bias: 'clean' });
  rj.forEach((p) => { p.name = isFg ? p.name : `port${p.name.replace('ethernet1/', '')}`; });
  if (rj[0]) { rj[0].state = 'up'; rj[0].speed = '1 Gbps'; rj[0].utilisation = 58; }
  ports.push(...rj);
  const sfpStart = spec.rj45 + 1;
  const sfp = buildPorts(spec.sfp, { prefix: 'sfp', type: 'SFP', speed: '1 Gbps', seed: seed + 1, bias: 'clean', startAt: 1 });
  sfp.forEach((p, i) => { p.name = `port${sfpStart + i}`; p.id = `sfp-${i + 1}`; });
  ports.push(...sfp);
  const sfppStart = sfpStart + spec.sfp;
  const sfpp = buildPorts(spec.sfpPlus, { prefix: 'sfpp', type: 'SFP+', speed: '10 Gbps', seed: seed + 2, bias: 'clean', startAt: 1 });
  sfpp.forEach((p, i) => { p.name = `port${sfppStart + i}`; p.id = `sfpp-${i + 1}`; });
  if (sfpp[0]) { sfpp[0].state = 'up'; sfpp[0].speed = '10 Gbps'; sfpp[0].utilisation = 44; }
  ports.push(...sfpp);
  const qsfpStart = sfppStart + spec.sfpPlus;
  const qsfp = buildPorts(spec.qsfp, { prefix: 'qsfp', type: 'QSFP', speed: '40 Gbps', seed: seed + 3, bias: 'clean', startAt: 1 });
  qsfp.forEach((p, i) => { p.name = `port${qsfpStart + i}`; p.id = `qsfp-${i + 1}`; });
  ports.push(...qsfp);
  if (spec.mgmt) ports.push({ id: 'mgmt', name: 'MGMT', type: 'MGMT', speed: '1 Gbps', state: 'up', utilisation: 1, errors: 0 });
  if (spec.ha) ports.push({ id: 'ha', name: 'HA', type: 'RJ45', speed: '1 Gbps', state: 'up', utilisation: 2, errors: 0, label: 'High availability' });
  return { form_factor: 'firewall', role: 'Firewall', ports, model: modelId, modelName: spec.label };
}

function router(): FaceplateDevice {
  const rj = buildPorts(4, { prefix: 'Gi0/0/', type: 'RJ45', speed: '1 Gbps', seed: 55, bias: 'clean' });
  rj[0].state = 'up'; rj[0].utilisation = 83; rj[0].neighbour = { device: 'isp-edge-01', port: 'Gi0/1' };
  const sfp = buildPorts(2, { prefix: 'Te0/1/', type: 'SFP', speed: '1 Gbps', seed: 56, bias: 'clean' });
  sfp[0].state = 'up'; sfp[0].utilisation = 55;
  const mod = buildPorts(2, { prefix: 'Gi0/2/', type: 'RJ45', speed: '1 Gbps', seed: 57, bias: 'mixed' });
  return { form_factor: 'branch-router', role: 'Branch router', ports: [...rj, ...sfp, ...mod], moduleSlotFilled: true };
}

function chassis(): FaceplateDevice {
  const lc = (slot: string, seed: number, bias: 'clean' | 'mixed' | 'rough'): ChassisModule => ({
    id: `slot-${slot}`,
    kind: 'linecard',
    slot,
    label: `Line card ${slot} · 48p`,
    state: bias === 'rough' ? 'fault' : bias === 'mixed' ? 'warning' : 'up',
    ports: buildPorts(48, { prefix: `${slot}/`, type: 'RJ45', speed: '1 Gbps', seed, bias }),
  });
  const modules: ChassisModule[] = [
    { id: 'fan1', kind: 'fan', slot: 'FAN1', label: 'Fan tray 1', state: 'up', ports: [] },
    lc('1', 101, 'clean'),
    lc('2', 102, 'mixed'),
    {
      id: 'slot-3', kind: 'supervisor', slot: '3', label: 'Supervisor · active', state: 'up',
      ports: buildPorts(4, { prefix: 'S3/', type: 'SFP+', speed: '10 Gbps', seed: 103, bias: 'clean' }),
    },
    {
      id: 'slot-4', kind: 'supervisor', slot: '4', label: 'Supervisor · standby', state: 'up',
      ports: buildPorts(4, { prefix: 'S4/', type: 'SFP+', speed: '10 Gbps', seed: 104, bias: 'clean' }),
    },
    lc('5', 105, 'rough'),
    lc('6', 106, 'mixed'),
    { id: 'fan2', kind: 'fan', slot: 'FAN2', label: 'Fan tray 2', state: 'up', ports: [] },
    { id: 'psu1', kind: 'psu', slot: 'PSU1', label: 'PSU 1', state: 'up', ports: [] },
    { id: 'psu2', kind: 'psu', slot: 'PSU2', label: 'PSU 2', state: 'up', ports: [] },
    { id: 'psu3', kind: 'psu', slot: 'PSU3', label: 'PSU 3', state: 'warning', ports: [] },
    { id: 'psu4', kind: 'psu', slot: 'PSU4', label: 'PSU 4', state: 'up', ports: [] },
  ];
  return { form_factor: 'modular-chassis', role: 'Modular chassis', modules };
}

function generic(count: number): FaceplateDevice {
  const ports = buildPorts(count, { prefix: 'Port', type: 'RJ45', speed: '1 Gbps', seed: 303, bias: 'clean' });
  return { form_factor: 'generic', role: 'Unclassified device', ports };
}

export const FACEPLATE_SAMPLES: Record<string, { label: string; build: () => FaceplateDevice }> = {
  'access-switch-24': { label: 'Access switch · 24p PoE', build: () => sw24() },
  'access-switch-48': { label: 'Access switch · 48p', build: () => sw48() },
  'switch-stack': { label: 'Switch stack · 3 members', build: () => stack3() },
  'ceiling-ap': { label: 'Ceiling access point', build: () => ap() },
  'wireless-controller': { label: 'Wireless controller', build: () => wlc() },
  firewall: { label: 'Firewall', build: () => fw() },
  'branch-router': { label: 'Branch router', build: () => router() },
  'modular-chassis': { label: 'Modular chassis', build: () => chassis() },
  generic: { label: 'Generic · 16 ports', build: () => generic(16) },
  ...Object.fromEntries(
    FW_MODEL_LIST.map((m) => [m.id, { label: m.label, build: () => fwModel(m.id) }]),
  ),
};

export function buildFaceplateFor(form: string): FaceplateDevice {
  const sample = FACEPLATE_SAMPLES[form] ?? FACEPLATE_SAMPLES.generic;
  return sample.build();
}

// ---------- device list ----------
const SITE_NAMES = [
  'Rotterdam-Havenstraat', 'Utrecht-Centrum', 'Eindhoven-Strijp', 'Amsterdam-Zuidas', 'Leiden-Bio',
  'Groningen-Noord', 'Zwolle-Station', 'Breda-Chasse', 'Arnhem-Rijn', 'Haarlem-Spaarne',
  'Tilburg-Spoorzone', 'Maastricht-Randwyck',
];
const ROLES: { role: string; form: FormFactor; model: string }[] = [
  { role: 'Access switch', form: 'access-switch-48', model: 'Series-A 48p' },
  { role: 'Access switch', form: 'access-switch-24', model: 'Series-A 24p PoE' },
  { role: 'Switch stack', form: 'switch-stack', model: 'Series-A stack' },
  { role: 'Access point', form: 'ceiling-ap', model: 'Series-W ceiling' },
  { role: 'Wireless controller', form: 'wireless-controller', model: 'Series-W ctrl' },
  { role: 'Firewall', form: 'firewall', model: 'Series-F 10G' },
  { role: 'Branch router', form: 'branch-router', model: 'Series-R modular' },
  { role: 'Modular chassis', form: 'modular-chassis', model: 'Series-C 6-slot' },
];
const PREFIX: Record<string, string> = {
  'Access switch': 'sw', 'Switch stack': 'stk', 'Access point': 'ap', 'Wireless controller': 'wlc',
  Firewall: 'fw', 'Branch router': 'rtr', 'Modular chassis': 'chs',
};

export const TOTAL_DEVICES = 19840;

export function buildDeviceRow(index: number): DeviceRow {
  const rnd = seeded(index * 7919 + 13);
  const r = ROLES[Math.floor(rnd() * ROLES.length)];
  const siteIdx = Math.floor(rnd() * SITE_NAMES.length);
  const total = r.form === 'access-switch-48' ? 52 : r.form === 'access-switch-24' ? 28 : r.form === 'switch-stack' ? 84 : r.form === 'ceiling-ap' ? 2 : r.form === 'wireless-controller' ? 10 : r.form === 'firewall' ? 12 : r.form === 'branch-router' ? 8 : 214;
  const hv = rnd();
  const health: DeviceHealth = hv < 0.74 ? 'healthy' : hv < 0.88 ? 'warning' : hv < 0.96 ? 'critical' : 'unreachable';
  const fault = health === 'critical' ? Math.max(1, Math.floor(rnd() * 5)) : health === 'unreachable' ? 0 : 0;
  const warn = health === 'warning' ? Math.max(1, Math.floor(rnd() * 4)) : health === 'critical' ? Math.floor(rnd() * 3) : 0;
  const up = health === 'unreachable' ? 0 : Math.max(0, Math.floor(total * (0.35 + rnd() * 0.5)));
  const days = Math.floor(rnd() * 420);
  const hrs = Math.floor(rnd() * 24);
  const pollMin = health === 'unreachable' ? 35 + Math.floor(rnd() * 400) : Math.floor(rnd() * 4);
  const pollSec = Math.floor(rnd() * 59);
  const n = String(1 + (index % 28)).padStart(2, '0');
  return {
    id: `dev-${String(index + 1).padStart(5, '0')}`,
    hostname: `${PREFIX[r.role]}-${SITE_NAMES[siteIdx].split('-')[0].toLowerCase().slice(0, 3)}${String((index % 97) + 1).padStart(2, '0')}-${n}`,
    role: r.role,
    site: SITE_NAMES[siteIdx],
    siteId: `site-${String(siteIdx + 1).padStart(4, '0')}`,
    mgmtIp: `10.${20 + (siteIdx % 8)}.${(index * 3) % 255}.${(index * 11) % 250 + 2}`,
    modelFamily: r.model,
    health,
    portsUp: up,
    portsTotal: total,
    portsWarn: warn,
    portsFault: fault,
    uptime: health === 'unreachable' ? '—' : `${days}d ${hrs}h`,
    lastPoll: health === 'unreachable' ? `${pollMin}m ago` : pollMin === 0 ? `${pollSec}s ago` : `${pollMin}m ${pollSec}s ago`,
    formFactor: r.form,
  };
}

export function buildDeviceRows(from: number, count: number): DeviceRow[] {
  return Array.from({ length: count }, (_, i) => buildDeviceRow(from + i));
}

// ---------- sites ----------
const REGIONS = ['Benelux-West', 'Benelux-North', 'Benelux-South', 'Rhine-East'];
export const TOTAL_SITES = 2014;
export function buildSiteRow(index: number): SiteRow {
  const rnd = seeded(index * 4421 + 5);
  const hv = rnd();
  const health: DeviceHealth = hv < 0.78 ? 'healthy' : hv < 0.91 ? 'warning' : hv < 0.98 ? 'critical' : 'unreachable';
  const cityIdx = index % SITE_NAMES.length;
  const code = String(100 + (index % 899));
  return {
    id: `site-${String(index + 1).padStart(4, '0')}`,
    name: `${SITE_NAMES[cityIdx]}-${code}`,
    region: REGIONS[index % REGIONS.length],
    city: SITE_NAMES[cityIdx].split('-')[0],
    deviceCount: 6 + Math.floor(rnd() * 8),
    health,
    alerts: health === 'healthy' ? 0 : health === 'warning' ? 1 + Math.floor(rnd() * 3) : 3 + Math.floor(rnd() * 6),
    lastDiscovery: `${1 + Math.floor(rnd() * 22)}h ${Math.floor(rnd() * 59)}m ago`,
  };
}
export function buildSiteRows(from: number, count: number): SiteRow[] {
  return Array.from({ length: count }, (_, i) => buildSiteRow(from + i));
}

export function buildSiteDevices(siteIndex: number): DeviceRow[] {
  const rnd = seeded(siteIndex * 131 + 7);
  const count = 6 + Math.floor(rnd() * 5);
  const forms: FormFactor[] = ['access-switch-48', 'access-switch-24', 'switch-stack', 'access-switch-48', 'access-switch-24', 'firewall', 'wireless-controller', 'branch-router', 'access-switch-48', 'ceiling-ap'];
  return Array.from({ length: count }, (_, i) => {
    const base = buildDeviceRow(siteIndex * 20 + i);
    const f = forms[i % forms.length];
    const meta = ROLES.find((x) => x.form === f) ?? ROLES[0];
    return { ...base, formFactor: f, role: meta.role, modelFamily: meta.model, hostname: `${PREFIX[meta.role]}-${SITE_NAMES[siteIndex % SITE_NAMES.length].split('-')[0].toLowerCase().slice(0, 3)}${String(siteIndex % 90 + 1).padStart(2, '0')}-${String(i + 1).padStart(2, '0')}` };
  });
}

// ---------- alerts ----------
const ALERT_TEMPLATES: { severity: AlertItem['severity']; category: string; title: string; detail: string }[] = [
  { severity: 'critical', category: 'Reachability', title: 'Device unreachable', detail: 'No SNMP or ICMP response for the last 3 polling cycles.' },
  { severity: 'critical', category: 'Uplink', title: 'Uplink port down', detail: 'Uplink to distribution lost link; traffic is failing over to the backup path.' },
  { severity: 'critical', category: 'Hardware', title: 'Power supply failure', detail: 'Redundant power supply 2 reports a fault. Device is running on a single supply.' },
  { severity: 'critical', category: 'Hardware', title: 'Fan tray failure', detail: 'Fan 3 stopped. Chassis temperature is rising above the normal range.' },
  { severity: 'warning', category: 'Ports', title: 'Port flapping', detail: 'Interface changed state 14 times in the last 10 minutes.' },
  { severity: 'warning', category: 'Errors', title: 'High CRC error rate', detail: 'Input CRC errors above 0.5% on a downlink port. Check the cable or transceiver.' },
  { severity: 'warning', category: 'Capacity', title: 'High CPU utilisation', detail: 'CPU has stayed above 85% for 15 minutes.' },
  { severity: 'warning', category: 'Capacity', title: 'Uplink utilisation above 80%', detail: 'Sustained utilisation on the uplink for more than 20 minutes.' },
  { severity: 'warning', category: 'Hardware', title: 'Transceiver temperature high', detail: 'SFP+ module temperature is 4°C below its shutdown threshold.' },
  { severity: 'warning', category: 'Wireless', title: 'AP radio channel utilisation high', detail: '5 GHz radio is above 75% channel utilisation with 38 clients.' },
  { severity: 'info', category: 'Configuration', title: 'Configuration changed', detail: 'Running configuration differs from the last backed-up version.' },
  { severity: 'info', category: 'Firmware', title: 'Firmware update available', detail: 'A newer recommended release is available for this model.' },
  { severity: 'info', category: 'Ports', title: 'New neighbour discovered', detail: 'LLDP learned a new neighbour on a previously empty port.' },
];

export function buildAlerts(count = 64): AlertItem[] {
  return Array.from({ length: count }, (_, i) => {
    const rnd = seeded(i * 2909 + 41);
    const t = ALERT_TEMPLATES[Math.floor(rnd() * ALERT_TEMPLATES.length)];
    const siteIdx = Math.floor(rnd() * SITE_NAMES.length);
    const role = ROLES[Math.floor(rnd() * ROLES.length)];
    const code = String(100 + ((siteIdx * 83) % 899));
    const ageMinutes = 2 + Math.floor(rnd() * rnd() * 2600);
    const host = `${PREFIX[role.role]}-${SITE_NAMES[siteIdx].split('-')[0].toLowerCase().slice(0, 3)}${String((siteIdx * 7) % 90 + 1).padStart(2, '0')}-${String(1 + Math.floor(rnd() * 12)).padStart(2, '0')}`;
    const acked = rnd() < 0.14 && t.severity !== 'critical';
    const hh = String(Math.floor(((14 * 60 + 31 - ageMinutes + 2880) % 1440) / 60)).padStart(2, '0');
    const mm = String(((14 * 60 + 31 - ageMinutes + 2880) % 1440) % 60).padStart(2, '0');
    const day = ageMinutes > 14 * 60 + 31 ? '2026-10-26' : '2026-10-27';
    return {
      id: `alert-${String(i + 1).padStart(4, '0')}`,
      severity: t.severity,
      title: t.title,
      detail: t.detail,
      site: `${SITE_NAMES[siteIdx]}-${code}`,
      siteId: `site-${String(siteIdx + 1).padStart(4, '0')}`,
      deviceHostname: host,
      formFactor: role.form,
      category: t.category,
      raisedAt: `${day} ${hh}:${mm}`,
      ageMinutes,
      status: acked ? 'acknowledged' : 'open',
      acknowledgedBy: acked ? 'Marit van der Berg' : undefined,
      acknowledgedAt: acked ? `${day} ${hh}:${mm}` : undefined,
    };
  }).sort((a, b) => a.ageMinutes - b.ageMinutes);
}

// ---------- discovered ----------
export { DISCOVERED_SEED as DISCOVERED } from '@/lib/mock/discoveredSeed';

// ---------- device detail ----------
export function buildDeviceDetail(formKey: string): DeviceDetailData {
  const fp = buildFaceplateFor(formKey);
  const form: FormFactor = fp.form_factor;
  const fwSpec = fp.model ? FW_MODELS[fp.model] : undefined;
  const names: Record<string, string> = {
    'access-switch-24': 'sw-rot04-07', 'access-switch-48': 'sw-utr12-03', 'switch-stack': 'stk-rot04-01',
    'ceiling-ap': 'ap-ams01-114', 'wireless-controller': 'wlc-ein02', firewall: 'fw-ams01-a',
    'branch-router': 'rtr-bre07-01', 'modular-chassis': 'chs-rot01-core', generic: 'dev-lei02-17',
  };
  const stack = form === 'switch-stack';
  const health: DeviceHealth = form === 'switch-stack' || form === 'firewall' || form === 'modular-chassis' ? 'critical' : form === 'access-switch-24' || form === 'ceiling-ap' ? 'warning' : 'healthy';
  return {
    id: 'dev-00417',
    hostname: fwSpec ? `fw-${fwSpec.id.split('-')[1]}-${fwSpec.vendor === 'fortigate' ? 'a' : 'b'}` : (names[form] ?? 'dev-unknown'),
    role: fp.role,
    site: 'Rotterdam-Havenstraat-214',
    mgmtIp: '10.22.14.17',
    modelFamily: fwSpec ? fwSpec.label : (FACEPLATE_SAMPLES[formKey]?.label ?? 'Generic'),
    health,
    uptime: '138d 06h 12m',
    lastPoll: '14s ago',
    firmware: 'v17.9.4-build.221',
    serialMasked: 'FDO••••••82K',
    faceplate: fp,
    checkRunAt: '2026-10-27 14:36:41',
    issues:
      health === 'healthy'
        ? []
        : [
            ...(stack
              ? [
                  { id: 'i1', severity: 'critical' as const, title: 'PSU failed on member 3', detail: 'Redundant power supply reports no input; running on single PSU.', since: '2h 14m', target: 'Member 3 · PSU-B' },
                  { id: 'i2', severity: 'critical' as const, title: '4 ports faulted on member 3', detail: 'CRC errors above 1,000/min on Gi3/0/5–Gi3/0/8.', since: '1h 48m', target: 'Member 3 · Gi3/0/5–8' },
                  { id: 'i3', severity: 'warning' as const, title: 'Fan speed degraded on member 2', detail: 'Fan 2 at 41% of nominal RPM; temperature rising.', since: '5h 02m', target: 'Member 2 · Fan 2' },
                ]
              : [
                  { id: 'i1', severity: health === 'critical' ? ('critical' as const) : ('warning' as const), title: 'Uplink Te1/1/2 dropping frames', detail: 'Output discards 412/s over 15 min, utilisation at 94%.', since: '47m', target: 'Te1/1/2' },
                  { id: 'i2', severity: 'warning' as const, title: '3 access ports with input errors', detail: 'Gi1/0/9, Gi1/0/17, Gi1/0/22 show rising CRC counters.', since: '3h 20m', target: 'Gi1/0/9, 17, 22' },
                ]),
            { id: 'i9', severity: 'info' as const, title: 'Firmware 2 releases behind', detail: 'v17.9.4 installed, v17.12.1 recommended by baseline.', since: '14d', target: 'System' },
          ],
    checks: [
      { id: 'c1', name: 'Reachable via SNMP and ICMP', result: 'pass', detail: 'Round trip 3.2 ms, no loss over 20 probes' },
      { id: 'c2', name: 'Telemetry freshness (< 120s)', result: 'pass', detail: 'Last poll 14s ago' },
      { id: 'c3', name: 'Port error rate below threshold', result: health === 'healthy' ? 'pass' : 'fail', detail: health === 'healthy' ? 'All ports under 5 errors/min' : '4 ports exceed 100 errors/min' },
      { id: 'c4', name: 'Power supplies redundant', result: stack ? 'fail' : 'pass', detail: stack ? 'Member 3 running on single PSU' : 'Both PSUs reporting input' },
      { id: 'c5', name: 'Fans and temperature in range', result: stack ? 'warn' : 'pass', detail: stack ? 'Member 2 fan 2 below 50% RPM' : 'Max 47°C, limit 70°C' },
      { id: 'c6', name: 'Approved in NetBox', result: 'pass', detail: 'Matched by serial and management IP' },
      { id: 'c7', name: 'Firmware matches baseline', result: 'warn', detail: 'v17.9.4 (baseline v17.12.1)' },
    ],
    hardware: [
      { id: 'h1', name: 'Power supplies', kind: 'power', status: stack ? 'fail' : 'ok', value: stack ? '1 of 2 OK' : '2 of 2 OK', detail: stack ? 'Member 3 PSU-B has no input' : 'PSU-A and PSU-B both reporting input' },
      { id: 'h2', name: 'Fans', kind: 'fan', status: stack ? 'warn' : 'ok', value: stack ? '1 degraded' : 'All normal', detail: stack ? 'Member 2 fan 2 at 41% of nominal RPM' : 'All fans between 4,200 and 5,100 RPM' },
      { id: 'h3', name: 'Temperature', kind: 'temp', status: stack ? 'warn' : 'ok', value: stack ? '61°C' : '47°C', detail: stack ? 'Highest sensor, limit 70°C' : 'Highest sensor, limit 70°C' },
      { id: 'h4', name: 'CPU load', kind: 'cpu', status: 'ok', value: '23%', detail: '5 min average, threshold 80%' },
      { id: 'h5', name: 'Memory', kind: 'memory', status: health === 'healthy' ? 'ok' : 'warn', value: health === 'healthy' ? '52%' : '78%', detail: 'Used of 4 GB, threshold 85%' },
      { id: 'h6', name: 'Flash storage', kind: 'storage', status: 'ok', value: '38%', detail: 'Used of 8 GB, threshold 90%' },
    ],
  };
}

// ---------- time series ----------
export type RangeKey = '1h' | '6h' | '24h' | '7d' | 'custom';
const RANGE_CFG: Record<Exclude<RangeKey, 'custom'>, { points: number; stepMin: number }> = {
  '1h': { points: 60, stepMin: 1 },
  '6h': { points: 72, stepMin: 5 },
  '24h': { points: 96, stepMin: 15 },
  '7d': { points: 84, stepMin: 120 },
};

const NOW_MS = Date.UTC(2026, 9, 27, 14, 38, 0);

function fmtLabel(ms: number, range: RangeKey): string {
  const d = new Date(ms);
  const hh = String(d.getUTCHours()).padStart(2, '0');
  const mm = String(d.getUTCMinutes()).padStart(2, '0');
  if (range === '7d') {
    const day = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'][d.getUTCDay()];
    return `${day} ${hh}:${mm}`;
  }
  return `${hh}:${mm}`;
}

export function buildSeries(range: RangeKey, seed: number, scale = 1, customMin = 180): SeriesPoint[] {
  const cfg = range === 'custom' ? { points: 90, stepMin: Math.max(1, Math.round(customMin / 90)) } : RANGE_CFG[range];
  const rnd = seeded(seed + cfg.points);
  const out: SeriesPoint[] = [];
  const gapStart = Math.floor(cfg.points * 0.58);
  const gapEnd = gapStart + Math.max(2, Math.floor(cfg.points * 0.05));
  for (let i = 0; i < cfg.points; i++) {
    const t = NOW_MS - (cfg.points - 1 - i) * cfg.stepMin * 60000;
    const wave = Math.sin(i / (cfg.points / 6)) * 0.25 + Math.sin(i / (cfg.points / 17)) * 0.1;
    const spike = i === Math.floor(cfg.points * 0.31) ? 0.45 : i === Math.floor(cfg.points * 0.82) ? 0.6 : 0;
    const base = 0.45 + wave + spike + (rnd() - 0.5) * 0.12;
    const inBps = Math.max(0.02, base) * 640 * scale;
    const outBps = Math.max(0.02, base * 0.62 + (rnd() - 0.5) * 0.08) * 640 * scale;
    const isGap = i >= gapStart && i < gapEnd;
    out.push({
      t,
      label: fmtLabel(t, range),
      inBps: isGap ? null : Math.round(inBps * 10) / 10,
      outBps: isGap ? null : Math.round(outBps * 10) / 10,
      errors: isGap ? null : Math.max(0, Math.round((spike > 0 ? 80 + rnd() * 90 : rnd() * 9) * 10) / 10),
      util: isGap ? null : Math.min(99, Math.max(2, Math.round((base * 100 + (rnd() - 0.5) * 8) * 10) / 10)),
    });
  }
  return out;
}

export function buildResourceSeries(range: RangeKey, seed: number) {
  const base = buildSeries(range, seed, 1);
  const rnd = seeded(seed * 3 + 1);
  return base.map((p, i) => ({
    t: p.t,
    label: p.label,
    cpu: p.util === null ? null : Math.round(Math.min(96, 18 + (p.util ?? 0) * 0.35 + rnd() * 6) * 10) / 10,
    mem: p.util === null ? null : Math.round((58 + Math.sin(i / 20) * 4 + rnd() * 2) * 10) / 10,
    temp: p.util === null ? null : Math.round((41 + (p.util ?? 0) * 0.08 + rnd() * 1.4) * 10) / 10,
  }));
}

export function buildTopPorts(seed: number) {
  const rnd = seeded(seed);
  const names = ['Te1/1/1', 'Te1/1/2', 'Gi1/0/12', 'Gi1/0/3', 'Gi1/0/22', 'Gi1/0/17', 'Gi1/0/9', 'Gi1/0/31'];
  return names
    .map((n, i) => ({ name: n, util: Math.round((92 - i * 9 + rnd() * 7) * 10) / 10 }))
    .sort((a, b) => b.util - a.util);
}

// ---------- settings ----------
export const USERS: UserRow[] = [
  { id: 'u1', name: 'Marit van der Berg', email: 'm.vanderberg@noc.example', role: 'Administrator', lastActive: '2 min ago', mfa: true },
  { id: 'u2', name: 'Sander Kuipers', email: 's.kuipers@noc.example', role: 'Engineer', lastActive: '11 min ago', mfa: true },
  { id: 'u3', name: 'Ilse Hoogendijk', email: 'i.hoogendijk@noc.example', role: 'Engineer', lastActive: '1h ago', mfa: true },
  { id: 'u4', name: 'Dewi Pranata', email: 'd.pranata@noc.example', role: 'Operator', lastActive: '26 min ago', mfa: false },
  { id: 'u5', name: 'Joost Brouwer', email: 'j.brouwer@noc.example', role: 'Operator', lastActive: '3h ago', mfa: true },
  { id: 'u6', name: 'Fenna Smit', email: 'f.smit@customer.example', role: 'Read-only', lastActive: 'Yesterday', mfa: false },
];

export const PERMISSIONS: { label: string; Administrator: boolean; Engineer: boolean; Operator: boolean; 'Read-only': boolean }[] = [
  { label: 'View devices, sites and faceplates', Administrator: true, Engineer: true, Operator: true, 'Read-only': true },
  { label: 'View port graphs and history', Administrator: true, Engineer: true, Operator: true, 'Read-only': true },
  { label: 'Acknowledge alerts', Administrator: true, Engineer: true, Operator: true, 'Read-only': false },
  { label: 'Approve devices from "Not in NetBox"', Administrator: true, Engineer: true, Operator: false, 'Read-only': false },
  { label: 'Edit saved views and thresholds', Administrator: true, Engineer: true, Operator: false, 'Read-only': false },
  { label: 'Manage Alertmanager webhook', Administrator: true, Engineer: false, Operator: false, 'Read-only': false },
  { label: 'Manage users and roles', Administrator: true, Engineer: false, Operator: false, 'Read-only': false },
  { label: 'View Database tab (read-only)', Administrator: true, Engineer: true, Operator: false, 'Read-only': false },
];

export const DB_TABLES = [
  { name: 'devices', rows: 19840, size: '412 MB', updated: '14:38:02' },
  { name: 'ports', rows: 1284190, size: '6.8 GB', updated: '14:38:11' },
  { name: 'port_samples', rows: 482910331, size: '212 GB', updated: '14:38:12' },
  { name: 'sites', rows: 2014, size: '3.4 MB', updated: '09:12:40' },
  { name: 'discovered_devices', rows: 47, size: '260 KB', updated: '14:31:09' },
  { name: 'alerts', rows: 8123, size: '88 MB', updated: '14:36:55' },
  { name: 'audit_log', rows: 90412, size: '240 MB', updated: '14:35:01' },
];

export const WEBHOOK_DELIVERIES: WebhookDelivery[] = [
  { id: 'wd1', at: '14:36:55', alertname: 'PortErrorRateHigh', status: 200, durationMs: 41 },
  { id: 'wd2', at: '14:21:03', alertname: 'DeviceUnreachable', status: 200, durationMs: 38 },
  { id: 'wd3', at: '13:58:47', alertname: 'PSUFailure', status: 200, durationMs: 52 },
  { id: 'wd4', at: '13:12:10', alertname: 'UplinkSaturation', status: 500, durationMs: 3012 },
  { id: 'wd5', at: '13:12:40', alertname: 'UplinkSaturation', status: 200, durationMs: 45 },
  { id: 'wd6', at: '11:03:22', alertname: 'DiscoveryDrift', status: 200, durationMs: 36 },
];

export const SUMMARY = {
  total: TOTAL_DEVICES,
  healthy: 14782,
  warning: 2764,
  critical: 1488,
  unreachable: 806,
  alerts: 142,
};