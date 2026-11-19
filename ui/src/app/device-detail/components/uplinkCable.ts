import type { PortInfo } from '@/lib/types';
import { namesMatch } from '@/components/faceplate/library/ifname';

/** The faceplate port the parent cable plugs into. */
export function portIsUplink(port: PortInfo | null | undefined, uplink: string): boolean {
  const wanted = (uplink || '').trim();
  if (!port || !wanted) return false;
  return [port.name, ...(port.names || [])].some((name) => namesMatch(name, wanted));
}

/** The jack is inside the faceplate's visible frame, not scrolled off it. */
export function rectsOverlap(port: Pick<DOMRect, 'left' | 'right' | 'top' | 'bottom'>, frame: Pick<DOMRect, 'left' | 'right' | 'top' | 'bottom'>): boolean {
  const width = Math.min(port.right, frame.right) - Math.max(port.left, frame.left);
  const height = Math.min(port.bottom, frame.bottom) - Math.max(port.top, frame.top);
  return width > 1 && height > 1;
}

export interface CableFlow {
  /** Bits arriving on this switch from the parent. */
  inbound: boolean;
  /** Bits leaving this switch toward the parent. */
  outbound: boolean;
  /** Seconds for one dash to travel the cable. Faster when the port is busier. */
  seconds: number;
}

const QUIET = new Set(['down', 'disabled', 'not-connected']);

/** Motion inside the cable. Null when the port is not passing traffic. */
export function cableFlow(port: PortInfo | null | undefined): CableFlow | null {
  if (!port || QUIET.has(port.state)) return null;
  const inboundBps = port.inBps ?? 0;
  const outboundBps = port.outBps ?? 0;
  const util = port.utilisation || 0;
  if (inboundBps <= 0 && outboundBps <= 0 && util <= 0) return null;
  const inbound = inboundBps > 0;
  const outbound = outboundBps > 0 || (!inbound && util > 0);
  const busiest = Math.max(inboundBps, outboundBps);
  const level = util > 0 ? util : Math.min(100, Math.log10(Math.max(busiest, 10)) * 14);
  const clamped = Math.max(0, Math.min(100, level));
  return {
    inbound,
    outbound,
    seconds: Math.round((2.4 - (clamped / 100) * 2) * 100) / 100,
  };
}
