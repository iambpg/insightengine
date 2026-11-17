import { describe, expect, it } from 'vitest';
import type { DeviceRow, SiteRow } from '@/lib/types';
import { describeSite, laneOf } from './siteCondition';

function site(): SiteRow {
  return { id: '1', name: 'wc18', region: 'Western Cape', city: 'wc18', deviceCount: 0, health: 'healthy', alerts: 0, lastDiscovery: '—' };
}

function device(partial: Partial<DeviceRow> & Pick<DeviceRow, 'id' | 'role' | 'health' | 'formFactor'>): DeviceRow {
  return {
    hostname: partial.id,
    site: 'wc18',
    siteId: '1',
    mgmtIp: '10.0.0.2',
    modelFamily: '—',
    portsUp: 0,
    portsTotal: 0,
    portsWarn: 0,
    portsFault: 0,
    uptime: '—',
    lastPoll: '—',
    ...partial,
  };
}

describe('describeSite', () => {
  it('treats an empty site as not yet judgeable', () => {
    const story = describeSite(site(), [], []);
    expect(story.verdict.heading).toBe('Nothing to judge yet');
    expect(story.lanes.map((lane) => lane.status)).toEqual(['Not monitored', 'Not monitored', 'Not monitored']);
    expect(story.problems).toEqual([]);
  });

  it('calls a fully answering site working as expected', () => {
    const story = describeSite(site(), [
      device({ id: 'sw', role: 'Access switch', health: 'healthy', formFactor: 'access-switch-48', portsUp: 10, portsTotal: 48 }),
      device({ id: 'fw', role: 'Firewall', health: 'healthy', formFactor: 'firewall' }),
    ], []);
    expect(story.verdict.heading).toBe('Working as expected');
    expect(story.lanes.find((lane) => lane.id === 'wan')?.status).toBe('Working');
    expect(laneOf({ role: 'Sdwan', formFactor: 'firewall' })).toBe('wan');
  });
});
