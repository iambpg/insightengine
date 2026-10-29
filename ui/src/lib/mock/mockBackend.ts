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
  listScans as scanList,
  listUnapproved,
  rejectUnapproved,
  resetDiscoveryStore,
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

export async function getDevice(form: string): Promise<DeviceDetailData> {
  await delay(350);
  return buildDeviceDetail(form);
}

export async function getThroughput(
  range: RangeKey,
  seed: string | number,
  customMin?: number
): Promise<SeriesPoint[]> {
  await delay(220);
  return buildSeries(range, asSeed(seed), 1, customMin);
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

export async function listDiscovered() {
  await delay(300);
  return listUnapproved();
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
