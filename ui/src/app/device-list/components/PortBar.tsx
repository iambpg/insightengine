import React from 'react';
import type { DeviceRow } from '@/lib/types';

// Micro-bar showing the up / warning / fault / down share of ports; numbers sit beside it so it is not colour only.
export default function PortBar({ row }: { row: DeviceRow }) {
  const { portsUp, portsTotal, portsWarn, portsFault } = row;
  const down = Math.max(0, portsTotal - portsUp - portsWarn - portsFault);
  const pct = (n: number) => `${(n / Math.max(1, portsTotal)) * 100}%`;
  return (
    <div className="flex items-center gap-2">
      <div
        className="flex h-2 w-20 overflow-hidden rounded-full bg-muted"
        role="img"
        aria-label={`${portsUp} up, ${portsWarn} warning, ${portsFault} fault, ${down} down of ${portsTotal} ports`}
      >
        <span className="bg-success" style={{ width: pct(portsUp) }} />
        <span className="bg-warning" style={{ width: pct(portsWarn) }} />
        <span className="bg-destructive" style={{ width: pct(portsFault) }} />
        <span className="bg-down/50" style={{ width: pct(down) }} />
      </div>
      <span className="font-mono-data text-xs tabular">
        {portsUp}
        <span className="text-muted-foreground">/{portsTotal}</span>
      </span>
    </div>
  );
}