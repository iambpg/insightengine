import { parseDocument, YAMLParseError } from 'yaml';
import type { FileLanguage, ValidateMessage, ValidateResult } from '@/lib/contract';

export function toolFor(path: string): string {
  const base = path.split('/').pop() ?? path;
  if (base === 'prometheus.yml') return 'promtool check config';
  if (base.includes('rules')) return 'promtool check rules';
  if (base === 'alertmanager.yml') return 'amtool check-config';
  if (base === 'snmp.yml' || base === 'candidate-snmp.yml') return 'snmp_exporter --dry-run';
  if (base === 'Caddyfile') return 'caddy validate';
  if (base.endsWith('.toml')) return 'ie-config toml check';
  if (base.endsWith('.json')) return 'ie-config json check';
  return 'ie-config syntax check';
}

export function validateContent(
  language: FileLanguage,
  path: string,
  content: string
): ValidateResult {
  const started = Date.now();
  const messages: ValidateMessage[] = [];
  const tool = toolFor(path);
  if (!content.trim()) {
    messages.push({ severity: 'error', line: 1, column: 1, text: 'File is empty.' });
    return finish(false, messages, tool, started);
  }
  if (language === 'json') {
    try {
      const value = JSON.parse(content) as unknown;
      messages.push(...semantic(path, value, content));
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Invalid JSON';
      messages.push({ severity: 'error', line: 1, column: 1, text: message });
    }
  } else if (language === 'yaml') {
    const doc = parseDocument(content);
    if (doc.errors.length) {
      for (const error of doc.errors) {
        const pos = error instanceof YAMLParseError ? error.linePos?.[0] : undefined;
        messages.push({
          severity: 'error',
          line: pos?.line,
          column: pos?.col,
          text: error.message,
        });
      }
    } else {
      messages.push(...semantic(path, doc.toJS(), content));
    }
  }
  const ok = !messages.some((message) => message.severity === 'error');
  if (ok && messages.length === 0) {
    messages.push({ severity: 'info', text: `${tool} reported no problems.` });
  }
  return finish(ok, messages, tool, started);
}

function finish(
  ok: boolean,
  messages: ValidateMessage[],
  tool: string,
  started: number
): ValidateResult {
  return { ok, messages, tool, durationMs: Math.max(1, Date.now() - started) };
}

function semantic(path: string, value: unknown, content: string): ValidateMessage[] {
  const base = path.split('/').pop() ?? path;
  const messages: ValidateMessage[] = [];
  if (base === 'prometheus.yml') messages.push(...checkPrometheus(value, content));
  if (base.includes('rules')) messages.push(...checkRules(value));
  if (base === 'alertmanager.yml') messages.push(...checkAlertmanager(value, content));
  if (base === 'generator.yml') messages.push(...checkGenerator(value));
  return messages;
}

function checkPrometheus(value: unknown, content: string): ValidateMessage[] {
  const messages: ValidateMessage[] = [];
  const scrape = record(value)?.scrape_configs;
  if (!Array.isArray(scrape) || scrape.length === 0) {
    messages.push({
      severity: 'error',
      line: lineOf(content, 'scrape_configs') ?? 1,
      text: 'scrape_configs must be a non-empty list.',
    });
    return messages;
  }
  scrape.forEach((job, index) => {
    const name = record(job)?.job_name;
    if (typeof name !== 'string' || !name.trim()) {
      messages.push({
        severity: 'error',
        line: lineOf(content, 'scrape_configs') ?? 1,
        text: `Scrape job ${index + 1} is missing job_name.`,
      });
    }
  });
  return messages;
}

function checkRules(value: unknown): ValidateMessage[] {
  const groups = record(value)?.groups;
  if (!Array.isArray(groups)) {
    return [{ severity: 'error', line: 1, text: 'Alert rules need a groups list.' }];
  }
  const messages: ValidateMessage[] = [];
  groups.forEach((group, groupIndex) => {
    const rules = record(group)?.rules;
    if (!Array.isArray(rules)) return;
    rules.forEach((rule, ruleIndex) => {
      const row = record(rule);
      if (!row) return;
      if (typeof row.alert === 'string' && typeof row.expr !== 'string') {
        messages.push({
          severity: 'error',
          text: `Rule ${ruleIndex + 1} in group ${groupIndex + 1} is missing expr.`,
        });
      }
    });
  });
  return messages;
}

function checkAlertmanager(value: unknown, content: string): ValidateMessage[] {
  const root = record(value);
  const messages: ValidateMessage[] = [];
  const route = record(root?.route);
  const receivers = Array.isArray(root?.receivers) ? root.receivers : [];
  const names = new Set(
    receivers
      .map((receiver) => record(receiver)?.name)
      .filter((name): name is string => typeof name === 'string')
  );
  if (!route || typeof route.receiver !== 'string') {
    messages.push({
      severity: 'error',
      line: lineOf(content, 'route') ?? 1,
      text: 'route.receiver is required.',
    });
  } else if (!names.has(route.receiver)) {
    messages.push({
      severity: 'error',
      line: lineOf(content, 'receiver:') ?? 1,
      text: `route.receiver "${route.receiver}" does not match a receiver name.`,
    });
  }
  if (names.size === 0) {
    messages.push({ severity: 'error', text: 'At least one receiver is required.' });
  }
  return messages;
}

function checkGenerator(value: unknown): ValidateMessage[] {
  const root = record(value);
  if (!root || (!isPlain(root.modules) && !Array.isArray(root.modules))) {
    return [{ severity: 'warning', text: 'generator.yml has no modules block yet.' }];
  }
  return [];
}

function record(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  return value as Record<string, unknown>;
}

function isPlain(value: unknown): boolean {
  return !!value && typeof value === 'object' && !Array.isArray(value);
}

function lineOf(content: string, needle: string): number | undefined {
  const index = content.indexOf(needle);
  if (index < 0) return undefined;
  return content.slice(0, index).split('\n').length;
}
