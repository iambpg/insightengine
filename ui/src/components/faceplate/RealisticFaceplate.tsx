'use client';

import React from 'react';
import type { FaceplateDevice, PortInfo } from '@/lib/types';
import { STATE_COLOR, STATE_GLYPH, STATE_LABEL } from './palette';
import { namesMatch } from './library/ifname';
import type { FaceplateModel, FaceplatePortBox } from './library/catalog';

interface Props {
  device: FaceplateDevice;
  model: FaceplateModel;
  selectedPortId?: string | null;
  onHover: (port: PortInfo | null, el: SVGGElement | null) => void;
  onSelect: (port: PortInfo) => void;
}

function livePorts(device: FaceplateDevice): PortInfo[] {
  if (device.members) return device.members.flatMap((member) => member.ports);
  if (device.modules) return device.modules.flatMap((module) => module.ports);
  return device.ports ?? [];
}

function fallbackPort(box: FaceplatePortBox): PortInfo {
  return {
    id: box.name,
    name: box.name,
    type: 'RJ45',
    speed: '—',
    state: 'unknown',
    utilisation: 0,
    errors: 0,
  };
}

function portForBox(box: FaceplatePortBox, ports: PortInfo[]): PortInfo {
  return ports.find((port) => namesMatch(port.name, box.name)) ?? fallbackPort(box);
}

function Hotspot({
  box,
  port,
  width,
  height,
  selected,
  onHover,
  onSelect,
}: {
  box: FaceplatePortBox;
  port: PortInfo;
  width: number;
  height: number;
  selected: boolean;
  onHover: Props['onHover'];
  onSelect: Props['onSelect'];
}) {
  const color = STATE_COLOR[port.state];
  const disabled = port.state === 'disabled';
  const label = `${port.name}, ${STATE_LABEL[port.state]}`;
  const x = box.x * width;
  const y = box.y * height;
  const w = Math.max(box.w * width, 1);
  const h = Math.max(box.h * height, 1);
  return (
    <g
      tabIndex={0}
      role="button"
      aria-label={label}
      aria-pressed={selected}
      data-testid={`port-hotspot-${box.name}`}
      className="cursor-pointer outline-none focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1"
      style={{ pointerEvents: 'all' }}
      onMouseEnter={(event) => onHover(port, event.currentTarget)}
      onMouseLeave={() => onHover(null, null)}
      onFocus={(event) => onHover(port, event.currentTarget)}
      onBlur={() => onHover(null, null)}
      onClick={(event) => {
        event.stopPropagation();
        onSelect(port);
      }}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          onSelect(port);
        }
      }}
    >
      <rect
        x={x}
        y={y}
        width={w}
        height={h}
        rx={1.5}
        fill={color.fill}
        fillOpacity={port.state === 'up' ? 0.45 : port.state === 'fault' ? 0.62 : 0.38}
        stroke={color.rim}
        strokeWidth={disabled ? 1.6 : 1.2}
        strokeDasharray={disabled ? '3 2' : undefined}
        style={{ pointerEvents: 'all' }}
      />
      <text
        x={x + w / 2}
        y={y + h + Math.max(6, height * 0.04)}
        textAnchor="middle"
        fontSize={Math.max(7, height * 0.045)}
        fill={color.fill}
        fontFamily="var(--font-mono)"
        aria-hidden="true"
        style={{ pointerEvents: 'none' }}
      >
        {STATE_GLYPH[port.state]}
      </text>
      {selected && (
        <rect x={x - 2} y={y - 2} width={w + 4} height={h + 4} fill="none" stroke="var(--cyan)" strokeWidth={1.6} strokeDasharray="3 2" style={{ pointerEvents: 'none' }} />
      )}
    </g>
  );
}

function artwork(model: FaceplateModel, width: number, height: number) {
  if (!model.front) {
    return (
      <>
        <rect x={8} y={16} width={width - 16} height={height - 32} rx={10} fill="#2c333c" stroke="#6d7886" style={{ pointerEvents: 'none' }} />
        <text x={28} y={height * 0.45} fill="#d5dde6" fontSize={22} fontFamily="var(--font-sans)" style={{ pointerEvents: 'none' }}>{model.model}</text>
      </>
    );
  }
  return (
    <image
      href={model.front}
      x={0}
      y={0}
      width={width}
      height={height}
      preserveAspectRatio="none"
      style={{ pointerEvents: 'none' }}
    />
  );
}

export default function RealisticFaceplate({ device, model, selectedPortId = null, onHover, onSelect }: Props) {
  const ports = livePorts(device);
  const width = model.width || 1000;
  const height = model.height || 180;
  // Photos stay at or below their pixel width so the bitmap is not scaled up.
  // Visio and drawn art are vectors, so they fit the row and stay sharp.
  const maxWidth = model.raster ? width : undefined;

  return (
    <div>
      <p className="mb-2 text-xs text-muted-foreground">
        {model.model}
        {model.source === 'visio' ? ' · Visio stencil' : model.source === 'photo' ? ' · device-type photo' : model.source === 'vendor' ? ' · vendor image' : ' · drawn from the port list'}
      </p>
      <div className="mx-auto w-full" style={maxWidth ? { maxWidth } : undefined}>
        <svg
          viewBox={`0 0 ${width} ${height}`}
          preserveAspectRatio="xMidYMid meet"
          role="img"
          aria-label={`${model.model} faceplate`}
          data-testid="realistic-faceplate"
          data-faceplate-source={model.source}
          style={{ width: '100%', height: 'auto', display: 'block', aspectRatio: `${width} / ${height}` }}
        >
          {artwork(model, width, height)}
          {model.ports.map((box) => {
            const port = portForBox(box, ports);
            return (
              <Hotspot
                key={box.name}
                box={box}
                port={port}
                width={width}
                height={height}
                selected={selectedPortId === port.id}
                onHover={onHover}
                onSelect={onSelect}
              />
            );
          })}
        </svg>
      </div>
    </div>
  );
}
