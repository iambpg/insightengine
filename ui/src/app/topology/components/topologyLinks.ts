import type { DeviceKind } from '@/app/topology/components/DeviceArt';
import type { DeviceDetailData, DeviceHealth, DeviceRow, PortInfo } from '@/lib/types';

export interface TopoNode {
  id: string;
  label: string;
  sub: string;
  kind: DeviceKind;
  health: DeviceHealth;
  x: number;
  y: number;
  current?: boolean;
  href?: string;
}

export interface TopoLink {
  id: string;
  from: string;
  to: string;
  label: string;
  state: 'up' | 'warning' | 'fault';
}

const FORM_KIND: Record<string, DeviceKind> = {
  'access-switch-24': 'switch',
  'access-switch-48': 'switch',
  'switch-stack': 'stack',
  'ceiling-ap': 'ap',
  'wireless-controller': 'controller',
  firewall: 'firewall',
  'branch-router': 'router',
  'modular-chassis': 'chassis',
  generic: 'generic',
};

/** Icon from the backend form factor. Unknown classes use a generic device, never an access point. */
export function kindFromForm(form: string | undefined | null): DeviceKind {
  if (form && FORM_KIND[form]) return FORM_KIND[form];
  return 'generic';
}

/** Last resort when a neighbour has no NetBox or Netdisco record. Hostnames are not classified. */
export function kindForUnlinkedNeighbour(): DeviceKind {
  return 'generic';
}

export function deviceNodeHref(live: boolean, id: string | undefined, formFactor: string): string | undefined {
  const form = encodeURIComponent(formFactor || 'generic');
  if (!live) return formFactor ? `/device-detail?form=${form}` : undefined;
  if (!id) return undefined;
  return `/device-detail?id=${encodeURIComponent(id)}&form=${form}`;
}

export function neighbourNodeHref(
  live: boolean,
  deviceId: string | undefined,
  formFactor: string | undefined,
  fallbackKey: string | undefined,
): string | undefined {
  if (!live) {
    const form = formFactor && formFactor !== 'generic' ? formFactor : 'access-switch-48';
    return `/device-detail?form=${encodeURIComponent(form)}`;
  }
  if (deviceId) return deviceNodeHref(true, deviceId, formFactor || 'generic');
  const key = (fallbackKey || '').trim();
  if (!key) return undefined;
  return deviceNodeHref(true, key, formFactor || 'generic');
}

function portsOf(d: DeviceDetailData): PortInfo[] {
  const f = d.faceplate;
  if (f.members) return f.members.flatMap((m) => m.ports);
  if (f.modules) return f.modules.flatMap((m) => m.ports);
  return f.ports ?? [];
}

function matchDevice(name: string, devices: DeviceRow[]): DeviceRow | undefined {
  const text = name.trim().toLowerCase();
  if (!text) return undefined;
  return devices.find((row) => row.hostname.toLowerCase() === text || row.mgmtIp === name.trim());
}

export function buildDeviceTopology(d: DeviceDetailData, devices: DeviceRow[] = [], live = false) {
  const neighbours = new Map<string, { port: string; local: string; state: TopoLink['state']; deviceId?: string }>();
  portsOf(d).forEach((p) => {
    if (p.neighbour && !neighbours.has(p.neighbour.device)) {
      neighbours.set(p.neighbour.device, {
        port: p.neighbour.port,
        local: p.name,
        state: p.state === 'fault' ? 'fault' : p.state === 'warning' ? 'warning' : 'up',
        deviceId: p.neighbour.deviceId,
      });
    }
  });
  const list = Array.from(neighbours.entries()).slice(0, 6);
  const W = 900;
  const H = 380;
  const selfKind = kindFromForm(d.faceplate.form_factor);
  const nodes: TopoNode[] = [
    {
      id: 'self',
      label: d.hostname,
      sub: d.mgmtIp,
      kind: selfKind,
      health: d.health,
      x: W / 2,
      y: H / 2,
      current: true,
      href: deviceNodeHref(live, d.id, d.faceplate.form_factor),
    },
  ];
  const links: TopoLink[] = [];
  list.forEach(([name, info], i) => {
    const angle = (Math.PI * 2 * i) / Math.max(list.length, 1) - Math.PI / 2;
    const match = matchDevice(name, devices) || (info.deviceId ? devices.find((row) => row.id === info.deviceId) : undefined);
    const deviceId = info.deviceId || match?.id;
    const linked = Boolean(deviceId || match);
    nodes.push({
      id: `n-${name}`,
      label: name,
      sub: info.port,
      kind: linked ? kindFromForm(match?.formFactor) : kindForUnlinkedNeighbour(),
      health: info.state === 'fault' ? 'critical' : info.state === 'warning' ? 'warning' : 'healthy',
      x: W / 2 + Math.cos(angle) * 320,
      y: H / 2 + Math.sin(angle) * 140,
      href: neighbourNodeHref(live, deviceId, match?.formFactor, linked ? undefined : name),
    });
    links.push({ id: `l-${name}`, from: 'self', to: `n-${name}`, label: `${info.local} ↔ ${info.port}`, state: info.state });
  });
  return { nodes, links, W, H };
}

function stateOf(h: DeviceHealth): TopoLink['state'] {
  return h === 'critical' || h === 'unreachable' ? 'fault' : h === 'warning' ? 'warning' : 'up';
}

export function buildSiteTopology(devices: DeviceRow[], live = false, currentHost?: string) {
  const W = 900;
  const find = (k: DeviceKind) => devices.filter((d) => kindFromForm(d.formFactor) === k);
  const fw = find('firewall')[0];
  const rtr = find('router')[0];
  const wlc = find('controller')[0];
  const aps = find('ap');
  const stacks = find('stack');
  const switches = find('switch');
  const generics = find('generic');
  const lower = [...stacks, ...switches, ...generics];

  const nodes: TopoNode[] = [];
  const links: TopoLink[] = [];
  const mk = (d: DeviceRow, x: number, y: number, sub?: string): TopoNode => ({
    id: d.id,
    label: d.hostname,
    sub: sub ?? d.mgmtIp,
    kind: kindFromForm(d.formFactor),
    health: d.health,
    x,
    y,
    current: currentHost ? d.hostname === currentHost : false,
    href: deviceNodeHref(live, d.id, d.formFactor),
  });

  nodes.push({ id: 'wan', label: 'ISP uplink', sub: 'WAN', kind: 'cloud', health: 'healthy', x: W / 2, y: 40 });
  let edgeId = 'wan';
  let y = 40;
  if (rtr) {
    y += 85;
    nodes.push(mk(rtr, W / 2, y));
    links.push({ id: 'e-wan-rtr', from: 'wan', to: rtr.id, label: 'WAN', state: stateOf(rtr.health) });
    edgeId = rtr.id;
  }
  if (fw) {
    y += 85;
    nodes.push(mk(fw, W / 2, y));
    links.push({ id: 'e-fw', from: edgeId, to: fw.id, label: 'Te0/1', state: stateOf(fw.health) });
    edgeId = fw.id;
  }
  const coreY = y + 95;
  const distId = edgeId;
  const rowY = coreY;
  const lowerNodes = [...lower.slice(0, 4)];
  const sideItems: DeviceRow[] = [];
  if (wlc) sideItems.push(wlc);
  const total = lowerNodes.length + sideItems.length;
  const gap = total > 0 ? Math.min(210, (W - 160) / Math.max(total, 1)) : 0;
  const startX = W / 2 - ((total - 1) * gap) / 2;
  [...lowerNodes, ...sideItems].forEach((d, i) => {
    nodes.push(mk(d, startX + i * gap, rowY));
    links.push({ id: `e-${d.id}`, from: distId, to: d.id, label: `Te1/0/${i + 1}`, state: stateOf(d.health) });
  });
  const apY = rowY + 95;
  const apList = aps.slice(0, 4);
  const apGap = apList.length > 0 ? Math.min(180, (W - 160) / apList.length) : 0;
  const apStart = W / 2 - ((apList.length - 1) * apGap) / 2;
  const apParent = wlc ? wlc.id : lowerNodes[0]?.id ?? distId;
  apList.forEach((d, i) => {
    nodes.push(mk(d, apStart + i * apGap, apY));
    links.push({ id: `e-${d.id}`, from: apParent, to: d.id, label: `Gi1/0/${i + 10}`, state: stateOf(d.health) });
  });
  const H = (apList.length > 0 ? apY : rowY) + 60;
  return { nodes, links, W, H };
}
