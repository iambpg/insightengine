import type { FaceplateDevice, PortInfo } from '@/lib/types';
import { canonicalIface, faceplatePosition, namesMatch } from './ifname';

export interface Opening {
  name: string;
  type?: string;
}

const SKIP = /^(vlan|vl\d*|port-?channel|po\d+|po$|loopback|lo\d*|tunnel|tu\d*|null\d*|nve)/;

function devicePorts(device: FaceplateDevice): { name: string; type?: string }[] {
  if (device.members?.length) {
    const member = device.members.reduce((best, row) => (row.ports.length > best.ports.length ? row : best));
    return member.ports;
  }
  if (device.modules?.length) return device.modules.flatMap((module) => module.ports);
  return device.ports ?? [];
}

/** Physical openings NetBox put on this device. Console, USB and virtual interfaces are not faceplate ports. */
export function faceplatePortCount(device: FaceplateDevice): number {
  return devicePorts(device).filter((port) => {
    if (port.type === 'CONSOLE' || port.type === 'USB') return false;
    return !SKIP.test(canonicalIface(port.name));
  }).length;
}

/** A vendor picture is used only when it has the same number of openings NetBox listed. */
export function vendorFaceplateFits(openings: number, device: FaceplateDevice): boolean {
  const count = faceplatePortCount(device);
  return count > 0 && openings === count;
}

function lastNumber(name: string): number {
  const nums = name.match(/\d+/g);
  if (!nums) return 100000;
  return Number(nums[nums.length - 1]);
}

function isUplinkName(name: string, type?: string): boolean {
  const kind = (type || '').toLowerCase();
  if (kind.includes('sfp') || kind.includes('qsfp') || /10g|25g|40g|100g/.test(kind)) return true;
  return /^(te|twe|fo|hu)\d/.test(canonicalIface(name));
}

function isPhysical(port: PortInfo): boolean {
  if (port.type === 'CONSOLE' || port.type === 'USB') return false;
  return !SKIP.test(canonicalIface(port.name));
}

function namedHit(box: Opening, ports: PortInfo[]): PortInfo | undefined {
  const exact = ports.find((port) => namesMatch(port.name, box.name));
  if (exact) return exact;
  const opening = faceplatePosition(box.name);
  if (!opening || opening === canonicalIface(box.name)) return undefined;
  return ports.find((port) => faceplatePosition(port.name) === opening);
}

/** True when the live names already sit on this faceplate (a real 9200L, or the same Cisco numbering). */
export function hasNamedFaceplateMatch(boxes: Opening[], ports: PortInfo[]): boolean {
  return boxes.some((box) => namedHit(box, ports));
}

/**
 * Place live ports on the 9200L openings when the names are not Cisco interface names.
 * Copper fills 1..N left to right, then the four uplink cages.
 */
export function assignByOpening(boxes: Opening[], ports: PortInfo[]): Map<string, PortInfo> {
  const copperBoxes = boxes.filter((box) => !isUplinkName(box.name, box.type)).sort((a, b) => lastNumber(a.name) - lastNumber(b.name));
  const uplinkBoxes = boxes.filter((box) => isUplinkName(box.name, box.type)).sort((a, b) => lastNumber(a.name) - lastNumber(b.name));
  const usable = ports.filter(isPhysical);
  const uplinks = usable.filter((port) => isUplinkName(port.name, port.type));
  const copper = usable.filter((port) => !isUplinkName(port.name, port.type));
  copper.sort((a, b) => lastNumber(a.name) - lastNumber(b.name));
  uplinks.sort((a, b) => lastNumber(a.name) - lastNumber(b.name));
  const placed = new Map<string, PortInfo>();
  copper.forEach((port, index) => {
    const box = copperBoxes[index] || uplinkBoxes[index - copperBoxes.length];
    if (box) placed.set(box.name, port);
  });
  uplinks.forEach((port, index) => {
    const box = uplinkBoxes[index];
    if (box && !placed.has(box.name)) placed.set(box.name, port);
  });
  return placed;
}
