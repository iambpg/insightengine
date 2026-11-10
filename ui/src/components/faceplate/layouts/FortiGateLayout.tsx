'use client';

import React from 'react';
import type { PortInfo } from '@/lib/types';
import ChassisBody, { EngravedText, StatusLeds, VentGrille } from '../Chassis';
import type { FaceplateModel } from '../library/catalog';
import { glyphMedium, placeFortiGatePorts } from '../library/fortigate';
import { ifaceCompact } from '../library/ifname';
import PortGlyph from '../Port';
import type { LayoutCommon } from './SwitchLayout';

interface Props extends LayoutCommon {
  model: FaceplateModel;
  ports: PortInfo[];
}

function openingPort(name: string, boxType: string | undefined, ports: PortInfo[]): PortInfo {
  const wanted = ifaceCompact(name);
  const live = ports.find((port) => ifaceCompact(port.name) === wanted);
  const base: PortInfo = live ?? {
    id: name,
    name,
    type: 'RJ45',
    speed: '—',
    state: 'unknown',
    utilisation: 0,
    errors: 0,
  };
  const type = glyphMedium(boxType, base.type);
  return type === base.type ? base : { ...base, type };
}

/** Switch chassis, with each opening sitting where the NetBox front image places it. */
export default function FortiGateLayout({ model, ports, uid, selectedId, onHover, onSelect }: Props) {
  const canvas = placeFortiGatePorts(model);
  const anyFault = ports.some((port) => port.state === 'fault');
  const anyWarn = ports.some((port) => port.state === 'warning');
  return (
    <ChassisBody x={0} y={0} w={canvas.width} h={canvas.height} uid={uid}>
      <VentGrille x={10} y={12} w={12} h={28} uid={uid} />
      <StatusLeds
        x={28}
        y={12}
        uid={uid}
        items={[
          { label: 'SYS', color: anyFault ? 'var(--destructive)' : anyWarn ? 'var(--warning)' : 'var(--success)', blink: anyWarn && !anyFault },
          { label: 'PWR', color: 'var(--success)' },
          { label: 'HA', color: 'var(--down)' },
        ]}
      />
      <EngravedText x={28} y={canvas.height - 8} size={4.8}>{model.model || 'FORTIGATE'}</EngravedText>
      {canvas.ports.map((opening) => {
        const port = openingPort(opening.name, opening.type, ports);
        return (
          <PortGlyph
            key={opening.name}
            port={port}
            x={opening.x}
            y={opening.y}
            size={opening.size}
            uid={uid}
            selected={selectedId === port.id}
            showLabel
            labelBelow
            labelText={opening.name}
            onHover={onHover}
            onSelect={onSelect}
          />
        );
      })}
    </ChassisBody>
  );
}
