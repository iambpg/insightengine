import type { PortInfo } from '@/lib/types';
import { lockedChassis } from '../size';
import type { FaceplatePortBox } from './catalog';

/** A FortiGate chassis. FortiSwitch and other vendors stay on their own faceplates. */
export function isFortiGateModel(model: {
  vendor?: string;
  manufacturer?: string;
  model?: string;
  partNumber?: string;
  slug?: string;
}): boolean {
  const blob = [model.vendor, model.manufacturer, model.model, model.partNumber, model.slug].filter(Boolean).join(' ').toLowerCase();
  if (/fortiswitch|\bfs-?\d/.test(blob)) return false;
  if (blob.includes('fortigate')) return true;
  return /\bfg-?\d/.test(blob);
}

export function isFortiSwitchModel(model: {
  vendor?: string;
  manufacturer?: string;
  model?: string;
  partNumber?: string;
  slug?: string;
}): boolean {
  const blob = [model.vendor, model.manufacturer, model.model, model.partNumber, model.slug].filter(Boolean).join(' ').toLowerCase();
  return /fortiswitch|\bfs-?\d/.test(blob);
}

/** Switches, FortiGates and FortiSwitches use the 9200L chassis frame. */
export function locksChassisFrame(model: {
  vendor?: string;
  manufacturer?: string;
  model?: string;
  partNumber?: string;
  slug?: string;
}): boolean {
  if (isFortiGateModel(model) || isFortiSwitchModel(model)) return true;
  const blob = [model.vendor, model.manufacturer, model.model, model.partNumber, model.slug].filter(Boolean).join(' ').toLowerCase();
  if (/palo|pan-os|\bpa-\d/.test(blob)) return false;
  return /cisco|catalyst|nexus|switch|\bc\d{4}|\bws-|\bie-\d|\bsg\d|\bcbs/.test(blob);
}

export function glyphMedium(boxType: string | undefined, fallback: PortInfo['type']): PortInfo['type'] {
  const kind = (boxType || '').toLowerCase();
  if (kind.includes('qsfp')) return 'QSFP';
  if (kind.includes('sfpp') || kind.includes('sfp28') || kind.includes('10gbase-x') || kind.includes('25g')) return 'SFP+';
  if (kind.includes('sfp') || kind.includes('base-x')) return 'SFP';
  if (kind.includes('base-t') || kind.includes('rj45')) return 'RJ45';
  return fallback || 'RJ45';
}

export interface PlacedOpening {
  name: string;
  type?: string;
  x: number;
  y: number;
  size: number;
}

export interface FortiGateCanvas {
  width: number;
  height: number;
  ports: PlacedOpening[];
}

function snapPortRows(ports: PlacedOpening[]): PlacedOpening[] {
  const sorted = [...ports].sort((left, right) => left.y - right.y || left.x - right.x);
  const rows: PlacedOpening[][] = [];
  for (const port of sorted) {
    const row = rows[rows.length - 1];
    if (!row || port.y - row[0].y > 14) rows.push([port]);
    else row.push(port);
  }
  return rows.flatMap((row) => {
    const y = Math.min(...row.map((port) => port.y));
    return row.map((port) => ({ ...port, y }));
  });
}

/**
 * Place the switch-style port glyphs where the NetBox front image puts each opening.
 * Openings in the same band share one baseline so the rows line up. The picture itself is not drawn.
 */
export function placeFortiGatePorts(model: { width: number; height: number; ports: FaceplatePortBox[] }): FortiGateCanvas {
  const frame = lockedChassis();
  const boxes = model.ports.filter((box) => box.name && box.w > 0 && box.h > 0);
  if (!boxes.length) return { width: frame.innerW, height: frame.innerH, ports: [] };
  const ports = snapPortRows(boxes.map((box) => {
    const openingW = box.w * frame.innerW;
    const openingH = box.h * frame.innerH;
    const fiber = glyphMedium(box.type, 'RJ45') !== 'RJ45';
    const size = Math.max(12, Math.min(22, Math.min(openingW * 0.92, openingH * 0.9)));
    const glyphW = fiber ? size * 1.15 : size;
    return {
      name: box.name,
      type: box.type,
      x: box.x * frame.innerW + Math.max(0, (openingW - glyphW) / 2),
      y: box.y * frame.innerH + Math.max(0, (openingH - size * 0.9) / 2),
      size,
    };
  }));
  return { width: frame.innerW, height: frame.innerH, ports };
}
