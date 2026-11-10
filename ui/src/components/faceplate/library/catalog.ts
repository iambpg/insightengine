import { useEffect, useState } from 'react';
import type { FaceplateDevice } from '@/lib/types';
import { faceplatePortCount } from './assign';
import { isFortiGateModel } from './fortigate';
import { matchDeviceType, type CatalogEntry } from './match';

export interface FaceplatePortBox {
  name: string;
  type?: string;
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface FaceplateModel {
  slug: string;
  model: string;
  partNumber: string;
  manufacturer: string;
  vendor: string;
  source: string;
  front: string;
  rear: string;
  width: number;
  height: number;
  raster: boolean;
  ports: FaceplatePortBox[];
}

interface IndexFile {
  entries: CatalogEntry[];
}

let indexPromise: Promise<CatalogEntry[]> | null = null;
const modelCache = new Map<string, Promise<FaceplateModel | null>>();

function loadModel(slug: string): Promise<FaceplateModel | null> {
  const cached = modelCache.get(slug);
  if (cached) return cached;
  const pending = Promise.resolve()
    .then(() => {
      if (typeof fetch !== 'function') return null;
      return fetch(`/faceplates/models/${encodeURIComponent(slug)}.json`).then((response) => (response.ok ? response.json() : null));
    })
    .catch(() => null) as Promise<FaceplateModel | null>;
  modelCache.set(slug, pending);
  return pending;
}

export function loadFaceplateIndex(): Promise<CatalogEntry[]> {
  if (!indexPromise) {
    indexPromise = fetch('/faceplates/index.json')
      .then((response) => (response.ok ? response.json() : { entries: [] }))
      .then((body: IndexFile) => body.entries || [])
      .catch(() => []);
  }
  return indexPromise;
}

/** FortiGate openings come from the front image. Other pictures must match the NetBox port count. */
export function keepFaceplateModel(body: FaceplateModel, portCount: number): boolean {
  if (!body.ports.length) return false;
  if (isFortiGateModel(body)) return true;
  return portCount > 0 && body.ports.length === portCount;
}

export function useFaceplateModel(device: FaceplateDevice): FaceplateModel | null {
  const [model, setModel] = useState<FaceplateModel | null>(null);
  const slug = device.slug || '';
  const partNumber = device.partNumber || '';
  const modelName = device.model || device.modelName || '';
  const manufacturer = device.manufacturer || '';
  const portCount = faceplatePortCount(device);

  useEffect(() => {
    let cancel = false;
    if (!slug && !partNumber && !modelName) {
      setModel(null);
      return undefined;
    }
    loadFaceplateIndex()
      .then((entries) => {
        if (cancel) return null;
        const match = matchDeviceType({ slug, partNumber, model: modelName, manufacturer }, entries);
        if (!match) return null;
        return loadModel(match.slug);
      })
      .then((body) => {
        if (cancel) return;
        // A switch picture is kept only when it has the same number of openings.
        // A FortiGate uses its own front image's port map even when NetBox lists fewer interfaces.
        if (body && keepFaceplateModel(body, portCount)) setModel(body);
        else setModel(null);
      })
      .catch(() => {
        if (!cancel) setModel(null);
      });
    return () => {
      cancel = true;
    };
    // portCount is the NetBox opening count. The picture is dropped when it disagrees.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [slug, partNumber, modelName, manufacturer, portCount]);

  return model;
}
