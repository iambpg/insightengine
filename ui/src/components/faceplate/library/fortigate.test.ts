import { readFileSync } from 'fs';
import path from 'path';
import { describe, expect, it } from 'vitest';
import type { FaceplatePortBox } from './catalog';
import { keepFaceplateModel } from './catalog';
import { isFortiGateModel, placeFortiGatePorts } from './fortigate';

function modelFile(slug: string): { width: number; height: number; ports: FaceplatePortBox[] } {
  const file = path.resolve(__dirname, `../../../../public/faceplates/models/${slug}.json`);
  return JSON.parse(readFileSync(file, 'utf8'));
}

function byName(slug: string, name: string) {
  const placed = placeFortiGatePorts(modelFile(slug));
  const found = placed.ports.find((port) => port.name === name);
  if (!found) throw new Error(`${slug} has no ${name}`);
  return found;
}

describe('FortiGate faceplates follow the NetBox front image', () => {
  it('keeps the FortiGate port map when NetBox lists a different count', () => {
    const body = {
      slug: 'fortinet-fg-60f',
      model: 'FortiGate 60F',
      partNumber: 'FG-60F',
      manufacturer: 'Fortinet',
      vendor: 'fortinet',
      source: 'visio',
      front: '/faceplates/visio/fortinet/fg-fwf-60-61f.front.svg',
      rear: '',
      width: 510,
      height: 91,
      raster: false,
      ports: [{ name: 'wan1', x: 0.2, y: 0.3, w: 0.05, h: 0.2 }],
    };
    expect(keepFaceplateModel(body, 10)).toBe(true);
    expect(keepFaceplateModel({ ...body, slug: 'cisco-c9200l-48p', model: 'C9200L-48P', partNumber: 'C9200L-48P', manufacturer: 'Cisco', vendor: 'cisco' }, 8)).toBe(false);
  });

  it('recognises FortiGate models and leaves FortiSwitch alone', () => {
    expect(isFortiGateModel({ slug: 'fortinet-fg-60f', model: 'FortiGate 60F', partNumber: 'FG-60F', vendor: 'fortinet' })).toBe(true);
    expect(isFortiGateModel({ slug: 'fortinet-fg-1200d', model: 'FortiGate 1200D', partNumber: 'FG-1200D' })).toBe(true);
    expect(isFortiGateModel({ slug: 'fortinet-fg-40f', partNumber: 'FG-40F' })).toBe(true);
    expect(isFortiGateModel({ slug: 'fortinet-fg-2200e', model: 'FortiGate 2200E' })).toBe(true);
    expect(isFortiGateModel({ slug: 'fortinet-fs-108f', model: 'FortiSwitch 108F', partNumber: 'FS-108F' })).toBe(false);
    expect(isFortiGateModel({ slug: 'cisco-c9200l-48p', manufacturer: 'Cisco' })).toBe(false);
  });

  it('keeps the 60F on one row in the image order', () => {
    const placed = placeFortiGatePorts(modelFile('fortinet-fg-60f'));
    const names = [...placed.ports].sort((left, right) => left.x - right.x).map((port) => port.name);
    expect(names).toEqual(['wan1', 'wan2', 'internal1', 'A', 'B', 'internal5', 'internal4', 'internal3', 'internal2', 'dmz']);
    const ys = placed.ports.map((port) => port.y);
    expect(Math.max(...ys) - Math.min(...ys)).toBeLessThan(4);
  });

  it('keeps the 40F, 60E and 80F arrangements from their images', () => {
    const forty = placeFortiGatePorts(modelFile('fortinet-fg-40f'));
    const fortyNames = [...forty.ports].sort((left, right) => left.x - right.x).map((port) => port.name);
    expect(fortyNames).toEqual(['wan', 'A', 'lan3', 'lan2', 'lan1']);

    const sixtyE = placeFortiGatePorts(modelFile('fortinet-fg-60e'));
    expect(sixtyE.ports).toHaveLength(10);
    expect(Math.max(...sixtyE.ports.map((port) => port.y)) - Math.min(...sixtyE.ports.map((port) => port.y))).toBeLessThan(16);

    const wan1 = byName('fortinet-fg-80f', 'wan1');
    const wan2 = byName('fortinet-fg-80f', 'wan2');
    expect(wan2.y).toBeGreaterThan(wan1.y + 20);
    expect(Math.abs(wan2.x - wan1.x)).toBeLessThan(8);
  });

  it('stacks the 1200D and 2200E ports the way the front image does', () => {
    const mgmt1 = byName('fortinet-fg-1200d', 'mgmt1');
    const mgmt2 = byName('fortinet-fg-1200d', 'mgmt2');
    expect(mgmt2.y).toBeGreaterThan(mgmt1.y);
    expect(Math.abs(mgmt2.x - mgmt1.x)).toBeLessThan(8);
    const port17 = byName('fortinet-fg-1200d', 'port17');
    const port18 = byName('fortinet-fg-1200d', 'port18');
    expect(port18.y).toBeGreaterThan(port17.y);

    const ha1 = byName('fortinet-fg-2200e', 'ha1');
    const ha2 = byName('fortinet-fg-2200e', 'ha2');
    expect(ha2.y).toBeGreaterThan(ha1.y);
    expect(Math.abs(ha2.x - ha1.x)).toBeLessThan(8);
  });
});
