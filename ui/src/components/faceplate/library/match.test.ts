import { describe, expect, it } from 'vitest';
import { matchDeviceType, normalizeModelKey, type CatalogEntry } from './match';

const ENTRIES: CatalogEntry[] = [
  { slug: 'cisco-catalyst-2960-plus-48tc-l', model: 'Catalyst 2960+48TC-L', partNumber: 'WS-C2960+48TC-L', manufacturer: 'Cisco', vendor: 'cisco', source: 'visio' },
  { slug: 'cisco-c9300-48p', model: 'Catalyst 9300-48P', partNumber: 'C9300-48P', manufacturer: 'Cisco', vendor: 'cisco', source: 'visio' },
  { slug: 'cisco-c9300-48p-e', model: 'Catalyst 9300-48P-E', partNumber: 'C9300-48P-E', manufacturer: 'Cisco', vendor: 'cisco', source: 'visio' },
  { slug: 'fortinet-fg-40f', model: 'FortiGate 40F', partNumber: 'FG-40F', manufacturer: 'Fortinet', vendor: 'fortinet', source: 'visio' },
  { slug: 'fortinet-fg-40f-3g4g', model: 'FortiGate 40F-3G4G', partNumber: 'FG-40F-3G4G', manufacturer: 'Fortinet', vendor: 'fortinet', source: 'drawn' },
  { slug: 'palo-alto-networks-pa-3220', model: 'PA-3220', partNumber: 'PA-3220', manufacturer: 'Palo Alto Networks', vendor: 'palo-alto', source: 'visio' },
  { slug: 'cisco-meraki-ms120-48fp', model: 'Meraki MS120-48FP', partNumber: 'MS120-48FP-HW', manufacturer: 'Cisco', vendor: 'meraki', source: 'visio' },
];

describe('device type matching', () => {
  it('normalises plus and punctuation', () => {
    expect(normalizeModelKey('Catalyst 2960-Plus 48TC-L')).toBe('catalyst2960+48tcl');
    expect(normalizeModelKey('WS-C2960+48TC-L')).toBe('wsc2960+48tcl');
  });

  it('matches the 2960-Plus by model, part number and slug', () => {
    expect(matchDeviceType({ model: 'Catalyst 2960+48TC-L' }, ENTRIES)?.slug).toBe('cisco-catalyst-2960-plus-48tc-l');
    expect(matchDeviceType({ partNumber: 'WS-C2960+48TC-L' }, ENTRIES)?.slug).toBe('cisco-catalyst-2960-plus-48tc-l');
    expect(matchDeviceType({ slug: 'cisco-catalyst-2960-plus-48tc-l' }, ENTRIES)?.slug).toBe('cisco-catalyst-2960-plus-48tc-l');
    expect(matchDeviceType({ model: '2960-Plus 48TC-L' }, ENTRIES)?.slug).toBe('cisco-catalyst-2960-plus-48tc-l');
  });

  it('prefers C9300-48P over the network-essentials part', () => {
    expect(matchDeviceType({ model: 'C9300-48P' }, ENTRIES)?.partNumber).toBe('C9300-48P');
    expect(matchDeviceType({ partNumber: 'C9300-48P-E' }, ENTRIES)?.partNumber).toBe('C9300-48P-E');
  });

  it('matches FortiGate, Palo Alto and Meraki part numbers', () => {
    expect(matchDeviceType({ model: 'FortiGate 40F' }, ENTRIES)?.slug).toBe('fortinet-fg-40f');
    expect(matchDeviceType({ partNumber: 'FG-40F' }, ENTRIES)?.slug).toBe('fortinet-fg-40f');
    expect(matchDeviceType({ partNumber: 'FG-40F-3G4G' }, ENTRIES)?.slug).toBe('fortinet-fg-40f-3g4g');
    expect(matchDeviceType({ model: 'PA-3220' }, ENTRIES)?.slug).toBe('palo-alto-networks-pa-3220');
    expect(matchDeviceType({ partNumber: 'MS120-48FP-HW' }, ENTRIES)?.slug).toBe('cisco-meraki-ms120-48fp');
  });
});
