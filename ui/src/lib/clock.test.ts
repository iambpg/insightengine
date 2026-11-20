import { describe, expect, it } from 'vitest';
import { buildSeries } from '@/lib/mockData';
import { epochMs, formatClock, formatTick, formatWhen } from '@/lib/clock';

describe('clock', () => {
  it('shows the local time and a timezone name', () => {
    const date = new Date('2026-11-20T05:19:08Z');
    const text = formatClock(date);
    const time = date.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
    expect(text.startsWith(time)).toBe(true);
    expect(text.length).toBeGreaterThan(time.length);
  });

  it('reads a UTC stamp in local time', () => {
    const text = formatWhen('2026-11-20 05:19:08');
    const date = new Date('2026-11-20T05:19:08Z');
    const time = date.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
    expect(text).toContain(time);
    expect(text).not.toMatch(/UTC$/);
  });

  it('labels a five minute axis with seconds and a day-long axis with hours', () => {
    const ms = Date.UTC(2026, 10, 20, 5, 7, 9);
    const date = new Date(ms);
    const pad = (value: number) => String(value).padStart(2, '0');
    const hours = `${pad(date.getHours())}:${pad(date.getMinutes())}`;
    expect(formatTick(ms, 5 * 60 * 1000)).toBe(`${hours}:${pad(date.getSeconds())}`);
    expect(formatTick(ms, 24 * 60 * 60 * 1000)).toBe(hours);
    expect(epochMs(1_700_000_000)).toBe(1_700_000_000_000);
  });

  it('ends a five minute series at the current time', () => {
    const series = buildSeries('5m', 3);
    expect(series).toHaveLength(30);
    expect(Math.abs(series[series.length - 1].t - Date.now())).toBeLessThan(5000);
    expect(series[0].t).toBeLessThan(series[series.length - 1].t);
    expect(series[series.length - 1].label).toMatch(/\d{2}:\d{2}:\d{2}/);
    expect(series.some((point) => point.discards != null)).toBe(true);
  });
});
