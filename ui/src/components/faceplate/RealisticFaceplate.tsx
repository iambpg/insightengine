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

function Artwork({ model, zoomed }: { model: FaceplateModel; zoomed: boolean }) {
  const native = Math.max(1, model.width);
  if (!model.front) {
    return (
      <svg viewBox="0 0 1000 180" className="block h-auto w-full" role="img" aria-hidden="true">
        <rect x="8" y="16" width="984" height="148" rx="10" fill="#2c333c" stroke="#6d7886" />
        <rect x="8" y="16" width="984" height="18" rx="8" fill="#3a424c" />
        <text x="28" y="78" fill="#d5dde6" fontSize="22" fontFamily="var(--font-sans)">{model.model}</text>
        <text x="28" y="108" fill="#8a97ab" fontSize="14" fontFamily="var(--font-mono)">{model.partNumber || model.manufacturer}</text>
      </svg>
    );
  }
  const style: React.CSSProperties = model.raster
    ? { width: '100%', maxWidth: native, height: 'auto' }
    : { width: '100%', maxWidth: zoomed ? native : 1180, height: 'auto' };
  return (
    <img
      src={model.front}
      alt=""
      width={model.width}
      height={model.height}
      draggable={false}
      style={style}
      className="block"
    />
  );
}

export default function RealisticFaceplate({ device, model, selectedPortId = null, onHover, onSelect }: Props) {
  const [zoom, setZoom] = useState(false);
  const ports = livePorts(device);
  const width = model.width || 1000;
  const height = model.height || 180;
  const frameStyle: React.CSSProperties = model.raster
    ? { width: '100%', maxWidth: width }
    : { width: '100%', maxWidth: zoom ? width : 1180 };

  const overlay = (key: string) => (
    <svg
      key={key}
      viewBox={`0 0 ${width} ${height}`}
      className="absolute inset-0 h-full w-full"
      role="presentation"
      onClick={() => setZoom(true)}
    >
      {model.ports.map((box) => {
        const port = portForBox(box, ports);
        if (!port) return null;
        return (
          <Hotspot
            key={`${key}-${box.name}`}
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

  const frame = (
    <div className="relative mx-auto" style={frameStyle} data-testid="realistic-faceplate" data-faceplate-source={model.source}>
      <Artwork model={model} zoomed={zoom} />
      {overlay('inline')}
    </div>
  );

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
      {frame}
      {zoom && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-6" role="dialog" aria-label={`${model.model} faceplate`}>
          <button type="button" className="absolute inset-0 cursor-zoom-out" aria-label="Close zoom" onClick={() => setZoom(false)} />
          <div className="relative z-10 max-h-full max-w-full overflow-auto rounded-md bg-background p-3">
            <div className="relative" style={{ width: model.raster ? width : Math.min(width, 1600) }}>
              <Artwork model={{ ...model, raster: model.raster }} zoomed />
              {overlay('zoom')}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
