/**
 * Match a NetBox device type (model, part number or slug) to a library entry.
 * The longest exact key wins, so C9300-48P does not become C9300-48P-E.
 */

export interface CatalogQuery {
  model?: string;
  partNumber?: string;
  slug?: string;
  manufacturer?: string;
}

export interface CatalogEntry {
  slug: string;
  model: string;
  partNumber: string;
  manufacturer: string;
  vendor: string;
  source: 'visio' | 'photo' | 'vendor' | 'drawn' | string;
}

const STRIP = ['ciscocatalyst', 'paloaltonetworks', 'paloalto', 'fortigate', 'fortinet', 'cisco', 'meraki', 'catalyst'];

export function normalizeModelKey(value: string): string {
  const text = (value || '').toLowerCase().replace(/\bplus\b/g, '+');
  return text.replace(/[^a-z0-9+]+/g, '');
}

export function modelKeys(value: string): string[] {
  const key = normalizeModelKey(value);
  if (key.length < 3) return [];
  const keys = new Set<string>([key]);
  for (const prefix of STRIP) {
    if (key.startsWith(prefix) && key.length - prefix.length >= 3) keys.add(key.slice(prefix.length));
  }
  if (key.startsWith('wsc') && key.length > 5) keys.add(key.slice(3));
  else if (key.startsWith('ws') && key.length > 4) keys.add(key.slice(2));
  return [...keys];
}

function entryKeys(entry: CatalogEntry): string[] {
  return [...new Set([...modelKeys(entry.slug), ...modelKeys(entry.model), ...modelKeys(entry.partNumber)])];
}

function score(query: CatalogQuery, entry: CatalogEntry): number {
  const slug = normalizeModelKey(query.slug || '');
  const part = normalizeModelKey(query.partNumber || '');
  const model = normalizeModelKey(query.model || '');
  const entrySlug = normalizeModelKey(entry.slug);
  const entryPart = normalizeModelKey(entry.partNumber);
  const entryModel = normalizeModelKey(entry.model);
  if (slug && slug === entrySlug) return 100;
  if (part && part === entryPart) return 96;
  if (model && model === entryModel) return 92;
  if (part && part === entryModel) return 90;
  if (model && model === entryPart) return 90;
  const wanted = new Set([...modelKeys(query.slug || ''), ...modelKeys(query.partNumber || ''), ...modelKeys(query.model || '')]);
  const known = entryKeys(entry);
  let best = 0;
  for (const key of known) {
    if (wanted.has(key)) best = Math.max(best, 70 + Math.min(20, key.length / 5));
  }
  return best;
}

export function matchDeviceType(query: CatalogQuery, entries: CatalogEntry[]): CatalogEntry | null {
  let best: CatalogEntry | null = null;
  let bestScore = 0;
  let bestLength = 0;
  for (const entry of entries) {
    const value = score(query, entry);
    const length = normalizeModelKey(entry.partNumber || entry.model).length;
    const better = value > bestScore || (value === bestScore && value > 0 && length < bestLength);
    if (better) {
      best = entry;
      bestScore = value;
      bestLength = length;
    }
  }
  return bestScore > 0 ? best : null;
}
