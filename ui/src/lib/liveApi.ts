import type { AlertItem, DeviceDetailData, DeviceRow, SeriesPoint, SiteRow } from '@/lib/types';
import type { DeviceQuery, Paged, SiteQuery } from '@/lib/apiClient';
import type { RangeKey } from '@/lib/mockData';
import { ApiError } from '@/lib/apiError';
import type {
  ActionResult,
  ApproveBody,
  AuditPage,
  AuditQuery,
  DiffResult,
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
import { request } from '@/lib/http';
import type { Session } from '@/lib/session';

const API = '/api/v1';

function withExample<T>(data: Paged<T>): Paged<T> {
  return { ...data, isExampleData: Boolean(data.isExampleData) };
}

export async function getSummary() {
  const data = await request<Record<string, unknown> & { isExampleData?: boolean }>(
    `${API}/summary`
  );
  return { ...data, isExampleData: Boolean(data.isExampleData) };
}

export async function listDevices(query: DeviceQuery): Promise<Paged<DeviceRow>> {
  const params = new URLSearchParams({
    page: String(query.page),
    page_size: String(query.pageSize),
    q: query.search,
    health: query.health,
    role: query.role,
    sort: `${String(query.sortKey)}:${query.sortDir}`,
  });
  return withExample(await request<Paged<DeviceRow>>(`${API}/devices?${params}`));
}

export async function getDevice(form: string): Promise<DeviceDetailData> {
  return request(`${API}/devices/${encodeURIComponent(form)}`);
}

export async function getThroughput(
  range: RangeKey,
  seed: number,
  customMin?: number
): Promise<SeriesPoint[]> {
  const params = new URLSearchParams({ range, seed: String(seed) });
  if (customMin !== undefined) params.set('custom_min', String(customMin));
  return request(`${API}/devices/${seed}/metrics/throughput?${params}`);
}

export async function getResources(range: RangeKey, seed: number) {
  return request(`${API}/devices/${seed}/metrics/resources?range=${encodeURIComponent(range)}`);
}

export async function getTopPorts(seed: number) {
  return request(`${API}/devices/${seed}/ports/top?metric=util`);
}

export async function getPortSeries(
  portId: string,
  range: RangeKey,
  customMin?: number
): Promise<SeriesPoint[]> {
  const params = new URLSearchParams({ range });
  if (customMin !== undefined) params.set('custom_min', String(customMin));
  return request(`${API}/devices/ports/${encodeURIComponent(portId)}/metrics?${params}`);
}

export async function listSites(query: SiteQuery): Promise<Paged<SiteRow>> {
  const params = new URLSearchParams({
    page: String(query.page),
    page_size: String(query.pageSize),
    q: query.search,
    health: query.health,
    region: query.region,
  });
  return withExample(await request<Paged<SiteRow>>(`${API}/sites?${params}`));
}

export async function listSiteDevices(siteIndex: number): Promise<DeviceRow[]> {
  return request(`${API}/sites/${siteIndex}/devices`);
}

export async function listDiscovered(): Promise<UnapprovedDevice[]> {
  return request(`${API}/discovery/unapproved`);
}

export async function listAlerts(): Promise<AlertItem[]> {
  return request(`${API}/alerts`);
}

export async function acknowledgeAlerts(ids: string[]): Promise<{ ids: string[]; ok: boolean }> {
  return request(`${API}/alerts/acknowledge`, { method: 'POST', body: { ids } });
}

export async function approveDevice(
  id: string,
  body: ApproveBody
): Promise<{ id: string; ok: boolean }> {
  return request(`${API}/discovery/${encodeURIComponent(id)}/approve`, { method: 'POST', body });
}

export async function rejectDevice(id: string): Promise<{ id: string; ok: boolean }> {
  return request(`${API}/discovery/${encodeURIComponent(id)}/reject`, { method: 'POST', body: {} });
}

export async function getSetupState(): Promise<SetupState> {
  return request<SetupState>('/setup/state');
}

export async function login(email: string, password: string): Promise<LoginResult> {
  try {
    const data = await request<{ ok?: boolean; role?: LoginResult['role']; csrfToken?: string }>(
      `${API}/auth/login`,
      {
        method: 'POST',
        body: { email, password },
      }
    );
    if (!data?.role || !data.csrfToken)
      return { ok: false, error: 'Sign-in did not return a session.' };
    return { ok: true, role: data.role, email, csrfToken: data.csrfToken };
  } catch (error) {
    if (error instanceof ApiError) return { ok: false, error: error.message };
    return { ok: false, error: 'Sign-in failed.' };
  }
}

export async function logout(): Promise<{ ok: boolean }> {
  return request(`${API}/auth/logout`, { method: 'POST', body: {} });
}

export async function me(): Promise<Session> {
  return request(`${API}/auth/me`);
}

export async function listApps(): Promise<SettingsApp[]> {
  return request(`${API}/settings/apps`);
}

export async function getOverview(): Promise<OverviewResponse> {
  return request(`${API}/settings/overview`);
}

export async function getAudit(query: AuditQuery = {}): Promise<AuditPage> {
  const params = new URLSearchParams();
  if (query.app) params.set('app', query.app);
  if (query.user) params.set('user', query.user);
  if (query.from) params.set('from', query.from);
  if (query.to) params.set('to', query.to);
  if (query.page) params.set('page', String(query.page));
  const suffix = params.toString();
  return request(`${API}/settings/audit${suffix ? `?${suffix}` : ''}`);
}

export async function getFile(appId: string, fileId: string): Promise<FileDocument> {
  return request(
    `${API}/settings/apps/${encodeURIComponent(appId)}/files/${encodeURIComponent(fileId)}`
  );
}

export async function validateFile(
  appId: string,
  fileId: string,
  content: string
): Promise<ValidateResult> {
  return request(
    `${API}/settings/apps/${encodeURIComponent(appId)}/files/${encodeURIComponent(fileId)}/validate`,
    {
      method: 'POST',
      body: { content },
    }
  );
}

export async function diffFile(
  appId: string,
  fileId: string,
  content: string
): Promise<DiffResult> {
  return request(
    `${API}/settings/apps/${encodeURIComponent(appId)}/files/${encodeURIComponent(fileId)}/diff`,
    {
      method: 'POST',
      body: { content },
    }
  );
}

export async function saveFile(
  appId: string,
  fileId: string,
  body: SaveFileBody
): Promise<SaveResult> {
  return request(
    `${API}/settings/apps/${encodeURIComponent(appId)}/files/${encodeURIComponent(fileId)}`,
    {
      method: 'PUT',
      body,
    }
  );
}

export async function fileHistory(appId: string, fileId: string): Promise<HistoryEntry[]> {
  return request(
    `${API}/settings/apps/${encodeURIComponent(appId)}/files/${encodeURIComponent(fileId)}/history`
  );
}

export async function historyContent(
  appId: string,
  fileId: string,
  historyId: string
): Promise<HistoryDocument> {
  const data = await request<unknown>(
    `${API}/settings/apps/${encodeURIComponent(appId)}/files/${encodeURIComponent(fileId)}/history/${encodeURIComponent(historyId)}`
  );
  if (typeof data === 'string')
    return { id: historyId, content: data, savedAt: '', user: '', comment: '' };
  if (
    data &&
    typeof data === 'object' &&
    'content' in data &&
    typeof (data as HistoryDocument).content === 'string'
  ) {
    return data as HistoryDocument;
  }
  throw new ApiError(500, 'bad_response', 'History entry did not include content.');
}

export async function restoreHistory(
  appId: string,
  fileId: string,
  historyId: string,
  body: { apply: boolean }
): Promise<SaveResult> {
  return request(
    `${API}/settings/apps/${encodeURIComponent(appId)}/files/${encodeURIComponent(fileId)}/history/${encodeURIComponent(historyId)}/restore`,
    { method: 'POST', body }
  );
}

export async function runAction(
  appId: string,
  actionId: string,
  params?: Record<string, unknown>
): Promise<ActionResult> {
  return request(
    `${API}/settings/apps/${encodeURIComponent(appId)}/actions/${encodeURIComponent(actionId)}`,
    {
      method: 'POST',
      body: params ? { params } : {},
    }
  );
}

export async function listMibs(): Promise<MibFile[]> {
  return request(`${API}/settings/apps/snmp-generator/mibs`);
}

export async function uploadMib(file: File): Promise<MibFile> {
  const form = new FormData();
  form.append('file', file, file.name);
  return request(`${API}/settings/apps/snmp-generator/mibs`, { method: 'POST', form });
}

export async function deleteMib(name: string): Promise<{ ok: boolean }> {
  return request(`${API}/settings/apps/snmp-generator/mibs/${encodeURIComponent(name)}`, {
    method: 'DELETE',
  });
}

export async function listScans(): Promise<DiscoveryScan[]> {
  return request(`${API}/discovery/scans`);
}

export async function startScan(target: 'prefix' | 'ip', value: string): Promise<DiscoveryScan> {
  return request(`${API}/discovery/scan`, { method: 'POST', body: { target, value } });
}
