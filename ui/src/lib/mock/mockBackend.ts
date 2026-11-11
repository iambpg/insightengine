import {
  SUMMARY,
  TOTAL_DEVICES,
  TOTAL_SITES,
  buildAlerts,
  buildDeviceDetail,
  buildDeviceRows,
  buildResourceSeries,
  buildSeries,
  buildSiteDevices,
  buildSiteRows,
  buildTopPorts,
  type RangeKey,
} from '@/lib/mockData';
import type { DeviceQuery, Paged, SiteQuery } from '@/lib/apiClient';
import type { AlertItem, DeviceDetailData, DeviceRow, SeriesPoint, SiteRow } from '@/lib/types';
import { mockLogin } from '@/lib/mock/mockAuth';
import {
  approveUnapproved,
  discoverDevice as beginDeviceDiscover,
  getDeviceDiscovery as readDeviceDiscovery,
  listScans as scanList,
  listUnapproved,
  rejectUnapproved,
  resetDiscoveryStore,
  setRoles,
  setSites,
  startScan as beginScan,
} from '@/lib/mock/discoveryStore';
import { readMockSetupState } from '@/lib/mock/setupState';
import {
  addMib,
  deleteMib as removeMib,
  diffSettingsFile,
  fileHistory as historyEntries,
  historyDocument,
  listMibs as mibList,
  listSettingsApps,
  readSettingsFile,
  resetSettingsStore,
  restoreHistory as restoreVersion,
  runAppAction,
  saveSettingsFile,
  settingsAudit,
  settingsOverview,
  validateSettingsFile,
} from '@/lib/mock/store';
import type { ApproveBody, AuditQuery, LoginResult, SaveFileBody } from '@/lib/contract';
import { ApiError } from '@/lib/apiError';
import { readSession } from '@/lib/session';
import type { Session } from '@/lib/session';

const delay = (ms: number) =>
  new Promise<void>((resolve) => setTimeout(resolve, process.env.VITEST ? 0 : ms));

function asSeed(value: string | number): number {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  let hash = 0;
  const text = String(value);
  for (let i = 0; i < text.length; i += 1) hash = (hash * 31 + text.charCodeAt(i)) % 100000;
  return hash + 1;
}

function mockSiteIndex(siteId: string | number): number {
  if (typeof siteId === 'number' && Number.isFinite(siteId)) return siteId;
  const text = String(siteId);
  const tagged = /^site-0*(\d+)$/i.exec(text);
  if (tagged) return Math.max(0, Number(tagged[1]) - 1);
  const numeric = Number(text);
  return Number.isFinite(numeric) ? numeric : 0;
}

export function resetMockBackend(): void {
  resetSettingsStore();
  resetDiscoveryStore();
}

export async function getSummary() {
  await delay(250);
  return { ...SUMMARY, isExampleData: true as const };
}

export async function listDevices(query: DeviceQuery): Promise<Paged<DeviceRow>> {
  await delay(320);
  const windowSize = 400;
  const startWindow = Math.floor(((query.page - 1) * query.pageSize) / windowSize) * windowSize;
  let rows = buildDeviceRows(startWindow, windowSize);
  if (query.search.trim()) {
    const needle = query.search.trim().toLowerCase();
    rows = rows.filter(
      (row) =>
        row.hostname.toLowerCase().includes(needle) ||
        row.mgmtIp.includes(needle) ||
        row.site.toLowerCase().includes(needle)
    );
  }
  if (query.health !== 'all') rows = rows.filter((row) => row.health === query.health);
  if (query.role !== 'all') rows = rows.filter((row) => row.role === query.role);
  rows = [...rows].sort((a, b) => {
    const av = a[query.sortKey];
    const bv = b[query.sortKey];
    const cmp =
      typeof av === 'number' && typeof bv === 'number'
        ? av - bv
        : String(av).localeCompare(String(bv));
    return query.sortDir === 'asc' ? cmp : -cmp;
  });
  const filtered = Boolean(query.search.trim() || query.health !== 'all' || query.role !== 'all');
  const total = filtered ? Math.round((rows.length / windowSize) * TOTAL_DEVICES) : TOTAL_DEVICES;
  const offset = filtered
    ? ((query.page - 1) * query.pageSize) % Math.max(1, rows.length)
    : ((query.page - 1) * query.pageSize) % windowSize;
  return { rows: rows.slice(offset, offset + query.pageSize), total, isExampleData: true };
}

export async function syncNetbox(_deviceId: string) {
  await delay(40);
  return { ok: true, updated: ['model', 'serial', 'firmware'], note: '' };
}

export async function getDevice(form: string): Promise<DeviceDetailData> {
  await delay(350);
  return buildDeviceDetail(form);
}

export async function getHierarchy() {
  await delay(40);
  return { autoApply: false, roots: [], flagged: [], nodes: [] };
}

export async function saveHierarchySettings(autoApply: boolean) {
  await delay(40);
  return { autoApply };
}

export async function approveHierarchy() {
  await delay(40);
  return { results: [] };
}

const ACCESS_POINTS = [
  {
    name: 'ap-ams01-114', mac: '0.17.34.1.0.1', wlc: 'wlc-ein02', site: 'Rotterdam', netboxSite: 'Rotterdam', status: 'up', clients: 18, uptimeSeconds: 86400,
    model: 'C9120AXI', serial: 'FGL000114', ip: '10.8.1.114', location: 'floor-1', ios: '17.12.1', mode: 'local',
    neighborSwitch: 'sw-ams01', neighborPort: 'Gi1/0/14', rssiAvg: -61, snrAvg: 27,
    radios: [
      { slot: '0', channel: 36, utilization: 0.22, clients: 11, noise: -92, interference: 8, txPowerDbm: 18, width: 40, rssiAvg: -58, snrAvg: 30, band: '5' },
      { slot: '1', channel: 6, utilization: 0.41, clients: 7, noise: -88, interference: 14, txPowerDbm: 14, width: 20, rssiAvg: -64, snrAvg: 24, band: '2.4' },
    ],
    ssids: [{ ssid: 'corp', radio: '0', band: '5', clients: 11 }, { ssid: 'corp', radio: '1', band: '2.4', clients: 7 }],
  },
  { name: 'ap-ams01-115', mac: '0.17.34.1.0.2', wlc: 'wlc-ein02', site: 'Rotterdam', netboxSite: 'Rotterdam', status: 'up', clients: 4, uptimeSeconds: 43200, model: 'C9115AXI', serial: 'FGL000115', ip: '10.8.1.115', neighborSwitch: 'sw-ams01', neighborPort: 'Gi1/0/15', radios: [{ slot: '0', channel: 44, utilization: 0.08, clients: 4 }], ssids: [] },
  { name: 'ap-rot04-002', mac: '0.17.34.1.0.3', wlc: 'wlc-ein02', site: 'Rotterdam', netboxSite: '', status: 'down', clients: 0, uptimeSeconds: null, radios: [], ssids: [] },
];

export async function getAccessPointDetail(wlc: string, name: string) {
  await delay(80);
  const row = ACCESS_POINTS.find((item) => item.name === name && (!wlc || item.wlc === wlc)) || ACCESS_POINTS[0];
  return {
    accessPoint: row,
    events: [
      { t: 1700000000, what: 'channel', ap: row.name, radio: '0', from: '40', to: '36' },
      { t: 1700001000, what: 'oper', ap: row.name, radio: '', from: '0', to: '1' },
    ],
    degraded: [],
  };
}

export async function listAccessPoints(query: { wlc?: string; q?: string; page?: number; pageSize?: number }) {
  await delay(120);
  const all = ACCESS_POINTS;
  const needle = (query.q || '').toLowerCase();
  const wlc = (query.wlc || '').toLowerCase();
  const matched = all.filter((row) => (!wlc || row.wlc.toLowerCase().includes(wlc)) && (!needle || row.name.includes(needle) || row.mac.includes(needle)));
  const page = query.page || 1;
  const pageSize = query.pageSize || 50;
  const start = (page - 1) * pageSize;
  return { rows: matched.slice(start, start + pageSize), total: matched.length, page, pageSize };
}

export async function getThroughput(
  range: RangeKey,
  seed: string | number,
  customMin?: number
): Promise<SeriesPoint[]> {
  await delay(220);
  return buildSeries(range, asSeed(seed), 1, customMin);
}

export async function getDeviceLogs(_deviceId: string, hostname: string) {
  return { hostname, lines: [] as { at: string; severity: string; message: string }[], reason: 'Example data has no syslog lines.' };
}

export async function getResources(range: RangeKey, seed: string | number) {
  await delay(220);
  return buildResourceSeries(range, asSeed(seed));
}

export async function getTopPorts(seed: string | number, _range?: RangeKey, _customMin?: number) {
  await delay(180);
  return buildTopPorts(asSeed(seed));
}

export async function getPortSeries(
  portId: string,
  range: RangeKey,
  customMin?: number,
  _deviceId?: string
): Promise<SeriesPoint[]> {
  await delay(200);
  let hash = 0;
  for (let i = 0; i < portId.length; i += 1) hash = (hash * 31 + portId.charCodeAt(i)) % 100000;
  return buildSeries(range, hash + 3, 0.6, customMin);
}

export async function listSites(query: SiteQuery): Promise<Paged<SiteRow>> {
  await delay(280);
  const windowSize = 300;
  const startWindow = Math.floor(((query.page - 1) * query.pageSize) / windowSize) * windowSize;
  let rows = buildSiteRows(startWindow, windowSize);
  if (query.search.trim()) {
    const needle = query.search.trim().toLowerCase();
    rows = rows.filter(
      (row) => row.name.toLowerCase().includes(needle) || row.city.toLowerCase().includes(needle)
    );
  }
  if (query.health !== 'all') rows = rows.filter((row) => row.health === query.health);
  if (query.region !== 'all') rows = rows.filter((row) => row.region === query.region);
  const filtered = Boolean(query.search.trim() || query.health !== 'all' || query.region !== 'all');
  const total = filtered ? Math.round((rows.length / windowSize) * TOTAL_SITES) : TOTAL_SITES;
  const offset =
    ((query.page - 1) * query.pageSize) % Math.max(1, Math.min(windowSize, rows.length));
  return { rows: rows.slice(offset, offset + query.pageSize), total, isExampleData: true };
}

export async function listSiteDevices(siteId: string | number): Promise<DeviceRow[]> {
  await delay(260);
  return buildSiteDevices(mockSiteIndex(siteId));
}

export async function listDiscovered(query?: { page?: number; pageSize?: number; q?: string }) {
  await delay(300);
  const rows = listUnapproved();
  if (!query) return rows;
  const needle = (query.q || '').trim().toLowerCase();
  const filtered = needle
    ? rows.filter((device) =>
        [device.sysName, device.hostname, device.ip, device.vendor, device.model, device.suggested.role, device.suggested.site]
          .filter(Boolean)
          .join(' ')
          .toLowerCase()
          .includes(needle)
      )
    : rows;
  const size = query.pageSize || 25;
  const page = query.page || 1;
  const start = (page - 1) * size;
  return { rows: filtered.slice(start, start + size), total: filtered.length, page, pageSize: size };
}

export async function setDeviceRoles(ids: string[], role: string) {
  await delay(40);
  return setRoles(ids, role);
}

export async function setDeviceSites(ids: string[], site: string) {
  await delay(40);
  return setSites(ids, site);
}

export async function netbridgeGet(path: string) {
  await delay(40);
  if (path.startsWith('/open-count')) return { open: 2, iseConfigured: false, infobloxConfigured: false };
  if (path.startsWith('/summary')) {
    return {
      netdiscoDevices: 12,
      netboxDevices: 9,
      notInNetbox: 3,
      stacksPending: 1,
      apsPending: 4,
      openConflicts: 2,
      netdisco: { ok: true, message: '' },
      eox: { configured: true, message: '' },
      fortimanager: { configured: false, message: 'FortiManager URL and token are not configured. Add them in Settings → Vault.' },
      ise: { configured: false, message: 'ISE URL, username, and password are not configured. Add them in Settings → Vault.' },
      jobs: [{ id: 1, kind: 'ap-scan', actor: 'admin@example.com', status: 'done', counts: { aps: 4 }, errors: [], startedAt: '2026-11-01T00:00:00Z', finishedAt: '2026-11-01T00:01:00Z', detail: '' }],
    };
  }
  if (path.startsWith('/eox')) {
    return {
      configured: true,
      message: '',
      total: 1,
      page: 1,
      pageSize: 25,
      counts: { past: 1, soon: 0, ok: 0, unknown: 0 },
      rows: [{ id: 1, name: 'sw-old', pid: 'WS-C2960-24TC-L', serial: 'FOC1234', bucket: 'past', end_of_sale: '2018-10-31', end_of_sw_maintenance: '2019-10-31', end_of_security: '2020-10-31', last_date_of_support: '2023-10-31', migration_pid: 'C9200-24P', message: '', source: 'netbox' }],
    };
  }
  if (path.startsWith('/conflicts')) {
    return { total: 1, page: 1, pageSize: 25, rows: [{ id: 7, kind: 'serial', left: 'FOC1', right: 'FOC2', status: 'open', detail: {}, updatedAt: '2026-11-01T00:00:00Z' }] };
  }
  if (path.startsWith('/history')) {
    return { total: 1, page: 1, pageSize: 25, rows: [{ id: 1, kind: 'stacks-preview', actor: 'admin@example.com', status: 'dry-run', counts: { changes: 2 }, errors: [], startedAt: '2026-11-01T00:00:00Z', finishedAt: '2026-11-01T00:00:00Z', detail: '' }] };
  }
  if (path.startsWith('/access-points')) {
    return { total: 1, page: 1, pageSize: 25, models: [{ model: 'CW9164', count: 1 }], rows: [{ id: 3, name: 'ap-1', model: 'CW9164', serial: 'FGL1', ip: '10.1.1.5', wlc: 'wlc1', neighbor: 'sw1', neighborPort: 'Gi1/0/1', action: 'create', inNetbox: false }] };
  }
  if (path.startsWith('/fortimanager')) {
    return { configured: false, message: 'FortiManager URL and token are not configured. Add them in Settings → Vault.', instances: [], rows: [], total: 0, page: 1, pageSize: 25 };
  }
  if (path.startsWith('/infoblox/members/')) {
    return {
      configured: false,
      ok: false,
      message: 'Infoblox URL, username, and password are not configured. Add them in Settings → Vault.',
      grid: '',
      version: '',
      member: null,
    };
  }
  if (path.startsWith('/infoblox/health')) {
    return {
      configured: false,
      ok: false,
      message: 'Infoblox URL, username, and password are not configured. Add them in Settings → Vault.',
      grid: '',
      version: '',
      members: [],
    };
  }
  if (path.startsWith('/ise/operations')) {
    return {
      configured: false,
      ok: false,
      message: 'ISE URL, username, and password are not configured. Add them in Settings → Vault.',
      version: '',
      sessions: { active: null, windowMinutes: 30, recent: null, rows: [], message: '' },
      inventory: [],
      directories: [],
      dependencies: [],
      alarms: { available: false, message: '', rows: [] },
    };
  }
  if (path.startsWith('/ise/nodes/')) {
    return {
      configured: false,
      ok: false,
      message: 'ISE URL, username, and password are not configured. Add them in Settings → Vault.',
      version: '',
      node: null,
    };
  }
  if (path.startsWith('/ise/health')) {
    return {
      configured: false,
      ok: false,
      message: 'ISE URL, username, and password are not configured. Add them in Settings → Vault.',
      version: '',
      activeSessions: null,
      nodes: [],
    };
  }
  if (path.startsWith('/ise')) {
    return {
      configured: false,
      ok: false,
      message: 'ISE URL, username, and password are not configured. Add them in Settings → Vault.',
      version: '',
      activeSessions: null,
      rows: [],
      total: 0,
      page: 1,
      pageSize: 25,
    };
  }
  return { rows: [], total: 0, page: 1, pageSize: 25, message: '' };
}

export async function netbridgePost(path: string, body?: unknown) {
  await delay(40);
  if (path.endsWith('/preview')) {
    return { previewId: 41, dryRun: true, changes: 1, rows: [{ name: 'example', action: 'create' }], message: 'Nothing is written until you confirm this preview.' };
  }
  if (path.endsWith('/apply')) {
    const confirm = body && typeof body === 'object' && (body as { confirm?: boolean }).confirm === true;
    if (!confirm) throw new (await import('@/lib/apiError')).ApiError(400, 'bad_body', 'confirm must be true');
    return { ok: true, previewId: 41, counts: { created: 1, updated: 0, skipped: 0, errors: 0 }, errors: [] };
  }
  if (path.endsWith('/refresh')) return { ok: true, configured: true, message: 'Refreshed 1 Cisco device.', updated: 1 };
  return { ok: true, message: 'Done.' };
}

const MOCK_ROLES = [
  'Access switch',
  'Core switch',
  'Firewall',
  'Router',
  'Access point',
  'Wireless controller',
  'Server',
  'Unknown',
];
const MOCK_SITES = [
  'Rotterdam-Havenstraat-214',
  'Utrecht-Centrum-482',
  'Eindhoven-Strijp-731',
  'Amsterdam-Zuidas-105',
  'Leiden-Bio-566',
  'Groningen-Noord-317',
  'Zwolle-Station-209',
  'Breda-Chasse-640',
  'Arnhem-Rijn-853',
];
const MOCK_PLATFORMS = ['ios-xe', 'ios', 'nxos', 'junos', 'fortios', 'aoscx'];

export async function discoveryCatalog() {
  await delay(120);
  return { ok: true, roles: MOCK_ROLES, sites: MOCK_SITES, platforms: MOCK_PLATFORMS };
}

export async function listAlerts(): Promise<AlertItem[]> {
  await delay(300);
  return buildAlerts();
}

export async function acknowledgeAlerts(ids: string[]): Promise<{ ids: string[]; ok: boolean }> {
  await delay(380);
  return { ids, ok: true };
}

export async function approveDevice(
  id: string,
  body: ApproveBody
): Promise<{ id: string; ok: boolean }> {
  await delay(420);
  return approveUnapproved(id, body);
}

export async function approveAccessPoints(body: { accessPoints: { name: string; serial?: string }[] }) {
  await delay(200);
  return {
    ok: true,
    results: body.accessPoints.map((ap) => ({
      name: ap.name,
      wlc: '',
      status: ap.serial === 'FGL000114' ? 'skipped' : 'created',
      reason: ap.serial === 'FGL000114' ? 'Already in NetBox' : '',
      deviceId: ap.serial === 'FGL000114' ? '9' : '42',
    })),
  };
}

export async function rejectDevice(id: string): Promise<{ id: string; ok: boolean }> {
  await delay(350);
  return rejectUnapproved(id);
}

export async function getSetupState() {
  await delay(80);
  return readMockSetupState();
}

export async function login(email: string, password: string): Promise<LoginResult> {
  await delay(400);
  return mockLogin(email, password);
}

export async function logout(): Promise<{ ok: boolean }> {
  await delay(40);
  return { ok: true };
}

export async function me(): Promise<Session> {
  await delay(40);
  const existing = readSession();
  if (existing) return existing;
  return {
    email: 'm.vanderberg@noc.example',
    role: 'Administrator',
    csrfToken: 'mock-csrf-Administrator',
  };
}

export async function listApps() {
  await delay(30);
  return listSettingsApps();
}

export async function getOverview() {
  await delay(30);
  return settingsOverview();
}

export async function getAudit(query: AuditQuery = {}) {
  await delay(30);
  return settingsAudit(query);
}

export async function getFile(appId: string, fileId: string) {
  await delay(30);
  return readSettingsFile(appId, fileId);
}

export async function validateFile(appId: string, fileId: string, content: string) {
  await delay(40);
  return validateSettingsFile(appId, fileId, content);
}

export async function diffFile(appId: string, fileId: string, content: string) {
  await delay(40);
  return diffSettingsFile(appId, fileId, content);
}

export async function saveFile(appId: string, fileId: string, body: SaveFileBody) {
  await delay(50);
  return saveSettingsFile(appId, fileId, body);
}

export async function fileHistory(appId: string, fileId: string) {
  await delay(30);
  return historyEntries(appId, fileId);
}

export async function historyContent(appId: string, fileId: string, historyId: string) {
  await delay(30);
  return historyDocument(appId, fileId, historyId);
}

export async function restoreHistory(
  appId: string,
  fileId: string,
  historyId: string,
  body: { apply: boolean }
) {
  await delay(50);
  return restoreVersion(appId, fileId, historyId, body.apply);
}

export async function runAction(appId: string, actionId: string) {
  await delay(80);
  return runAppAction(appId, actionId);
}

export async function listMibs() {
  await delay(20);
  return mibList();
}

export async function uploadMib(file: File) {
  await delay(40);
  return addMib(file.name, file.size);
}

export async function deleteMib(name: string) {
  await delay(30);
  return removeMib(name);
}

export async function listScans() {
  await delay(20);
  return scanList();
}

export async function startScan(target: 'prefix' | 'ip', value: string) {
  await delay(60);
  return beginScan(target, value);
}

export async function discoverDevice(ip: string, neighbours = false) {
  await delay(40);
  return beginDeviceDiscover(ip, neighbours);
}

export async function getDeviceDiscovery(id: string) {
  await delay(20);
  return readDeviceDiscovery(id);
}

export async function listLauncherApps() {
  await delay(20);
  return {
    host: 'monitor.example.com',
    role: 'Administrator',
    apps: [
      { id: 'netbox', name: 'NetBox', url: 'https://monitor.example.com:8092/', status: 'up' as const },
      { id: 'grafana', name: 'Grafana', url: 'https://monitor.example.com:3000/', status: 'up' as const },
      { id: 'alertmanager', name: 'Alertmanager', url: 'https://monitor.example.com:8086/', status: 'up' as const },
    ],
  };
}

export async function getDeviceCli() {
  await delay(20);
  return {
    platform: 'ios',
    platformLabel: 'Cisco IOS',
    commands: [],
    credentialsConfigured: false,
    hostname: '',
    mgmtIp: '',
    message: 'CLI credentials are not set for this device.',
  };
}

export async function runDeviceCli(_deviceId: string, command: string) {
  await delay(20);
  return { command, output: '', platform: 'ios' };
}

export async function saveDeviceCliCredentials() {
  await delay(20);
  return { ok: true, configured: true };
}

export async function getExperience() {
  await delay(40);
  return {
    isExampleData: true,
    degraded: [],
    wlc: {
      configured: true,
      reason: '',
      note: 'Example only.',
      controllers: [{ name: 'wlc-9800', site: 'Rotterdam', platform: 'ios-xe', transport: 'mdt' }],
      radios: [{ ap: 'ap-rot-1', radio: '0', rssi_avg: '-64', clients: '12' }],
    },
    sdwan: {
      configured: false,
      reason: 'not configured. No Cisco SD-WAN cEdge is in NetBox.',
      routers: [],
      tunnels: [],
    },
    vbs: {
      configured: false,
      reason: 'not configured. No site has vbs_server_ip.',
      sites: [],
      sla: [],
    },
    thirdParties: {
      configured: false,
      reason: 'not configured. No NetBox service is tagged third-party or bank.',
      targets: [],
      probes: [],
    },
  };
}

export async function getIpSlaConfig() {
  await delay(20);
  return {
    configured: false,
    pushed: false,
    title: 'IP SLA config',
    filename: 'ip-sla.txt',
    config: '',
    reason: 'not configured. Site has no vbs_server_ip.',
  };
}

export async function getTelemetryConfig() {
  await delay(20);
  return {
    configured: true,
    pushed: false,
    title: 'Controller config',
    filename: 'telemetry-subscription.txt',
    receiverConfigured: false,
    reason: '',
    config: '! Example telemetry subscription. Nothing is pushed.\ntelemetry ietf subscription 60000\n',
  };
}

type MockDirectoryUser = {
  id: number;
  username: string;
  displayName: string;
  email: string;
  role: 'Administrator' | 'Engineer' | 'Operator' | 'Read-only';
  status: 'active' | 'disabled';
  lastLogin: string | null;
  created: string | null;
  builtin: boolean;
  mustChangePassword: boolean;
};

const mockUsers: MockDirectoryUser[] = [
  { id: 1, username: 'admin', displayName: 'Marit van der Berg', email: 'm.vanderberg@noc.example', role: 'Administrator', status: 'active', lastLogin: '2026-11-03T14:20:00Z', created: '2026-01-15T09:00:00Z', builtin: true, mustChangePassword: false },
  { id: 2, username: 'sander', displayName: 'Sander Kuipers', email: 's.kuipers@noc.example', role: 'Engineer', status: 'active', lastLogin: '2026-11-03T13:40:00Z', created: '2026-02-02T09:00:00Z', builtin: false, mustChangePassword: false },
  { id: 3, username: 'dewi', displayName: 'Dewi Pranata', email: 'd.pranata@noc.example', role: 'Operator', status: 'active', lastLogin: '2026-11-03T12:10:00Z', created: '2026-03-11T09:00:00Z', builtin: false, mustChangePassword: false },
  { id: 4, username: 'fenna', displayName: 'Fenna Smit', email: 'f.smit@customer.example', role: 'Read-only', status: 'active', lastLogin: '2026-11-02T16:00:00Z', created: '2026-04-01T09:00:00Z', builtin: false, mustChangePassword: false },
];

const mockUserAudit: { id: number; at: string | null; actor: string; role: string; action: string; detail: string; result: string }[] = [
  { id: 1, at: '2026-01-15T09:00:00Z', actor: 'm.vanderberg@noc.example', role: 'Administrator', action: 'admin-created', detail: 'first administrator created', result: 'ok' },
];

function storedRole(role: string): MockDirectoryUser['role'] {
  if (role === 'Admin' || role === 'Administrator') return 'Administrator';
  if (role === 'Viewer' || role === 'Read-only') return 'Read-only';
  if (role === 'Engineer' || role === 'Operator') return role;
  throw new ApiError(400, 'bad_role', 'role must be one of: Admin, Operator, Viewer, Engineer');
}

function activeAdmins(exceptId?: number) {
  return mockUsers.filter((user) => user.id !== exceptId && user.status === 'active' && user.role === 'Administrator').length;
}

function audit(action: string, detail: string) {
  mockUserAudit.unshift({
    id: mockUserAudit.length + 1,
    at: new Date().toISOString(),
    actor: readSession()?.email || 'm.vanderberg@noc.example',
    role: readSession()?.role || 'Administrator',
    action,
    detail,
    result: 'ok',
  });
}

export async function listDirectoryUsers() {
  await delay(20);
  return mockUsers.map((user) => ({ ...user }));
}

export async function listUserAudit() {
  await delay(20);
  return { entries: mockUserAudit.map((row) => ({ ...row })) };
}

export async function createDirectoryUser(body: {
  username: string;
  displayName: string;
  email: string;
  role: string;
  password?: string;
  generate?: boolean;
  forceChange?: boolean;
}) {
  await delay(30);
  const username = body.username.trim().toLowerCase();
  if (username === 'admin' || mockUsers.some((user) => user.username === username || user.email === body.email.toLowerCase())) {
    throw new ApiError(409, 'exists', 'a user with that username or email already exists');
  }
  const password = body.generate ? 'Temp' + Math.random().toString(36).slice(2, 10) + '1a' : body.password || '';
  if (!body.generate && (password.length < 12 || !/[A-Za-z]/.test(password) || !/\d/.test(password))) {
    throw new ApiError(400, 'bad_password', 'password must be 12-200 characters and include a letter and a digit');
  }
  const user: MockDirectoryUser = {
    id: Math.max(...mockUsers.map((row) => row.id)) + 1,
    username,
    displayName: body.displayName.trim(),
    email: body.email.trim().toLowerCase(),
    role: storedRole(body.role),
    status: 'active',
    lastLogin: null,
    created: new Date().toISOString(),
    builtin: false,
    mustChangePassword: body.generate === true || body.forceChange === true,
  };
  mockUsers.push(user);
  audit('user-create', user.email + ' ' + user.role);
  return { ...user, ok: true as const, ...(body.generate ? { oneTimePassword: password } : {}) };
}

export async function updateDirectoryUser(id: number, body: { displayName?: string; email?: string; role?: string }) {
  await delay(20);
  const user = mockUsers.find((row) => row.id === id);
  if (!user) throw new ApiError(404, 'no_user', 'no user with that id');
  if (body.role && storedRole(body.role) !== user.role) {
    const next = storedRole(body.role);
    if ((user.builtin || user.username === 'admin') && next !== 'Administrator') {
      throw new ApiError(409, 'protected_admin', 'the built-in admin account cannot be deleted, disabled, or demoted');
    }
    if (user.role === 'Administrator' && next !== 'Administrator' && activeAdmins(user.id) < 1) {
      throw new ApiError(409, 'last_admin', 'the last administrator cannot be removed, disabled, or demoted');
    }
    user.role = next;
  }
  if (body.displayName) user.displayName = body.displayName.trim();
  if (body.email) user.email = body.email.trim().toLowerCase();
  audit('user-update', user.username);
  return { ...user };
}

export async function setDirectoryUserStatus(id: number, status: 'active' | 'disabled') {
  await delay(20);
  const user = mockUsers.find((row) => row.id === id);
  if (!user) throw new ApiError(404, 'no_user', 'no user with that id');
  if (status === 'disabled' && (user.builtin || user.username === 'admin')) {
    throw new ApiError(409, 'protected_admin', 'the built-in admin account cannot be deleted, disabled, or demoted');
  }
  if (status === 'disabled' && user.role === 'Administrator' && activeAdmins(user.id) < 1) {
    throw new ApiError(409, 'last_admin', 'the last administrator cannot be removed, disabled, or demoted');
  }
  user.status = status;
  audit(status === 'disabled' ? 'user-disable' : 'user-enable', user.username);
  return { ...user };
}

export async function resetDirectoryPassword(id: number, body: { password?: string; generate?: boolean }) {
  await delay(20);
  const user = mockUsers.find((row) => row.id === id);
  if (!user) throw new ApiError(404, 'no_user', 'no user with that id');
  const password = body.generate ? 'Reset' + Math.random().toString(36).slice(2, 10) + '9z' : body.password || '';
  if (!body.generate && (password.length < 12 || !/[A-Za-z]/.test(password) || !/\d/.test(password))) {
    throw new ApiError(400, 'bad_password', 'password must be 12-200 characters and include a letter and a digit');
  }
  user.mustChangePassword = true;
  audit('user-password-reset', user.username + ' sessions cleared');
  return { ok: true as const, username: user.username, mustChangePassword: true, ...(body.generate ? { oneTimePassword: password } : {}) };
}

export async function deleteDirectoryUser(id: number) {
  await delay(20);
  const index = mockUsers.findIndex((row) => row.id === id);
  if (index < 0) throw new ApiError(404, 'no_user', 'no user with that id');
  const user = mockUsers[index];
  if (readSession()?.email === user.email) throw new ApiError(403, 'self_delete', 'you cannot delete your own account');
  if (user.builtin || user.username === 'admin') {
    throw new ApiError(409, 'protected_admin', 'the built-in admin account cannot be deleted, disabled, or demoted');
  }
  if (user.role === 'Administrator' && activeAdmins(user.id) < 1) {
    throw new ApiError(409, 'last_admin', 'the last administrator cannot be removed, disabled, or demoted');
  }
  mockUsers.splice(index, 1);
  audit('user-delete', user.username + ' ' + user.email);
  return { ok: true as const };
}

export async function changePassword() {
  await delay(20);
  return { ok: true as const };
}
