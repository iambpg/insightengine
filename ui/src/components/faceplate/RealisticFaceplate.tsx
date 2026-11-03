'use client';

import React, { useState } from 'react';
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

function portForBox(box: FaceplatePortBox, ports: PortInfo[]): PortInfo | undefined {
  return ports.find((port) => namesMatch(port.name, box.name));
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
  const label = `${port.name}, ${STATE_LABEL[port.state]}, ${port.speed}, ${port.utilisation}% utilisation, ${port.errors} errors`;
  const x = box.x * width;
  const y = box.y * height;
  const w = box.w * width;
  const h = box.h * height;
  return (
    <g
      tabIndex={0}
      role="button"
      aria-label={label}
      aria-pressed={selected}
      className="cursor-pointer outline-none"
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
      />
      <text
        x={x + w / 2}
        y={y + h + Math.max(6, height * 0.04)}
        textAnchor="middle"
        fontSize={Math.max(7, height * 0.045)}
        fill={color.fill}
        fontFamily="var(--font-mono)"
        aria-hidden="true"
      >
        {STATE_GLYPH[port.state]}
      </text>
      {selected && (
        <rect x={x - 2} y={y - 2} width={w + 4} height={h + 4} fill="none" stroke="var(--cyan)" strokeWidth={1.6} strokeDasharray="3 2" />
      )}
    </g>
  );
}

function Panel({
  model,
  ports,
  selectedPortId,
  onHover,
  onSelect,
  zoomed,
  onZoom,
}: {
  model: FaceplateModel;
  ports: PortInfo[];
  selectedPortId: string | null;
  onHover: Props['onHover'];
  onSelect: Props['onSelect'];
  zoomed: boolean;
  onZoom: () => void;
}) {
  // One SVG holds the artwork and the hotspots. Both use the image's native
  // viewBox, and preserveAspectRatio is none, so a CSS resize cannot shift
  // the highlights relative to the picture. Raster photos are capped at their
  // pixel size; Visio drawings are vectors and may scale down to fit.
  const width = model.width || 1000;
  const height = model.height || 180;
  // Photos stop at their pixel width. Visio art is a vector, so it can grow to
  // the row width; the viewBox keeps the hotspots on the same points.
  const maxWidth = model.raster ? width : zoomed ? 1600 : 1180;
  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      role="presentation"
      data-testid="realistic-faceplate"
      data-faceplate-source={model.source}
      onClick={onZoom}
      style={{ width: '100%', maxWidth, height: 'auto', display: 'block', aspectRatio: `${width} / ${height}` }}
    >
      {model.front ? (
        <image href={model.front} x={0} y={0} width={width} height={height} preserveAspectRatio="none" />
      ) : (
        <>
          <rect x={8} y={16} width={width - 16} height={height - 32} rx={10} fill="#2c333c" stroke="#6d7886" />
          <text x={28} y={height * 0.45} fill="#d5dde6" fontSize={22} fontFamily="var(--font-sans)">{model.model}</text>
        </>
      )}
      {model.ports.map((box) => {
        const port = portForBox(box, ports);
        if (!port) return null;
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
  );
}

export default function RealisticFaceplate({ device, model, selectedPortId = null, onHover, onSelect }: Props) {
  const [zoom, setZoom] = useState(false);
  const ports = livePorts(device);
  const width = model.width || 1000;

  return (
    <div>
      <div className="mb-2 flex items-center justify-between gap-2 text-xs text-muted-foreground">
        <span>
          {model.model}
          {model.source === 'visio' ? ' · Visio stencil' : model.source === 'photo' ? ' · device-type photo' : model.source === 'vendor' ? ' · vendor image' : ' · drawn from the port list'}
        </span>
        <button
          type="button"
          onClick={() => setZoom(true)}
          className="rounded border border-border px-2 py-0.5 font-medium text-foreground hover:bg-muted"
        >
          Zoom
        </button>
      </div>
      <div className="mx-auto" style={{ maxWidth: model.raster ? width : 1180 }}>
        <Panel model={model} ports={ports} selectedPortId={selectedPortId} onHover={onHover} onSelect={onSelect} zoomed={false} onZoom={() => setZoom(true)} />
      </div>
      {zoom && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-6" role="dialog" aria-label={`${model.model} faceplate`}>
          <button type="button" className="absolute inset-0 cursor-zoom-out" aria-label="Close zoom" onClick={() => setZoom(false)} />
          <div className="relative z-10 max-h-full max-w-full overflow-auto rounded-md bg-background p-3">
            <Panel model={model} ports={ports} selectedPortId={selectedPortId} onHover={onHover} onSelect={onSelect} zoomed onZoom={() => undefined} />
          </div>
        </div>
      )}
    </div>
  );
}
