import type { RoleName } from '@/lib/types';

export type AppGroup =
  'metrics' | 'alerting' | 'snmp' | 'network' | 'automation' | 'platform' | 'data';

export type ContainerState = 'running' | 'exited' | 'unhealthy' | 'missing';

export type FileLanguage = 'yaml' | 'json' | 'toml' | 'caddyfile' | 'python' | 'ini' | 'text';

export type ActionKind = 'reload' | 'restart' | 'generate' | 'validate' | 'link';

export interface ContainerStatus {
  name: string;
  state: ContainerState;
  health?: string;
  uptimeSeconds?: number;
}

export interface SettingsFileMeta {
  id: string;
  path: string;
  label: string;
  language: FileLanguage;
  sizeBytes: number;
  editable: boolean;
  readOnlyReason?: string;
  hasSecrets: boolean;
}

export interface SettingsAction {
  id: string;
  label: string;
  kind: ActionKind;
  dangerous: boolean;
  roles: RoleName[];
}

export interface SettingsApp {
  id: string;
  name: string;
  description: string;
  group: AppGroup;
  container: ContainerStatus;
  version?: string;
  uiUrl?: string;
  files: SettingsFileMeta[];
  actions: SettingsAction[];
}

/** GET /api/v1/settings/overview — shape agreed for the landing page. */
export interface OverviewApp {
  id: string;
  container: ContainerStatus;
  lastReloadAt?: string | null;
  lastError?: string | null;
}

export interface OverviewResponse {
  generatedAt: string;
  apps: OverviewApp[];
}

export interface FileDocument {
  content: string;
  etag: string;
  modifiedAt: string;
  language: FileLanguage;
  maskedKeys: string[];
}

export interface ValidateMessage {
  severity: 'error' | 'warning' | 'info';
  line?: number;
  column?: number;
  text: string;
}

export interface ValidateResult {
  ok: boolean;
  messages: ValidateMessage[];
  tool: string;
  durationMs: number;
}

export interface DiffResult {
  unified: string;
  added: number;
  removed: number;
}

export interface SaveFileBody {
  content: string;
  etag: string;
  comment: string;
  apply: boolean;
}

export interface SaveResult {
  etag: string;
  applied: boolean;
  applyResult?: { ok: boolean; message: string };
}

export interface HistoryEntry {
  id: string;
  savedAt: string;
  user: string;
  comment: string;
  sizeBytes: number;
}

export interface HistoryDocument {
  id: string;
  content: string;
  savedAt: string;
  user: string;
  comment: string;
}

export interface ActionResult {
  ok: boolean;
  message: string;
  output?: string;
}

export interface MibFile {
  name: string;
  sizeBytes: number;
  uploadedAt: string;
}

export interface AuditEntry {
  id: string;
  at: string;
  user: string;
  app: string;
  file?: string;
  action: string;
  comment?: string;
  result: string;
  sourceIp: string;
}

export interface AuditQuery {
  app?: string;
  user?: string;
  from?: string;
  to?: string;
  page?: number;
}

export interface AuditPage {
  page: number;
  entries: AuditEntry[];
}

export type SetupStateName = 'unconfigured' | 'applying' | 'complete' | 'failed';

export interface SetupState {
  state: SetupStateName;
  step?: string;
}

export interface LoginResult {
  ok: boolean;
  role?: RoleName;
  email?: string;
  csrfToken?: string;
  error?: string;
}

export interface DiscoverySuggestion {
  role?: string;
  site?: string;
  platform?: string;
}

export interface UnapprovedDevice {
  id: string;
  ip: string;
  hostname?: string;
  sysName?: string;
  vendor?: string;
  model?: string;
  platform?: string;
  sysDescr?: string;
  firstSeen: string;
  lastSeen: string;
  suggested: DiscoverySuggestion;
}

export interface ApproveBody {
  role: string;
  site: string;
  name?: string;
  platform?: string;
}

export type ScanTarget = 'prefix' | 'ip';
export type ScanStatus = 'queued' | 'running' | 'finished' | 'failed';

export interface DiscoveryScan {
  id: string;
  target: ScanTarget;
  value: string;
  status: ScanStatus;
  startedAt: string;
  finishedAt?: string;
  message?: string;
}

export const GROUP_ORDER: AppGroup[] = [
  'metrics',
  'alerting',
  'snmp',
  'network',
  'automation',
  'platform',
  'data',
];

export const GROUP_LABEL: Record<AppGroup, string> = {
  metrics: 'Metrics',
  alerting: 'Alerting',
  snmp: 'SNMP',
  network: 'Network',
  automation: 'Automation',
  platform: 'Platform',
  data: 'Data',
};

/** States the mock can return. The running demo defaults to complete. */
export const MOCK_SETUP_STATES: SetupState[] = [
  { state: 'unconfigured', step: 'admin' },
  { state: 'applying', step: 'compose' },
  { state: 'complete' },
  { state: 'failed', step: 'database' },
];
