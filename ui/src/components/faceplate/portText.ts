/** Interface name, including the short and long forms. A description stored as the name is left out. */
export function portNameLine(port: { name: string; names?: string[]; description?: string }): string {
  const description = (port.description || '').trim().toLowerCase();
  const stored = (port.name || '').trim();
  const extras = port.names || [];
  const storedIsDescription = Boolean(description) && stored.toLowerCase() === description && extras.length > 0;
  const seen = new Set<string>();
  const names: string[] = [];
  for (const raw of storedIsDescription ? extras : [stored, ...extras]) {
    const text = (raw || '').trim();
    const key = text.toLowerCase();
    if (!text || seen.has(key)) continue;
    seen.add(key);
    names.push(text);
  }
  return names.join(' · ');
}
