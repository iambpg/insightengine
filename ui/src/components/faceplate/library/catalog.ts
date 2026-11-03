import { useEffect, useState } from 'react';
import type { FaceplateDevice } from '@/lib/types';
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

export function loadFaceplateIndex(): Promise<CatalogEntry[]> {
  if (!indexPromise) {
    indexPromise = fetch('/faceplates/index.json')
      .then((response) => (response.ok ? response.json() : { entries: [] }))
      .then((body: IndexFile) => body.entries || [])
      .catch(() => []);
  }
  return indexPromise;
}

export function useFaceplateModel(device: FaceplateDevice): FaceplateModel | null {
  const [model, setModel] = useState<FaceplateModel | null>(null);
  const slug = device.slug || '';
  const partNumber = device.partNumber || '';
  const modelName = device.model || device.modelName || '';
  const manufacturer = device.manufacturer || '';

  useEffect(() => {
    let cancel = false;
    if (!slug && !partNumber && !modelName) {
      setModel(null);
      return undefined;
    }
    loadFaceplateIndex().then((entries) => {
      if (cancel) return;
      const match = matchDeviceType({ slug, partNumber, model: modelName, manufacturer }, entries);
      if (!match) {
        setModel(null);
        return;
      }
      fetch(`/faceplates/models/${encodeURIComponent(match.slug)}.json`)
        .then((response) => (response.ok ? response.json() : null))
        .then((body: FaceplateModel | null) => {
          if (!cancel) setModel(body);
        })
        .catch(() => {
          if (!cancel) setModel(null);
        });
    });
    return () => {
      cancel = true;
    };
  }, [slug, partNumber, modelName, manufacturer]);

  return model;
}
