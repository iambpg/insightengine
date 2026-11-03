// Single API client. Live mode calls same-origin /api/v1 (and /setup/state).
// Mock mode keeps the demo data so the UI runs without ie-config.
import type {
  AlertItem,
  DeviceDetailData,
  DeviceHealth,
  DeviceRow,
  SeriesPoint,
  SiteRow,
} from '@/lib/types';
import type { RangeKey } from '@/lib/mockData';
import type {
  ActionResult,
  AccessPointApproveBody,
  AccessPointApproveResult,
  ApproveBody,
  AuditPage,
  AuditQuery,
  DiffResult,
  DiscoveryCatalog,
  DeviceDiscoveryJob,
  DiscoveryScan,
  FileDocument,
  HistoryDocument,
  HistoryEntry,
  LoginResult,
  MibFile,
  OverviewResponse,
  SaveFileBody,
  SaveResult,
  SettingsApp,
  SetupState,
  UnapprovedDevice,
  ValidateResult,
} from '@/lib/contract';
import { writeSession } from '@/lib/session';
import type { Session } from '@/lib/session';
import * as live from '@/lib/liveApi';

export interface DeviceQuery {
  page: number;
  pageSize: number;
  search: string;
  health: DeviceHealth | 'all';
  role: string;
  sortKey: keyof DeviceRow;
  sortDir: 'asc' | 'desc';
}

export interface SiteQuery {
  page: number;
  pageSize: number;
  search: string;
  health: DeviceHealth | 'all';
  region: string;
}

export interface Paged<T> {
  rows: T[];
  total: number;
  isExampleData: boolean;
  roles?: string[];
  regions?: string[];
  degraded?: string[];
}

type Backend = typeof live;

async function backend(): Promise<Backend> {
  if (
    process.env.NEXT_PUBLIC_IE_API_MODE === 'mock' ||
    (process.env.NEXT_PUBLIC_IE_API_MODE !== 'live' && process.env.NODE_ENV !== 'production')
  ) {
    return import('@/lib/mock/mockBackend');
  }
  return live;
}

export const api = {
  // BACKEND: GET /api/v1/summary
  async getSummary() {
    return (await backend()).getSummary();
  },

  // BACKEND: GET /api/v1/devices?page=&page_size=&q=&health=&role=&sort=
  async listDevices(query: DeviceQuery): Promise<Paged<DeviceRow>> {
    return (await backend()).listDevices(query);
  },

  // BACKEND: GET /api/v1/devices/{id}
  async getDevice(form: string): Promise<DeviceDetailData> {
    return (await backend()).getDevice(form);
  },

  // BACKEND: GET /api/v1/access-points?wlc=&page=&page_size=&q=
  async listAccessPoints(query: { wlc?: string; site?: string; q?: string; status?: string; page?: number; pageSize?: number }) {
    return (await backend()).listAccessPoints(query);
  },

  // BACKEND: GET /api/v1/access-points/detail?wlc=&name=
  async getAccessPointDetail(wlc: string, name: string) {
    return (await backend()).getAccessPointDetail(wlc, name);
  },

  // BACKEND: GET /api/v1/devices/{id}/metrics/throughput?range=
  async getThroughput(range: RangeKey, seed: string | number, customMin?: number): Promise<SeriesPoint[]> {
    return (await backend()).getThroughput(range, seed, customMin);
  },

  // BACKEND: GET /api/v1/devices/{id}/metrics/resources?range=
  async getResources(range: RangeKey, seed: string | number) {
    return (await backend()).getResources(range, seed);
  },

  // BACKEND: GET /api/v1/devices/{id}/ports/top?metric=util
  async getTopPorts(seed: string | number, range?: RangeKey, customMin?: number) {
    return (await backend()).getTopPorts(seed, range, customMin);
  },

  // BACKEND: GET /api/v1/devices/{id}/ports/{portId}/metrics?range=
  async getPortSeries(
    portId: string,
    range: RangeKey,
    customMin?: number,
    deviceId?: string
  ): Promise<SeriesPoint[]> {
    return (await backend()).getPortSeries(portId, range, customMin, deviceId);
  },

  // BACKEND: GET /api/v1/sites?page=&q=&health=&region=
  async listSites(query: SiteQuery): Promise<Paged<SiteRow>> {
    return (await backend()).listSites(query);
  },

  // BACKEND: GET /api/v1/sites/{id}/devices
  async listSiteDevices(siteId: string | number): Promise<DeviceRow[]> {
    return (await backend()).listSiteDevices(siteId);
  },

  // BACKEND: GET /api/v1/discovery/unapproved?page=&page_size=&q=
  async listDiscovered(query?: { page?: number; pageSize?: number; q?: string }) {
    return (await backend()).listDiscovered(query);
  },

  // BACKEND: POST /api/v1/discovery/roles  { ids, role }
  async setDeviceRoles(ids: string[], role: string) {
    return (await backend()).setDeviceRoles(ids, role);
  },

  // BACKEND: GET /api/v1/netbridge/...
  async netbridgeGet(path: string) {
    return (await backend()).netbridgeGet(path);
  },

  // BACKEND: POST /api/v1/netbridge/...
  async netbridgePost(path: string, body?: unknown) {
    return (await backend()).netbridgePost(path, body);
  },

  // BACKEND: GET /api/v1/discovery/catalog
  async discoveryCatalog(): Promise<DiscoveryCatalog> {
    return (await backend()).discoveryCatalog();
  },

  // BACKEND: GET /api/v1/alerts?status=&severity=&site=
  async listAlerts(): Promise<AlertItem[]> {
    return (await backend()).listAlerts();
  },

  // BACKEND: POST /api/v1/alerts/acknowledge  { ids: string[] }
  async acknowledgeAlerts(ids: string[]): Promise<{ ids: string[]; ok: boolean }> {
    return (await backend()).acknowledgeAlerts(ids);
  },

  // BACKEND: POST /api/v1/discovery/{id}/approve
  async approveDevice(id: string, body: ApproveBody): Promise<{ id: string; ok: boolean }> {
    return (await backend()).approveDevice(id, body);
  },

  // BACKEND: POST /api/v1/access-points/approve
  async approveAccessPoints(body: AccessPointApproveBody): Promise<AccessPointApproveResult> {
    return (await backend()).approveAccessPoints(body);
  },

  // BACKEND: POST /api/v1/discovery/{id}/reject
  async rejectDevice(id: string): Promise<{ id: string; ok: boolean }> {
    return (await backend()).rejectDevice(id);
  },

  // BACKEND: GET /setup/state  -> { state, step? }
  async getSetupState(): Promise<SetupState> {
    return (await backend()).getSetupState();
  },

  // BACKEND: POST /api/v1/auth/login
  async login(email: string, password: string): Promise<LoginResult> {
    const result = await (await backend()).login(email, password);
    if (result.ok && result.role && result.csrfToken) {
      writeSession({
        email: result.email ?? email,
        role: result.role,
        csrfToken: result.csrfToken,
        id: result.id,
        username: result.username,
        displayName: result.displayName,
        mustChangePassword: result.mustChangePassword,
      });
    }
    return result;
  },

  // BACKEND: POST /api/v1/auth/logout
  async logout(): Promise<{ ok: boolean }> {
    try {
      return await (await backend()).logout();
    } finally {
      writeSession(null);
    }
  },

  // BACKEND: GET /api/v1/auth/me
  async me(): Promise<Session> {
    const session = await (await backend()).me();
    writeSession(session);
    return session;
  },

  // BACKEND: GET /api/v1/settings/apps
  async listApps(): Promise<SettingsApp[]> {
    return (await backend()).listApps();
  },

  // BACKEND: GET /api/v1/settings/overview
  async getOverview(): Promise<OverviewResponse> {
    return (await backend()).getOverview();
  },

  // BACKEND: GET /api/v1/settings/audit
  async getAudit(query?: AuditQuery): Promise<AuditPage> {
    return (await backend()).getAudit(query);
  },

  // BACKEND: GET /api/v1/settings/apps/{app}/files/{file}
  async getFile(appId: string, fileId: string): Promise<FileDocument> {
    return (await backend()).getFile(appId, fileId);
  },

  // BACKEND: POST /api/v1/settings/apps/{app}/files/{file}/validate
  async validateFile(appId: string, fileId: string, content: string): Promise<ValidateResult> {
    return (await backend()).validateFile(appId, fileId, content);
  },

  // BACKEND: POST /api/v1/settings/apps/{app}/files/{file}/diff
  async diffFile(appId: string, fileId: string, content: string): Promise<DiffResult> {
    return (await backend()).diffFile(appId, fileId, content);
  },

  // BACKEND: PUT /api/v1/settings/apps/{app}/files/{file}
  async saveFile(appId: string, fileId: string, body: SaveFileBody): Promise<SaveResult> {
    return (await backend()).saveFile(appId, fileId, body);
  },

  // BACKEND: GET /api/v1/settings/apps/{app}/files/{file}/history
  async fileHistory(appId: string, fileId: string): Promise<HistoryEntry[]> {
    return (await backend()).fileHistory(appId, fileId);
  },

  // BACKEND: GET /api/v1/settings/apps/{app}/files/{file}/history/{id}
  async historyContent(appId: string, fileId: string, historyId: string): Promise<HistoryDocument> {
    return (await backend()).historyContent(appId, fileId, historyId);
  },

  // BACKEND: POST /api/v1/settings/apps/{app}/files/{file}/history/{id}/restore
  async restoreHistory(
    appId: string,
    fileId: string,
    historyId: string,
    body: { apply: boolean }
  ): Promise<SaveResult> {
    return (await backend()).restoreHistory(appId, fileId, historyId, body);
  },

  // BACKEND: POST /api/v1/settings/apps/{app}/actions/{action}
  async runAction(
    appId: string,
    actionId: string,
    params?: Record<string, unknown>
  ): Promise<ActionResult> {
    return (await backend()).runAction(appId, actionId, params);
  },

  // BACKEND: GET /api/v1/settings/apps/snmp-generator/mibs
  async listMibs(): Promise<MibFile[]> {
    return (await backend()).listMibs();
  },

  // BACKEND: POST /api/v1/settings/apps/snmp-generator/mibs
  async uploadMib(file: File): Promise<MibFile> {
    return (await backend()).uploadMib(file);
  },

  // BACKEND: DELETE /api/v1/settings/apps/snmp-generator/mibs/{name}
  async deleteMib(name: string): Promise<{ ok: boolean }> {
    return (await backend()).deleteMib(name);
  },

  // BACKEND: GET /api/v1/discovery/scans
  async listScans(): Promise<DiscoveryScan[]> {
    return (await backend()).listScans();
  },

  // BACKEND: POST /api/v1/discovery/scan
  async startScan(target: 'prefix' | 'ip', value: string): Promise<DiscoveryScan> {
    return (await backend()).startScan(target, value);
  },

  // BACKEND: POST /api/v1/discovery/device
  async discoverDevice(ip: string, neighbours = false): Promise<DeviceDiscoveryJob> {
    return (await backend()).discoverDevice(ip, neighbours);
  },

  // BACKEND: GET /api/v1/discovery/device/{id}
  async getDeviceDiscovery(id: string): Promise<DeviceDiscoveryJob> {
    return (await backend()).getDeviceDiscovery(id);
  },

  // BACKEND: GET /api/v1/apps/launcher
  async listLauncherApps() {
    return (await backend()).listLauncherApps();
  },

  // BACKEND: GET /api/v1/devices/{id}/cli
  async getDeviceCli(deviceId: string) {
    return (await backend()).getDeviceCli(deviceId);
  },

  // BACKEND: POST /api/v1/devices/{id}/cli
  async runDeviceCli(deviceId: string, command: string) {
    return (await backend()).runDeviceCli(deviceId, command);
  },

  // BACKEND: PUT /api/v1/devices/{id}/cli/credentials
  async saveDeviceCliCredentials(deviceId: string, username: string, password: string) {
    return (await backend()).saveDeviceCliCredentials(deviceId, username, password);
  },

  // BACKEND: GET /api/v1/experience
  async getExperience() {
    return (await backend()).getExperience();
  },

  // BACKEND: GET /api/v1/devices/{id}/ip-sla-config
  async getIpSlaConfig(deviceId: string) {
    return (await backend()).getIpSlaConfig(deviceId);
  },

  // BACKEND: GET /api/v1/devices/{id}/telemetry-config
  async getTelemetryConfig(deviceId: string) {
    return (await backend()).getTelemetryConfig(deviceId);
  },

  // BACKEND: GET /api/v1/auth/users
  async listDirectoryUsers() {
    return (await backend()).listDirectoryUsers();
  },

  // BACKEND: GET /api/v1/auth/users/audit
  async listUserAudit() {
    return (await backend()).listUserAudit();
  },

  async createDirectoryUser(body: {
    username: string;
    displayName: string;
    email: string;
    role: string;
    password?: string;
    generate?: boolean;
    forceChange?: boolean;
  }) {
    return (await backend()).createDirectoryUser(body);
  },

  async updateDirectoryUser(id: number, body: { displayName?: string; email?: string; role?: string }) {
    return (await backend()).updateDirectoryUser(id, body);
  },

  async setDirectoryUserStatus(id: number, status: 'active' | 'disabled') {
    return (await backend()).setDirectoryUserStatus(id, status);
  },

  async resetDirectoryPassword(id: number, body: { password?: string; generate?: boolean }) {
    return (await backend()).resetDirectoryPassword(id, body);
  },

  async deleteDirectoryUser(id: number) {
    return (await backend()).deleteDirectoryUser(id);
  },

  async changePassword(currentPassword: string, newPassword: string) {
    return (await backend()).changePassword(currentPassword, newPassword);
  },
};
