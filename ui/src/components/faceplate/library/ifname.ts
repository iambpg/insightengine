/**
 * Join an SNMP ifName to a device-type interface name.
 *
 * Cisco inventories use the long form (GigabitEthernet1/0/1) while IF-MIB
 * ifName is short (Gi1/0/1). FortiGate and Palo Alto use port1, lan1 and
 * ethernet1/1. Matching is case-insensitive and ignores spaces and dashes.
 */

const PREFIXES: [string, string][] = [
  ['fortygigabitethernet', 'fo'],
  ['hundredgigabitethernet', 'hu'],
  ['twentyfivegigabitethernet', 'twe'],
  ['tengigabitethernet', 'te'],
  ['gigabitethernet', 'gi'],
  ['fastethernet', 'fa'],
  ['twentyfivegige', 'twe'],
  ['tengigethernet', 'te'],
  ['fortygige', 'fo'],
  ['hundredgige', 'hu'],
  ['portchannel', 'po'],
  ['management', 'mgmt'],
  ['fortilink', 'fortilink'],
  ['ethernet', 'eth'],
  ['loopback', 'lo'],
  ['tunnel', 'tu'],
  ['vlan', 'vl'],
  ['twe', 'twe'],
  ['mgmt', 'mgmt'],
  ['eth', 'eth'],
  ['ae', 'ae'],
  ['fa', 'fa'],
  ['gi', 'gi'],
  ['te', 'te'],
  ['fo', 'fo'],
  ['hu', 'hu'],
  ['et', 'eth'],
  ['po', 'po'],
  ['vl', 'vl'],
  ['lo', 'lo'],
  ['tu', 'tu'],
  ['ma', 'mgmt'],
];

const SORTED = [...PREFIXES].sort((a, b) => b[0].length - a[0].length);
const GUARDED = new Set(PREFIXES.filter(([prefix]) => prefix.length <= 4).map(([prefix]) => prefix));

export function ifaceCompact(name: string): string {
  return (name || '').trim().toLowerCase().replace(/[\s_-]+/g, '');
}

export function canonicalIface(name: string): string {
  const compact = ifaceCompact(name);
  if (!compact) return '';
  for (const [prefix, short] of SORTED) {
    if (compact !== prefix && !compact.startsWith(prefix)) continue;
    const rest = compact.slice(prefix.length);
    if (GUARDED.has(prefix) && rest && !'0123456789./'.includes(rest[0])) continue;
    return short + rest;
  }
  return compact;
}

/** Extra keys so port1 and lan1, and wan and wan1, can meet a YAML name. */
export function ifaceKeys(name: string): Set<string> {
  const compact = ifaceCompact(name);
  const canonical = canonicalIface(name);
  const keys = new Set<string>();
  if (compact) keys.add(compact);
  if (canonical) keys.add(canonical);
  const numbered = /^(port|lan|internal|ethernet|eth)(\d+)$/.exec(canonical);
  if (numbered) {
    const index = numbered[2];
    keys.add(`port${index}`);
    keys.add(`lan${index}`);
    keys.add(`internal${index}`);
  }
  if (/^wan\d*$/.test(canonical)) {
    keys.add('wan');
    keys.add('wan1');
  }
  return keys;
}

/**
 * Port position on a faceplate, ignoring the chassis or stack member.
 * Gi2/0/48 and GigabitEthernet1/0/48 are the same opening on a member faceplate.
 */
export function faceplatePosition(name: string): string {
  const canonical = canonicalIface(name);
  return canonical.replace(/^([a-z]+)\d+(?=\/)/, '$1');
}

export function namesMatch(left: string, right: string): boolean {
  const a = ifaceKeys(left);
  const b = ifaceKeys(right);
  for (const key of a) if (b.has(key)) return true;
  return false;
}

/** The YAML interface this SNMP (or NetBox) name refers to, if one is listed. */
export function mapIfName(ifName: string, yamlNames: string[]): string | null {
  const wanted = ifaceKeys(ifName);
  if (!wanted.size) return null;
  for (const name of yamlNames) {
    for (const key of ifaceKeys(name)) {
      if (wanted.has(key)) return name;
    }
  }
  return null;
}
