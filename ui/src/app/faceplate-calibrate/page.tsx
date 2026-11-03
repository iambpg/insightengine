'use client';

import React, { useEffect, useMemo, useState } from 'react';
import AppLayout from '@/components/AppLayout';
import { loadFaceplateIndex } from '@/components/faceplate/library/catalog';
import type { FaceplateModel, FaceplatePortBox } from '@/components/faceplate/library/catalog';
import type { CatalogEntry } from '@/components/faceplate/library/match';

/**
 * Dev tool for placing port hotspots. Drag a box, then download the model JSON
 * and replace ui/public/faceplates/models/<slug>.json.
 */
export default function FaceplateCalibratePage() {
  return (
    <AppLayout>
      <Calibrator />
    </AppLayout>
  );
}

function Calibrator() {
  const [entries, setEntries] = useState<CatalogEntry[]>([]);
  const [slug, setSlug] = useState('');
  const [model, setModel] = useState<FaceplateModel | null>(null);
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    loadFaceplateIndex().then((rows) => {
      setEntries(rows);
      if (rows[0]) setSlug(rows[0].slug);
    });
  }, []);

  useEffect(() => {
    if (!slug) return undefined;
    let cancel = false;
    fetch(`/faceplates/models/${encodeURIComponent(slug)}.json`)
      .then((response) => response.json())
      .then((body: FaceplateModel) => {
        if (!cancel) {
          setModel(body);
          setSelected(body.ports[0]?.name ?? null);
        }
      })
      .catch(() => {
        if (!cancel) setModel(null);
      });
    return () => {
      cancel = true;
    };
  }, [slug]);

  const width = model?.width || 1000;
  const height = model?.height || 180;

  function move(name: string, dx: number, dy: number) {
    setModel((current) => {
      if (!current) return current;
      return {
        ...current,
        ports: current.ports.map((port) => (
          port.name === name
            ? { ...port, x: clamp(port.x + dx, 0, 0.98), y: clamp(port.y + dy, 0, 0.98) }
            : port
        )),
      };
    });
  }

  function download() {
    if (!model) return;
    const blob = new Blob([JSON.stringify(model, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `${model.slug}.json`;
    link.click();
    URL.revokeObjectURL(url);
  }

  const selectedPort = useMemo(
    () => model?.ports.find((port) => port.name === selected) ?? null,
    [model, selected],
  );

  return (
    <div className="space-y-4">
      <header>
        <h1 className="text-xl font-semibold">Faceplate hotspot calibration</h1>
        <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
          Drag a port box until it sits on the physical opening. Download the JSON and save it as
          {' '}<code>ui/public/faceplates/models/{slug || '<slug>'}.json</code>.
          Coordinates are fractions of the image, so the overlay stays aligned when the picture scales.
        </p>
      </header>
      <div className="flex flex-wrap items-end gap-3">
        <label className="text-sm">
          Model
          <select
            className="mt-1 block rounded border border-border bg-card px-2 py-1"
            value={slug}
            onChange={(event) => setSlug(event.target.value)}
          >
            {entries.map((entry) => (
              <option key={entry.slug} value={entry.slug}>{entry.model || entry.slug}</option>
            ))}
          </select>
        </label>
        <button type="button" onClick={download} className="rounded bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground">
          Download JSON
        </button>
      </div>
      {model && (
        <div className="grid gap-4 lg:grid-cols-[1fr_240px]">
          <div className="relative mx-auto w-full" style={{ maxWidth: model.raster ? width : 1100 }}>
            {model.front ? (
              <img src={model.front} alt="" width={width} height={height} className="block h-auto w-full" style={model.raster ? { maxWidth: width } : undefined} />
            ) : (
              <div className="h-40 rounded bg-muted" />
            )}
            <svg viewBox={`0 0 ${width} ${height}`} className="absolute inset-0 h-full w-full">
              {model.ports.map((port) => (
                <DraggableBox
                  key={port.name}
                  port={port}
                  width={width}
                  height={height}
                  active={port.name === selected}
                  onSelect={() => setSelected(port.name)}
                  onMove={(dx, dy) => move(port.name, dx, dy)}
                />
              ))}
            </svg>
          </div>
          <aside className="text-sm">
            <p className="font-medium">{selectedPort?.name || 'Select a port'}</p>
            <ul className="mt-2 max-h-80 overflow-auto text-xs">
              {model.ports.map((port) => (
                <li key={port.name}>
                  <button type="button" className={port.name === selected ? 'font-semibold text-foreground' : 'text-muted-foreground'} onClick={() => setSelected(port.name)}>
                    {port.name}
                  </button>
                </li>
              ))}
            </ul>
          </aside>
        </div>
      )}
    </div>
  );
}

function DraggableBox({
  port,
  width,
  height,
  active,
  onSelect,
  onMove,
}: {
  port: FaceplatePortBox;
  width: number;
  height: number;
  active: boolean;
  onSelect: () => void;
  onMove: (dx: number, dy: number) => void;
}) {
  return (
    <rect
      x={port.x * width}
      y={port.y * height}
      width={port.w * width}
      height={port.h * height}
      fill={active ? 'rgba(23,166,114,0.45)' : 'rgba(59,123,240,0.28)'}
      stroke={active ? '#17a672' : '#3b7bf0'}
      strokeWidth={1.4}
      className="cursor-move"
      onPointerDown={(event) => {
        onSelect();
        const svg = (event.currentTarget.ownerSVGElement as SVGSVGElement);
        const start = clientToSvg(svg, event.clientX, event.clientY);
        const move = (pointer: PointerEvent) => {
          const point = clientToSvg(svg, pointer.clientX, pointer.clientY);
          onMove((point.x - start.x) / width, (point.y - start.y) / height);
          start.x = point.x;
          start.y = point.y;
        };
        const up = () => {
          window.removeEventListener('pointermove', move);
          window.removeEventListener('pointerup', up);
        };
        window.addEventListener('pointermove', move);
        window.addEventListener('pointerup', up);
      }}
    />
  );
}

function clientToSvg(svg: SVGSVGElement, clientX: number, clientY: number) {
  const point = svg.createSVGPoint();
  point.x = clientX;
  point.y = clientY;
  const matrix = svg.getScreenCTM();
  if (!matrix) return { x: 0, y: 0 };
  const mapped = point.matrixTransform(matrix.inverse());
  return { x: mapped.x, y: mapped.y };
}

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}
