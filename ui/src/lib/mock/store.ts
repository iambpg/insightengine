import { ApiError } from '@/lib/apiError';
import type {
  ActionResult,
  AuditEntry,
  AuditQuery,
  DiffResult,
  FileDocument,
  HistoryDocument,
  HistoryEntry,
  MibFile,
  OverviewResponse,
  SaveResult,
  SettingsApp,
  ValidateResult,
} from '@/lib/contract';
import { readSession } from '@/lib/session';
import type { RoleName } from '@/lib/types';
import { unifiedDiff } from '@/lib/settings/diff';
import { validateContent } from '@/lib/settings/validate';
import { STACK_SLUG, buildCatalog, type CatalogApp, type CatalogFile } from '@/lib/mock/catalog';

interface HistoryItem extends HistoryEntry {
  content: string;
}

interface StoredFile {
  meta: CatalogFile;
  content: string;
  etag: string;
  modifiedAt: string;
  history: HistoryItem[];
}

interface StoredApp {
  catalog: CatalogApp;
  lastReloadAt: string | null;
  lastError: string | null;
  state: CatalogApp['state'];
  health?: string;
  uptimeSeconds?: number;
  files: Map<string, StoredFile>;
}

type MibItem = MibFile;

const readers: RoleName[] = ['Administrator', 'Engineer'];

let apps = new Map<string, StoredApp>();
let mibs: MibItem[] = [];
let audit: AuditEntry[] = [];
let candidateReady = false;

export function resetSettingsStore(): void {
  apps = new Map();
  audit = [];
  candidateReady = false;
  mibs = [
    { name: 'IF-MIB', sizeBytes: 184320, uploadedAt: '2026-10-01T09:00:00Z' },
    { name: 'SNMPv2-MIB', sizeBytes: 42110, uploadedAt: '2026-10-01T09:00:00Z' },
  ];
  const now = '2026-10-01T09:00:00Z';
  for (const catalog of buildCatalog()) {
    const files = new Map<string, StoredFile>();
    for (const meta of catalog.files) {
      const content = meta.content;
      files.set(meta.id, {
        meta,
        content,
        etag: etagOf(content),
        modifiedAt: now,
        history: [
          {
            id: 'h-import',
            savedAt: now,
            user: 'setup',
            comment: 'Imported with the stack',
            sizeBytes: byteLength(content),
            content,
          },
        ],
      });
    }
    apps.set(catalog.id, {
      catalog,
      lastReloadAt: catalog.lastReloadAt ?? null,
      lastError: catalog.lastError ?? null,
      state: catalog.state,
      health: catalog.health,
      uptimeSeconds: catalog.uptimeSeconds,
      files,
    });
  }
}

resetSettingsStore();

export function listSettingsApps(): SettingsApp[] {
  const role = requireReader();
  return [...apps.values()].map((app) => toSettingsApp(app, role));
}

export function settingsOverview(): OverviewResponse {
  requireReader();
  return {
    generatedAt: new Date().toISOString(),
    apps: [...apps.values()].map((app) => ({
      id: app.catalog.id,
      container: containerOf(app),
      lastReloadAt: app.lastReloadAt,
      lastError: app.lastError,
    })),
  };
}

export function settingsAudit(query: AuditQuery = {}): { page: number; entries: AuditEntry[] } {
  requireReader();
  const page = query.page && query.page > 0 ? query.page : 1;
  let rows = [...audit].reverse();
  if (query.app) rows = rows.filter((row) => row.app === query.app);
  if (query.user) rows = rows.filter((row) => row.user === query.user);
  if (query.from) rows = rows.filter((row) => row.at >= query.from!);
  if (query.to) rows = rows.filter((row) => row.at <= query.to!);
  const size = 20;
  return { page, entries: rows.slice((page - 1) * size, page * size) };
}

export function readSettingsFile(appId: string, fileId: string): FileDocument {
  const role = requireReader();
  const stored = fileOf(appId, fileId);
  assertReadable(stored, role);
  return documentOf(stored);
}

export function validateSettingsFile(
  appId: string,
  fileId: string,
  content: string
): ValidateResult {
  requireEditor();
  const stored = fileOf(appId, fileId);
  return validateContent(stored.meta.language, stored.meta.path, content);
}

export function diffSettingsFile(appId: string, fileId: string, content: string): DiffResult {
  requireReader();
  const stored = fileOf(appId, fileId);
  return unifiedDiff(stored.content, content, stored.meta.path.split('/').pop() ?? fileId);
}

export function saveSettingsFile(
  appId: string,
  fileId: string,
  body: { content: string; etag: string; comment: string; apply: boolean }
): SaveResult {
  const role = requireEditor();
  const app = appOf(appId);
  const stored = fileOf(appId, fileId);
  assertWritable(app, stored, role);
  if (!body.comment || !body.comment.trim()) {
    throw new ApiError(400, 'comment_required', 'A comment is required to save.');
  }
  const validation = validateContent(stored.meta.language, stored.meta.path, body.content);
  if (!validation.ok) {
    throw new ApiError(
      422,
      'validation_failed',
      'The file did not validate. Nothing was written.',
      validation
    );
  }
  if (body.etag !== stored.etag) {
    throw new ApiError(409, 'etag_conflict', 'The file changed since you loaded it.', {
      etag: stored.etag,
    });
  }
  const now = new Date().toISOString();
  stored.content = body.content;
  stored.etag = etagOf(body.content);
  stored.modifiedAt = now;
  stored.meta = {
    ...stored.meta,
    hasSecrets: body.content.includes('__SECRET__:') || stored.meta.hasSecrets,
  };
  stored.history.push({
    id: `h-${stored.history.length + 1}`,
    savedAt: now,
    user: actor(),
    comment: body.comment.trim(),
    sizeBytes: byteLength(body.content),
    content: body.content,
  });
  stored.history = stored.history.slice(-50);
  let applyResult: SaveResult['applyResult'];
  let applied = false;
  if (body.apply) {
    applyResult = applyReload(app);
    applied = true;
  }
  recordAudit(
    appId,
    fileId,
    body.apply ? 'save-and-apply' : 'save',
    body.comment.trim(),
    validation.ok ? 'ok' : 'invalid'
  );
  return { etag: stored.etag, applied, applyResult };
}

export function fileHistory(appId: string, fileId: string): HistoryEntry[] {
  requireReader();
  const stored = fileOf(appId, fileId);
  return stored.history.map(({ content: _content, ...entry }) => entry).reverse();
}

export function historyDocument(appId: string, fileId: string, historyId: string): HistoryDocument {
  requireReader();
  const stored = fileOf(appId, fileId);
  const item = stored.history.find((entry) => entry.id === historyId);
  if (!item) throw new ApiError(404, 'not_found', 'That version was not found.');
  return {
    id: item.id,
    content: item.content,
    savedAt: item.savedAt,
    user: item.user,
    comment: item.comment,
  };
}

export function restoreHistory(
  appId: string,
  fileId: string,
  historyId: string,
  apply: boolean
): SaveResult {
  const role = requireEditor();
  const app = appOf(appId);
  const stored = fileOf(appId, fileId);
  assertWritable(app, stored, role);
  const item = stored.history.find((entry) => entry.id === historyId);
  if (!item) throw new ApiError(404, 'not_found', 'That version was not found.');
  const validation = validateContent(stored.meta.language, stored.meta.path, item.content);
  if (!validation.ok) {
    throw new ApiError(
      422,
      'validation_failed',
      'The historical version does not validate.',
      validation
    );
  }
  const comment = `Restored ${item.id} (${item.comment})`;
  return saveSettingsFile(appId, fileId, {
    content: item.content,
    etag: stored.etag,
    comment,
    apply,
  });
}

export function runAppAction(appId: string, actionId: string): ActionResult {
  const role = requireEditor();
  const app = appOf(appId);
  const action = app.catalog.actions.find((item) => item.id === actionId);
  if (!action) throw new ApiError(404, 'not_found', 'Unknown action.');
  if (action.dangerous && role !== 'Administrator') {
    throw new ApiError(403, 'forbidden', 'Only an Administrator can run this action.');
  }
  if (!action.roles.includes(role)) {
    throw new ApiError(403, 'forbidden', 'Your role cannot run this action.');
  }
  if (action.kind === 'restart') {
    app.state = 'running';
    app.health = 'healthy';
    app.uptimeSeconds = 1;
    app.lastError = null;
    recordAudit(appId, undefined, 'restart', '', 'ok');
    return {
      ok: true,
      message: `${app.catalog.name} container restarted.`,
      output: `restarted ${containerName(app)}`,
    };
  }
  if (action.kind === 'reload' || action.id === 'reload') {
    const result = applyReload(app);
    recordAudit(appId, undefined, 'reload', '', result.ok ? 'ok' : 'error');
    return { ok: result.ok, message: result.message, output: result.message };
  }
  if (action.kind === 'validate' || action.id === 'validate-all') {
    const lines: string[] = [];
    let ok = true;
    for (const stored of app.files.values()) {
      if (stored.meta.withheld) continue;
      const result = validateContent(stored.meta.language, stored.meta.path, stored.content);
      lines.push(`${stored.meta.path}: ${result.tool} ${result.ok ? 'ok' : 'failed'}`);
      if (!result.ok) {
        ok = false;
        result.messages.forEach((message) => lines.push(`  ${message.severity}: ${message.text}`));
      }
    }
    recordAudit(appId, undefined, 'validate-all', '', ok ? 'ok' : 'error');
    return {
      ok,
      message: ok ? 'All editable files validated.' : 'Validation reported errors.',
      output: lines.join('\n'),
    };
  }
  if (action.kind === 'generate' || action.id === 'generate') {
    return generateSnmp(app);
  }
  return { ok: false, message: 'This action is handled in the editor.' };
}

export function listMibs(): MibFile[] {
  requireReader();
  return mibs.map((mib) => ({ ...mib }));
}

export function addMib(name: string, sizeBytes: number): MibFile {
  requireEditor();
  const clean = name.split(/[/\\]/).pop() ?? name;
  if (!/^[A-Za-z0-9_.-]+$/.test(clean) || !/\.(mib|my|txt)$/i.test(clean)) {
    throw new ApiError(400, 'bad_mib', 'Upload a .mib, .my, or .txt MIB file.');
  }
  if (sizeBytes > 1_500_000)
    throw new ApiError(400, 'too_large', 'MIB files must be 1.5 MB or smaller.');
  const item = { name: clean, sizeBytes, uploadedAt: new Date().toISOString() };
  mibs = [...mibs.filter((mib) => mib.name !== clean), item].sort((a, b) =>
    a.name.localeCompare(b.name)
  );
  recordAudit('snmp-generator', clean, 'mib-upload', '', 'ok');
  return item;
}

export function deleteMib(name: string): { ok: boolean } {
  requireEditor();
  const before = mibs.length;
  mibs = mibs.filter((mib) => mib.name !== name);
  if (mibs.length === before) throw new ApiError(404, 'not_found', 'MIB not found.');
  recordAudit('snmp-generator', name, 'mib-delete', '', 'ok');
  return { ok: true };
}

function generateSnmp(app: StoredApp): ActionResult {
  const generator = fileOf('snmp-generator', 'generator.yml');
  const validation = validateContent('yaml', generator.meta.path, generator.content);
  if (!validation.ok) {
    return {
      ok: false,
      message: 'generator.yml did not validate.',
      output: validation.messages.map((m) => m.text).join('\n'),
    };
  }
  const produced = candidateFromGenerator(generator.content);
  const dry = validateContent('yaml', '/etc/snmp_exporter/snmp.yml', produced);
  const candidate = fileOf('snmp-generator', 'candidate-snmp.yml');
  candidate.content = produced;
  candidate.etag = etagOf(produced);
  candidate.modifiedAt = new Date().toISOString();
  candidateReady = dry.ok;
  const output = [
    'snmp-generator: wrote candidate-snmp.yml',
    `snmp_exporter --dry-run: ${dry.ok ? 'ok' : 'failed'}`,
    ...dry.messages.map((message) => `${message.severity}: ${message.text}`),
    `mibs: ${mibs.map((mib) => mib.name).join(', ')}`,
  ].join('\n');
  recordAudit('snmp-generator', 'candidate-snmp.yml', 'generate', '', dry.ok ? 'ok' : 'error');
  void app;
  return {
    ok: dry.ok,
    message: dry.ok
      ? 'Candidate snmp.yml is ready to review.'
      : 'Generator finished with validation errors.',
    output,
  };
}

export function candidateIsReady(): boolean {
  return candidateReady;
}

function candidateFromGenerator(content: string): string {
  return [
    '# Generated by snmp-generator from generator.yml.',
    '# Promote this only with "Use as live snmp.yml". Do not overwrite snmp.yml silently.',
    content.trim(),
    '',
  ].join('\n');
}

function applyReload(app: StoredApp): { ok: boolean; message: string } {
  if (app.state === 'missing' || app.state === 'exited') {
    const message = `${app.catalog.name} is ${app.state}. Start it before reloading.`;
    app.lastError = message;
    return { ok: false, message };
  }
  app.lastReloadAt = new Date().toISOString();
  app.lastError = null;
  if (app.state === 'unhealthy') {
    app.state = 'running';
    app.health = 'healthy';
  }
  return { ok: true, message: `${app.catalog.name} reloaded.` };
}

function toSettingsApp(app: StoredApp, role: RoleName): SettingsApp {
  return {
    id: app.catalog.id,
    name: app.catalog.name,
    description: app.catalog.description,
    group: app.catalog.group,
    container: containerOf(app),
    version: app.catalog.version,
    uiUrl: app.catalog.uiUrl,
    files: [...app.files.values()].map((stored) => metaFor(stored, role)),
    actions: app.catalog.actions,
  };
}

function metaFor(stored: StoredFile, role: RoleName) {
  const adminOnly = stored.meta.adminOnly === true && role !== 'Administrator';
  const editable = stored.meta.editable && !stored.meta.withheld && !adminOnly;
  return {
    id: stored.meta.id,
    path: stored.meta.path,
    label: stored.meta.label,
    language: stored.meta.language,
    sizeBytes: byteLength(stored.meta.withheld ? '' : stored.content),
    editable,
    readOnlyReason: adminOnly
      ? 'Only an Administrator can change this file.'
      : stored.meta.readOnlyReason,
    hasSecrets: stored.meta.hasSecrets || stored.meta.withheld === true,
  };
}

function containerOf(app: StoredApp) {
  return {
    name: containerName(app),
    state: app.state,
    health: app.health,
    uptimeSeconds: app.uptimeSeconds,
  };
}

function containerName(app: StoredApp): string {
  return `${app.catalog.service}-${STACK_SLUG}`;
}

function appOf(appId: string): StoredApp {
  const app = apps.get(appId);
  if (!app) throw new ApiError(404, 'not_found', `Unknown app ${appId}.`);
  return app;
}

function fileOf(appId: string, fileId: string): StoredFile {
  const app = appOf(appId);
  const stored = app.files.get(fileId);
  if (!stored) throw new ApiError(404, 'not_found', `Unknown file ${fileId}.`);
  return stored;
}

function documentOf(stored: StoredFile): FileDocument {
  const masked = [...stored.content.matchAll(/__SECRET__:([A-Za-z0-9_.-]+)/g)].map(
    (match) => match[1]
  );
  return {
    content: stored.content,
    etag: stored.etag,
    modifiedAt: stored.modifiedAt,
    language: stored.meta.language,
    maskedKeys: [...new Set(masked)],
  };
}

function assertReadable(stored: StoredFile, _role: RoleName): void {
  if (stored.meta.withheld) {
    throw new ApiError(403, 'secret_not_returned', 'Secret files are never returned.');
  }
}

function assertWritable(app: StoredApp, stored: StoredFile, role: RoleName): void {
  if (stored.meta.withheld || !stored.meta.editable) {
    throw new ApiError(403, 'read_only', stored.meta.readOnlyReason ?? 'This file is read-only.');
  }
  if (stored.meta.adminOnly && role !== 'Administrator') {
    throw new ApiError(403, 'forbidden', 'Only an Administrator can change this file.');
  }
  if ((app.catalog.id === 'postgres' || app.catalog.id === 'host') && role !== 'Administrator') {
    throw new ApiError(403, 'read_only', 'This app is read-only.');
  }
  if (app.catalog.id === 'postgres' || app.catalog.id === 'host') {
    throw new ApiError(403, 'read_only', stored.meta.readOnlyReason ?? 'This app is read-only.');
  }
}

function requireReader(): RoleName {
  const role = currentRole();
  if (!readers.includes(role)) {
    throw new ApiError(
      403,
      'forbidden',
      'Settings for applications is limited to Engineers and Administrators.'
    );
  }
  return role;
}

function requireEditor(): RoleName {
  return requireReader();
}

function currentRole(): RoleName {
  return readSession()?.role ?? 'Administrator';
}

function actor(): string {
  return readSession()?.email ?? 'm.vanderberg@noc.example';
}

function recordAudit(
  app: string,
  file: string | undefined,
  action: string,
  comment: string,
  result: string
): void {
  audit.push({
    id: `aud-${audit.length + 1}`,
    at: new Date().toISOString(),
    user: actor(),
    app,
    file,
    action,
    comment: comment || undefined,
    result,
    sourceIp: '127.0.0.1',
  });
}

export function etagOf(content: string): string {
  let hash = 5381;
  for (let i = 0; i < content.length; i += 1) hash = ((hash << 5) + hash) ^ content.charCodeAt(i);
  return `W/"${(hash >>> 0).toString(16)}-${content.length}"`;
}

function byteLength(content: string): number {
  return new TextEncoder().encode(content).length;
}
