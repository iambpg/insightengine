import { describe, expect, it } from 'vitest';
import type { DeviceDetailData, DeviceRow } from '@/lib/types';
import { buildDeviceTopology, buildHierarchyTopology, buildSiteTopology, deviceNodeHref } from './topologyLinks';
import type { HierarchyNode } from '@/lib/types';

function row(partial: Partial<DeviceRow> & Pick<DeviceRow, 'id' | 'hostname' | 'formFactor'>): DeviceRow {
  return {
    role: 'Device',
    site: 'Rotterdam',
    siteId: '1',
    mgmtIp: '10.1.0.1',
    modelFamily: 'Generic',
    health: 'healthy',
    portsUp: 1,
    portsTotal: 24,
    portsWarn: 0,
    portsFault: 0,
    uptime: '1d',
    lastPoll: '10s ago',
    ...partial,
  };
}

function detail(partial: Partial<DeviceDetailData> = {}): DeviceDetailData {
  return {
    id: '40',
    hostname: 'apc-ups',
    role: 'UPS',
    site: 'Rotterdam',
    siteId: '1',
    mgmtIp: '10.9.0.40',
    modelFamily: 'Smart-UPS 3000',
    health: 'healthy',
    uptime: '1d',
    lastPoll: '10s ago',
    firmware: '—',
    serialMasked: '—',
    faceplate: { form_factor: 'generic', role: 'UPS', hostname: 'apc-ups', ports: [] },
    issues: [],
    checks: [],
    hardware: [],
    checkRunAt: '',
    ...partial,
  };
}

function assertLiveHref(href: string | undefined) {
  if (!href) return;
  expect(href.startsWith('/device-detail?id=')).toBe(true);
  expect(href.startsWith('/device-detail?form=')).toBe(false);
}

describe('topology links in live mode', () => {
  const devices = [
    row({ id: '40', hostname: 'apc-ups', formFactor: 'generic', mgmtIp: '10.9.0.40', role: 'UPS' }),
    row({ id: '11', hostname: 'apex-sw1', formFactor: 'access-switch-48', mgmtIp: '10.1.0.11', role: 'Access switch' }),
    row({ id: '15', hostname: 'ap-lobby', formFactor: 'ceiling-ap', mgmtIp: '10.1.0.15', role: 'Access point' }),
    row({ id: '12', hostname: 'fg-edge', formFactor: 'firewall', mgmtIp: '10.1.0.12', role: 'Firewall' }),
  ];

  it('never builds a form-only device href', () => {
    const hrefs = [
      deviceNodeHref(true, '40', 'generic'),
      deviceNodeHref(true, '11', 'access-switch-48'),
      deviceNodeHref(true, '15', 'ceiling-ap'),
      deviceNodeHref(true, undefined, 'ceiling-ap'),
    ];
    hrefs.forEach(assertLiveHref);
    expect(deviceNodeHref(true, undefined, 'ceiling-ap')).toBeUndefined();
    expect(deviceNodeHref(false, '40', 'generic')).toBe('/device-detail?form=generic');
  });

  it('links site nodes by NetBox id and does not treat apc- or apex- as access points', () => {
    const topo = buildSiteTopology(devices, true);
    topo.nodes.forEach((node) => assertLiveHref(node.href));
    expect(topo.nodes.find((node) => node.label === 'apc-ups')?.kind).toBe('generic');
    expect(topo.nodes.find((node) => node.label === 'apex-sw1')?.kind).toBe('switch');
    expect(topo.nodes.find((node) => node.label === 'ap-lobby')?.kind).toBe('ap');
    expect(topo.nodes.find((node) => node.label === 'apex-sw1')?.href).toContain('id=11');
    expect(topo.nodes.find((node) => node.id === 'wan')?.href).toBeUndefined();
  });

  it('links the current device and resolved neighbours by id, and leaves unknown names off the access-point icon', () => {
    const device = detail({
      faceplate: {
        form_factor: 'generic',
        role: 'UPS',
        hostname: 'apc-ups',
        ports: [
          {
            id: '1',
            name: 'eth0',
            type: 'RJ45',
            speed: '1 Gbps',
            state: 'up',
            utilisation: 0,
            errors: 0,
            neighbour: { device: 'apex-sw1', port: 'Gi1/0/1', deviceId: '11' },
          },
          {
            id: '2',
            name: 'eth1',
            type: 'RJ45',
            speed: '1 Gbps',
            state: 'up',
            utilisation: 0,
            errors: 0,
            neighbour: { device: 'ap-lookalike', port: 'Te0' },
          },
        ],
      },
    });
    const topo = buildDeviceTopology(device, devices, true);
    topo.nodes.forEach((node) => assertLiveHref(node.href));
    const self = topo.nodes.find((node) => node.id === 'self');
    expect(self?.kind).toBe('generic');
    expect(self?.href).toContain('id=40');
    const known = topo.nodes.find((node) => node.label === 'apex-sw1');
    expect(known?.kind).toBe('switch');
    expect(known?.href).toContain('id=11');
    expect(known?.href?.startsWith('/device-detail?form=')).toBe(false);
    const unknown = topo.nodes.find((node) => node.label === 'ap-lookalike');
    expect(unknown?.kind).toBe('generic');
    expect(unknown?.kind).not.toBe('ap');
    expect(unknown?.href?.startsWith('/device-detail?id=')).toBe(true);
    expect(unknown?.href?.startsWith('/device-detail?form=')).toBe(false);
  });
});

function hierarchyNode(partial: Partial<HierarchyNode> & Pick<HierarchyNode, 'id' | 'hostname'>): HierarchyNode {
  return {
    role: 'access-switches',
    mgmtIp: '10.129.32.17',
    formFactor: 'access-switch-48',
    root: false,
    parentId: '',
    parentHostname: '',
    parentInterface: '',
    uplinkInterface: '',
    hops: 1,
    flagged: false,
    reason: '',
    wlc: '',
    parentDown: false,
    differs: true,
    children: [],
    ...partial,
  };
}

describe('buildHierarchyTopology', () => {
  it('places the parent above the device and the access point below its switch', () => {
    const core = hierarchyNode({ id: '1', hostname: 'core-sw', mgmtIp: '10.129.32.1', root: true, hops: 0, formFactor: 'switch-stack' });
    const access = hierarchyNode({
      id: '2', hostname: 'access-sw', parentId: '1', parentHostname: 'core-sw', parentInterface: 'Gi0/5', uplinkInterface: 'Gi1/0/23', hops: 1,
    });
    const ap = hierarchyNode({
      id: '9', hostname: 'AP-WC18', parentId: '2', parentHostname: 'access-sw', parentInterface: 'Gi1/0/10', uplinkInterface: 'uplink',
      hops: 2, formFactor: 'ceiling-ap', wlc: 'OiOB-Bree-WLC01', parentDown: true,
    });
    const laid = buildHierarchyTopology([core, access, ap], true, { focusId: '2', currentHostname: 'access-sw' });
    expect(laid).not.toBeNull();
    const parent = laid!.nodes.find((node) => node.id === '1');
    const self = laid!.nodes.find((node) => node.id === '2');
    const child = laid!.nodes.find((node) => node.id === '9');
    const wlc = laid!.nodes.find((node) => node.label === 'OiOB-Bree-WLC01');
    expect(parent && self && parent.y < self.y).toBe(true);
    expect(child && self && child.y > self.y).toBe(true);
    expect(child?.sub).toBe('Unreachable due to parent');
    expect(wlc?.sub).toBe('Joined WLC');
    const uplink = laid!.links.find((link) => link.to === '2');
    expect(uplink?.label).toContain('Gi1/0/23');
    expect(uplink?.label).toContain('Gi0/5');
    expect(laid!.links.some((link) => link.label === 'joined' && link.to === '9')).toBe(true);
    expect(laid!.links.some((link) => link.from === wlc?.id && link.label !== 'joined')).toBe(false);
  });
});
