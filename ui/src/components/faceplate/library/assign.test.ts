import { describe, expect, it } from 'vitest';
import type { PortInfo, PortType } from '@/lib/types';
import { assignByOpening, faceplatePortCount, hasNamedFaceplateMatch, vendorFaceplateFits } from './assign';

function port(name: string, type: PortType = 'RJ45'): PortInfo {
  return { id: name, name, type, speed: '1 Gbps', state: 'up', utilisation: 0, errors: 0 };
}

const boxes = [
  { name: 'GigabitEthernet1/0/1', type: '1000base-t' },
  { name: 'GigabitEthernet1/0/2', type: '1000base-t' },
  { name: 'TenGigabitEthernet1/1/1', type: '10gbase-x-sfpp' },
];

describe('faceplate port count follows NetBox', () => {
  it('counts the physical ports and ignores console and vlan', () => {
    const device = {
      form_factor: 'firewall' as const,
      role: 'Firewall',
      ports: [port('port1'), port('port2'), port('port3'), port('port4'), port('port5'), port('port6'), port('port7'), port('port8'), port('console', 'CONSOLE'), port('Vlan10')],
    };
    expect(faceplatePortCount(device)).toBe(8);
  });

  it('rejects a 48-port picture for an 8-port device', () => {
    const device = {
      form_factor: 'firewall' as const,
      role: 'Firewall',
      ports: Array.from({ length: 8 }, (_, index) => port(`port${index + 1}`)),
    };
    expect(vendorFaceplateFits(8, device)).toBe(true);
    expect(vendorFaceplateFits(48, device)).toBe(false);
    expect(vendorFaceplateFits(52, device)).toBe(false);
  });

  it('keeps Cisco names on their own openings', () => {
    expect(hasNamedFaceplateMatch(boxes, [port('Gi2/0/1')])).toBe(true);
  });

  it('lays other devices onto openings in port order', () => {
    const placed = assignByOpening(boxes, [port('port2'), port('wan1', 'SFP'), port('port1'), port('Vlan10')]);
    expect(placed.get('GigabitEthernet1/0/1')?.name).toBe('port1');
    expect(placed.get('GigabitEthernet1/0/2')?.name).toBe('port2');
    expect(placed.get('TenGigabitEthernet1/1/1')?.name).toBe('wan1');
    expect([...placed.values()].some((row) => row.name === 'Vlan10')).toBe(false);
  });
});
