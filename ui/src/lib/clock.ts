/** Local clock for the monitoring screens. Server stamps without a zone are UTC. */

export function timeZoneName(date = new Date()): string {
  const part = new Intl.DateTimeFormat(undefined, { timeZoneName: 'short' })
    .formatToParts(date)
    .find((item) => item.type === 'timeZoneName');
  return part?.value ?? '';
}

export function formatClock(date = new Date()): string {
  const time = date.toLocaleTimeString(undefined, {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  });
  const zone = timeZoneName(date);
  return zone ? `${time} ${zone}` : time;
}

/** Prometheus seconds and millisecond epochs both become milliseconds. */
export function epochMs(value: unknown): number | null {
  if (typeof value !== 'number' || !Number.isFinite(value) || value <= 0) return null;
  return value < 1e11 ? value * 1000 : value;
}

function pad(value: number): string {
  return String(value).padStart(2, '0');
}

/** Axis tick. Short windows include seconds so a 5 minute graph is readable. */
export function formatTick(ms: number, spanMs: number): string {
  const date = new Date(ms);
  const clock = spanMs <= 20 * 60 * 1000
    ? `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
    : `${pad(date.getHours())}:${pad(date.getMinutes())}`;
  if (spanMs > 36 * 60 * 60 * 1000) {
    const day = date.toLocaleDateString(undefined, { day: 'numeric', month: 'short' });
    return `${day} ${clock}`;
  }
  return clock;
}

function asUtc(value: string): string {
  const trimmed = value.trim().replace(/\s+UTC$/i, '');
  if (/^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}/.test(trimmed) && !/[zZ]|[+-]\d{2}:?\d{2}$/.test(trimmed)) {
    return `${trimmed.replace(' ', 'T')}Z`;
  }
  return trimmed;
}

export function formatWhen(value: Date | string | number | null | undefined): string {
  if (value == null || value === '') return '—';
  const date = value instanceof Date
    ? value
    : new Date(typeof value === 'number' ? (epochMs(value) ?? value) : asUtc(value));
  if (Number.isNaN(date.getTime())) return String(value);
  const day = date.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: '2-digit' });
  const time = date.toLocaleTimeString(undefined, {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  });
  const zone = timeZoneName(date);
  return zone ? `${day} ${time} ${zone}` : `${day} ${time}`;
}
