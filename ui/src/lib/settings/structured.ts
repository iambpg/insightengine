import { parse, stringify } from 'yaml';
import { unifiedDiff } from '@/lib/settings/diff';
import type { DiffResult } from '@/lib/contract';

export type StructuredKind =
  'prometheus-scrapes' | 'prometheus-rules' | 'alertmanager' | 'snmp-summary';

export function structuredKind(fileId: string, path: string): StructuredKind | null {
  const base = path.split('/').pop() ?? fileId;
  if (base === 'prometheus.yml') return 'prometheus-scrapes';
  if (base.includes('rules') && (base.endsWith('.yml') || base.endsWith('.yaml')))
    return 'prometheus-rules';
  if (base === 'alertmanager.yml') return 'alertmanager';
  if (base === 'snmp.yml' || base === 'candidate-snmp.yml') return 'snmp-summary';
  return null;
}

export interface ScrapeJobForm {
  job_name: string;
  metrics_path: string;
  interval: string;
  targets: string;
  httpSdUrl: string;
}

export interface RuleForm {
  group: string;
  alert: string;
  expr: string;
  for: string;
  severity: string;
  summary: string;
}

export interface RouteForm {
  matchers: string;
  receiver: string;
}

export interface ReceiverForm {
  name: string;
  url: string;
  bearerTokenFile: string;
}

export interface AlertmanagerForm {
  rootReceiver: string;
  groupBy: string;
  routes: RouteForm[];
  receivers: ReceiverForm[];
}

export interface SnmpSummary {
  auths: { name: string; version: string }[];
  modules: { name: string; walks: number }[];
  lines: number;
}

function asRecord(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return {};
  return value as Record<string, unknown>;
}

export function readScrapeJobs(content: string): ScrapeJobForm[] {
  const doc = asRecord(parse(content));
  const jobs = Array.isArray(doc.scrape_configs) ? doc.scrape_configs : [];
  return jobs.map((job) => {
    const row = asRecord(job);
    const staticConfigs = Array.isArray(row.static_configs) ? row.static_configs : [];
    const targets = staticConfigs.flatMap((entry) => {
      const list = asRecord(entry).targets;
      return Array.isArray(list) ? list.map(String) : [];
    });
    const httpSd = Array.isArray(row.http_sd_configs) ? asRecord(row.http_sd_configs[0]).url : '';
    return {
      job_name: String(row.job_name ?? ''),
      metrics_path: String(row.metrics_path ?? '/metrics'),
      interval: String(row.scrape_interval ?? ''),
      targets: targets.join(', '),
      httpSdUrl: typeof httpSd === 'string' ? httpSd : '',
    };
  });
}

export function writeScrapeJobs(original: string, jobs: ScrapeJobForm[]): string {
  const doc = asRecord(parse(original) ?? {});
  doc.scrape_configs = jobs.map((job) => {
    const next: Record<string, unknown> = {
      job_name: job.job_name.trim(),
      metrics_path: job.metrics_path.trim() || '/metrics',
    };
    if (job.interval.trim()) next.scrape_interval = job.interval.trim();
    if (job.targets.trim()) {
      next.static_configs = [
        {
          targets: job.targets
            .split(',')
            .map((item) => item.trim())
            .filter(Boolean),
        },
      ];
    }
    if (job.httpSdUrl.trim()) next.http_sd_configs = [{ url: job.httpSdUrl.trim() }];
    return next;
  });
  return stringify(doc);
}

export function readRules(content: string): RuleForm[] {
  const doc = asRecord(parse(content));
  const groups = Array.isArray(doc.groups) ? doc.groups : [];
  const rows: RuleForm[] = [];
  groups.forEach((group) => {
    const groupRow = asRecord(group);
    const rules = Array.isArray(groupRow.rules) ? groupRow.rules : [];
    rules.forEach((rule) => {
      const row = asRecord(rule);
      if (typeof row.alert !== 'string') return;
      const labels = asRecord(row.labels);
      const annotations = asRecord(row.annotations);
      rows.push({
        group: String(groupRow.name ?? ''),
        alert: row.alert,
        expr: String(row.expr ?? ''),
        for: String(row.for ?? ''),
        severity: String(labels.severity ?? ''),
        summary: String(annotations.summary ?? ''),
      });
    });
  });
  return rows;
}

export function writeRules(original: string, rules: RuleForm[]): string {
  const doc = asRecord(parse(original) ?? {});
  const byGroup = new Map<string, RuleForm[]>();
  rules.forEach((rule) => {
    const name = rule.group.trim() || 'insightengine';
    const list = byGroup.get(name) ?? [];
    list.push(rule);
    byGroup.set(name, list);
  });
  doc.groups = [...byGroup.entries()].map(([name, groupRules]) => ({
    name,
    rules: groupRules.map((rule) => ({
      alert: rule.alert.trim(),
      expr: rule.expr.trim(),
      ...(rule.for.trim() ? { for: rule.for.trim() } : {}),
      labels: { severity: rule.severity.trim() || 'warning' },
      annotations: { summary: rule.summary.trim() },
    })),
  }));
  return stringify(doc);
}

export function readAlertmanager(content: string): AlertmanagerForm {
  const doc = asRecord(parse(content));
  const route = asRecord(doc.route);
  const childRoutes = Array.isArray(route.routes) ? route.routes : [];
  const receivers = Array.isArray(doc.receivers) ? doc.receivers : [];
  return {
    rootReceiver: String(route.receiver ?? ''),
    groupBy: Array.isArray(route.group_by) ? route.group_by.map(String).join(', ') : '',
    routes: childRoutes.map((child) => {
      const row = asRecord(child);
      const matchers = Array.isArray(row.matchers) ? row.matchers.map(String).join(', ') : '';
      return { matchers, receiver: String(row.receiver ?? '') };
    }),
    receivers: receivers.map((receiver) => {
      const row = asRecord(receiver);
      const hooks = Array.isArray(row.webhook_configs) ? row.webhook_configs : [];
      const hook = asRecord(hooks[0]);
      const http = asRecord(hook.http_config);
      return {
        name: String(row.name ?? ''),
        url: String(hook.url ?? ''),
        bearerTokenFile: String(http.bearer_token_file ?? hook.bearer_token_file ?? ''),
      };
    }),
  };
}

export function writeAlertmanager(original: string, form: AlertmanagerForm): string {
  const doc = asRecord(parse(original) ?? {});
  const previous = asRecord(doc.route);
  doc.route = {
    ...previous,
    receiver: form.rootReceiver.trim(),
    group_by: form.groupBy
      .split(',')
      .map((item) => item.trim())
      .filter(Boolean),
    routes: form.routes
      .filter((route) => route.receiver.trim())
      .map((route) => ({
        matchers: route.matchers
          .split(',')
          .map((item) => item.trim())
          .filter(Boolean),
        receiver: route.receiver.trim(),
      })),
  };
  doc.receivers = form.receivers
    .filter((receiver) => receiver.name.trim())
    .map((receiver) => {
      const hook: Record<string, unknown> = { url: receiver.url.trim(), send_resolved: true };
      if (receiver.bearerTokenFile.trim()) {
        hook.http_config = { bearer_token_file: receiver.bearerTokenFile.trim() };
      }
      return { name: receiver.name.trim(), webhook_configs: [hook] };
    });
  return stringify(doc);
}

export function readSnmpSummary(content: string): SnmpSummary {
  let auths: SnmpSummary['auths'] = [];
  let modules: SnmpSummary['modules'] = [];
  try {
    const doc = asRecord(parse(content));
    auths = Object.entries(asRecord(doc.auths)).map(([name, value]) => ({
      name,
      version: String(asRecord(value).version ?? asRecord(value).security_level ?? ''),
    }));
    modules = Object.entries(asRecord(doc.modules)).map(([name, value]) => {
      const walk = asRecord(value).walk;
      return { name, walks: Array.isArray(walk) ? walk.length : 0 };
    });
  } catch {
    auths = [];
    modules = [];
  }
  return { auths, modules, lines: content.split('\n').length };
}

export function previewRewrite(before: string, after: string, filename: string): DiffResult {
  return unifiedDiff(before, after, filename);
}
