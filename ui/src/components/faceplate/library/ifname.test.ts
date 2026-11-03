import { describe, expect, it } from 'vitest';
import { canonicalIface, mapIfName, namesMatch } from './ifname';

describe('ifName mapping', () => {
  it('treats Gi and GigabitEthernet as the same port', () => {
    expect(canonicalIface('Gi1/0/1')).toBe('gi1/0/1');
    expect(canonicalIface('GigabitEthernet1/0/1')).toBe('gi1/0/1');
    expect(namesMatch('Gi1/0/1', 'GigabitEthernet1/0/1')).toBe(true);
    expect(mapIfName('Gi1/0/48', ['GigabitEthernet1/0/1', 'GigabitEthernet1/0/48'])).toBe('GigabitEthernet1/0/48');
  });

  it('maps the other Cisco short forms', () => {
    expect(namesMatch('Fa0/21', 'FastEthernet0/21')).toBe(true);
    expect(namesMatch('Te1/1/1', 'TenGigabitEthernet1/1/1')).toBe(true);
    expect(namesMatch('Twe1/0/1', 'TwentyFiveGigE1/0/1')).toBe(true);
    expect(namesMatch('Hu1/0/1', 'HundredGigE1/0/1')).toBe(true);
  });

  it('does not treat FortiGate port1 as a port-channel', () => {
    expect(canonicalIface('port1')).toBe('port1');
    expect(canonicalIface('port1')).not.toBe(canonicalIface('Po1'));
  });

  it('joins port1 with lan1 and ethernet1/1 with the YAML name', () => {
    expect(mapIfName('port1', ['wan', 'lan1', 'lan2'])).toBe('lan1');
    expect(mapIfName('lan2', ['port1', 'port2'])).toBe('port2');
    expect(mapIfName('ethernet1/1', ['ethernet1/1', 'ethernet1/2'])).toBe('ethernet1/1');
    expect(mapIfName('eth1/1', ['ethernet1/1'])).toBe('ethernet1/1');
    expect(mapIfName('wan1', ['wan', 'lan1'])).toBe('wan');
  });

  it('joins Meraki Port 1 to the library name', () => {
    expect(mapIfName('port1', ['Port 1', 'Port 2'])).toBe('Port 1');
    expect(mapIfName('Port 12', ['Port 12'])).toBe('Port 12');
  });
});
