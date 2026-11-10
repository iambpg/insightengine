import type { PortInfo } from '@/lib/types';
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
  if (/fortiswitch|\bfs-\d/.test(blob)) return false;
  if (blob.includes('fortigate')) return true;
  return /\bfg-?\d/.test(blob);
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

const MARGIN_L = 56;
const MARGIN_R = 18;
const MARGIN_T = 20;
const MARGIN_B = 18;
const MIN_PITCH_X = 48;
const MIN_PITCH_Y = 42;

function minGap(values: number[]): number {
  const sorted = [...values].sort((left, right) => left - right);
  let gap = 1;
  for (let index = 1; index < sorted.length; index += 1) {
    const delta = sorted[index] - sorted[index - 1];
    if (delta > 0.012) gap = Math.min(gap, delta);
  }
  return gap;
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
  const boxes = model.ports.filter((box) => box.name && box.w > 0 && box.h > 0);
  if (!boxes.length) return { width: 640, height: 140, ports: [] };
  const drawW = Math.max(520, Math.ceil(MIN_PITCH_X / minGap(boxes.map((box) => box.x + box.w / 2))));
  const aspect = model.width > 0 ? model.height / model.width : 0.2;
  const drawH = Math.max(drawW * aspect, Math.ceil(MIN_PITCH_Y / minGap(boxes.map((box) => box.y + box.h / 2))), 84);
  const ports = snapPortRows(boxes.map((box) => {
    const openingW = box.w * drawW;
    const openingH = box.h * drawH;
    const fiber = glyphMedium(box.type, 'RJ45') !== 'RJ45';
    const size = Math.max(14, Math.min(24, Math.min(openingW * 0.92, openingH / 0.9)));
    const glyphW = fiber ? size * 1.15 : size;
    return {
      name: box.name,
      type: box.type,
      x: MARGIN_L + box.x * drawW + Math.max(0, (openingW - glyphW) / 2),
      y: MARGIN_T + box.y * drawH + Math.max(0, (openingH - size * 0.9) / 2),
      size,
    };
  }));
  return {
    width: MARGIN_L + drawW + MARGIN_R,
    height: MARGIN_T + drawH + MARGIN_B,
    ports,
  };
}
