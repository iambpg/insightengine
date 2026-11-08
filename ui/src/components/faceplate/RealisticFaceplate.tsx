'use client';

import React, { useLayoutEffect, useRef, useState } from 'react';
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

function hotspots({
  model,
  ports,
  width,
  height,
  selectedPortId,
  onHover,
  onSelect,
}: {
  model: FaceplateModel;
  ports: PortInfo[];
  width: number;
  height: number;
  selectedPortId: string | null;
  onHover: Props['onHover'];
  onSelect: Props['onSelect'];
}) {
  return model.ports.map((box) => {
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
  });
}

export default function RealisticFaceplate({ device, model, selectedPortId = null, onHover, onSelect }: Props) {
  const ports = livePorts(device);
  const frameRef = useRef<HTMLDivElement>(null);
  const [box, setBox] = useState({ w: model.width || 1000, h: model.height || 180 });
  const [scale, setScale] = useState(1);
  const width = box.w;
  const height = box.h;

  function rememberNatural(event: React.SyntheticEvent<HTMLImageElement>) {
    const img = event.currentTarget;
    // naturalWidth is the bitmap's pixel width. It is not multiplied by
    // devicePixelRatio: both the image and the overlay live in CSS pixels,
    // and the browser paints the bitmap onto the device grid.
    if (img.naturalWidth > 0 && img.naturalHeight > 0) {
      setBox({ w: img.naturalWidth, h: img.naturalHeight });
    }
  }

  useLayoutEffect(() => {
    const node = frameRef.current;
    if (!node || typeof ResizeObserver === 'undefined') return undefined;
    const measure = () => {
      const available = node.clientWidth;
      if (!available || !width) return;
      const fit = available / width;
      // Photos are not scaled above their natural pixel width. Vectors may grow.
      setScale(model.raster ? Math.min(1, fit) : fit);
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    return () => observer.disconnect();
  }, [width, model.raster]);

  const caption = model.source === 'visio'
    ? ' · Visio stencil'
    : model.source === 'photo'
      ? ' · device-type photo'
      : model.source === 'vendor'
        ? ' · vendor image'
        : ' · drawn from the port list';

  return (
    <div>
      <p className="mb-2 text-xs text-muted-foreground">
        {model.model}
        {caption}
      </p>
      {model.front ? (
        <div
          ref={frameRef}
          className="mx-auto w-full"
          style={{ maxWidth: model.raster ? width : undefined, height: height * scale, padding: 0, border: 'none' }}
        >
          <div
            data-testid="faceplate-stage"
            style={{
              width,
              height,
              transform: `scale(${scale})`,
              transformOrigin: 'top left',
              position: 'relative',
              lineHeight: 0,
              padding: 0,
              border: 'none',
            }}
          >
            <img
              src={model.front}
              alt=""
              data-testid="faceplate-image"
              width={width}
              height={height}
              draggable={false}
              onLoad={rememberNatural}
              style={{
                display: 'block',
                width,
                height,
                objectFit: 'none',
                objectPosition: 'left top',
                pointerEvents: 'none',
                padding: 0,
                border: 'none',
              }}
            />
            <svg
              viewBox={`0 0 ${width} ${height}`}
              preserveAspectRatio="none"
              role="img"
              aria-label={`${model.model} faceplate`}
              data-testid="realistic-faceplate"
              data-faceplate-source={model.source}
              style={{ position: 'absolute', left: 0, top: 0, width, height, display: 'block', padding: 0 }}
            >
              {hotspots({ model, ports, width, height, selectedPortId, onHover, onSelect })}
            </svg>
          </div>
        </div>
      ) : (
        <svg
          viewBox={`0 0 ${width} ${height}`}
          preserveAspectRatio="xMidYMid meet"
          role="img"
          aria-label={`${model.model} faceplate`}
          data-testid="realistic-faceplate"
          data-faceplate-source={model.source}
          style={{ width: '100%', height: 'auto', display: 'block', aspectRatio: `${width} / ${height}` }}
        >
          <rect x={8} y={16} width={width - 16} height={height - 32} rx={10} fill="#2c333c" stroke="#6d7886" style={{ pointerEvents: 'none' }} />
          <text x={28} y={height * 0.45} fill="#d5dde6" fontSize={22} fontFamily="var(--font-sans)" style={{ pointerEvents: 'none' }}>{model.model}</text>
          {hotspots({ model, ports, width, height, selectedPortId, onHover, onSelect })}
        </svg>
      )}
    </div>
  );
}
