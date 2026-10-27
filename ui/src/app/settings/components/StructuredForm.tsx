'use client';

import React, { useMemo, useState } from 'react';
import Icon from '@/components/ui/AppIcon';
import Modal from '@/components/ui/Modal';
import type { DiffResult } from '@/lib/contract';
import {
  previewRewrite,
  readAlertmanager,
  readRules,
  readScrapeJobs,
  readSnmpSummary,
  writeAlertmanager,
  writeRules,
  writeScrapeJobs,
  type AlertmanagerForm,
  type RuleForm,
  type ScrapeJobForm,
  type StructuredKind,
} from '@/lib/settings/structured';
import DiffBlock from './DiffBlock';

interface StructuredFormProps {
  kind: StructuredKind;
  filename: string;
  content: string;
  readOnly: boolean;
  onApply: (next: string) => void;
}

export default function StructuredForm({
  kind,
  filename,
  content,
  readOnly,
  onApply,
}: StructuredFormProps) {
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<{ next: string; diff: DiffResult } | null>(null);

  if (kind === 'snmp-summary') {
    return <SnmpSummary content={content} />;
  }

  const propose = (next: string) => {
    try {
      setPending({ next, diff: previewRewrite(content, next, filename) });
      setError(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not build the file.');
    }
  };

  return (
    <div className="space-y-3">
      <p className="rounded-md border border-warning/40 bg-warning/10 px-3 py-2 text-sm">
        Applying the form rewrites this file. Comments and formatting may change. Nothing is saved
        until you press Save.
      </p>
      {error ? (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      ) : null}
      {kind === 'prometheus-scrapes' ? (
        <ScrapeForm content={content} readOnly={readOnly} onPropose={propose} />
      ) : null}
      {kind === 'prometheus-rules' ? (
        <RulesForm content={content} readOnly={readOnly} onPropose={propose} />
      ) : null}
      {kind === 'alertmanager' ? (
        <AlertForm content={content} readOnly={readOnly} onPropose={propose} />
      ) : null}
      <Modal
        open={!!pending}
        onClose={() => setPending(null)}
        title="Review the rewrite"
        description="Comments and formatting may change. This updates the draft only."
        width="max-w-3xl"
        footer={
          <>
            <button
              type="button"
              onClick={() => setPending(null)}
              className="rounded-md border border-border px-3 py-1.5 text-sm"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={() => {
                if (pending) onApply(pending.next);
                setPending(null);
              }}
              className="rounded-md bg-primary px-3 py-1.5 text-sm font-semibold text-primary-foreground"
            >
              Apply to draft
            </button>
          </>
        }
      >
        {pending ? <DiffBlock diff={pending.diff} mode="unified" onMode={() => undefined} /> : null}
      </Modal>
    </div>
  );
}

function SnmpSummary({ content }: { content: string }) {
  const summary = useMemo(() => readSnmpSummary(content), [content]);
  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">
        Read-only summary of {summary.lines.toLocaleString()} lines. Search and fold the raw file to
        edit modules. A full snmp.yml is hundreds of kilobytes; this view does not try to rewrite
        it.
      </p>
      <div className="grid gap-3 md:grid-cols-2">
        <SummaryTable
          title="Auths"
          rows={summary.auths.map((auth) => [auth.name, auth.version || '—'])}
        />
        <SummaryTable
          title="Modules"
          rows={summary.modules.map((mod) => [mod.name, `${mod.walks} walks`])}
        />
      </div>
    </div>
  );
}

function SummaryTable({ title, rows }: { title: string; rows: string[][] }) {
  return (
    <section className="rounded-md border border-border">
      <h3 className="border-b border-border px-3 py-2 text-sm font-semibold">{title}</h3>
      <table className="w-full text-sm">
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td className="px-3 py-3 text-muted-foreground">None found.</td>
            </tr>
          ) : (
            rows.map((row) => (
              <tr key={row.join('-')} className="border-b border-border last:border-0">
                <td className="px-3 py-1.5 font-mono-data">{row[0]}</td>
                <td className="px-3 py-1.5 text-right text-muted-foreground">{row[1]}</td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </section>
  );
}

function useParsed<T>(
  content: string,
  read: (content: string) => T,
  fallback: T
): { value: T; error: string | null } {
  return useMemo(() => {
    try {
      return { value: read(content), error: null };
    } catch (cause) {
      return {
        value: fallback,
        error:
          cause instanceof Error
            ? cause.message
            : 'This file is not valid YAML yet. Fix it in the raw editor.',
      };
    }
  }, [content, read, fallback]);
}

const NO_JOBS: ScrapeJobForm[] = [];
const NO_RULES: RuleForm[] = [];
const EMPTY_ALERT: AlertmanagerForm = { rootReceiver: '', groupBy: '', routes: [], receivers: [] };

function ScrapeForm({
  content,
  readOnly,
  onPropose,
}: {
  content: string;
  readOnly: boolean;
  onPropose: (next: string) => void;
}) {
  const parsed = useParsed(content, readScrapeJobs, NO_JOBS);
  const [jobs, setJobs] = useState<ScrapeJobForm[]>(parsed.value);
  const update = (index: number, patch: Partial<ScrapeJobForm>) => {
    setJobs((current) => current.map((job, i) => (i === index ? { ...job, ...patch } : job)));
  };
  return (
    <FormShell
      readOnly={readOnly}
      error={parsed.error}
      onAdd={() =>
        setJobs((current) => [
          ...current,
          { job_name: '', metrics_path: '/metrics', interval: '30s', targets: '', httpSdUrl: '' },
        ])
      }
      onApply={() => onPropose(writeScrapeJobs(content, jobs))}
    >
      {jobs.map((job, index) => (
        <fieldset
          key={`job-${index}`}
          className="grid gap-2 rounded-md border border-border p-3 md:grid-cols-2"
        >
          <legend className="px-1 text-xs font-semibold">Scrape job {index + 1}</legend>
          <Field
            label="job_name"
            value={job.job_name}
            onChange={(value) => update(index, { job_name: value })}
          />
          <Field
            label="metrics_path"
            value={job.metrics_path}
            onChange={(value) => update(index, { metrics_path: value })}
          />
          <Field
            label="interval"
            value={job.interval}
            onChange={(value) => update(index, { interval: value })}
          />
          <Field
            label="targets (comma separated)"
            value={job.targets}
            onChange={(value) => update(index, { targets: value })}
          />
          <Field
            label="http_sd URL"
            value={job.httpSdUrl}
            onChange={(value) => update(index, { httpSdUrl: value })}
          />
          <button
            type="button"
            className="text-left text-xs text-destructive"
            onClick={() => setJobs((current) => current.filter((_, i) => i !== index))}
          >
            Remove job
          </button>
        </fieldset>
      ))}
    </FormShell>
  );
}

function RulesForm({
  content,
  readOnly,
  onPropose,
}: {
  content: string;
  readOnly: boolean;
  onPropose: (next: string) => void;
}) {
  const parsed = useParsed(content, readRules, NO_RULES);
  const [rules, setRules] = useState<RuleForm[]>(parsed.value);
  const update = (index: number, patch: Partial<RuleForm>) => {
    setRules((current) => current.map((rule, i) => (i === index ? { ...rule, ...patch } : rule)));
  };
  return (
    <FormShell
      readOnly={readOnly}
      error={parsed.error}
      onAdd={() =>
        setRules((current) => [
          ...current,
          {
            group: 'insightengine',
            alert: '',
            expr: '',
            for: '5m',
            severity: 'warning',
            summary: '',
          },
        ])
      }
      onApply={() => onPropose(writeRules(content, rules))}
    >
      {rules.map((rule, index) => (
        <fieldset
          key={`rule-${index}`}
          className="grid gap-2 rounded-md border border-border p-3 md:grid-cols-2"
        >
          <legend className="px-1 text-xs font-semibold">
            {rule.alert || `Rule ${index + 1}`}
          </legend>
          <Field
            label="group"
            value={rule.group}
            onChange={(value) => update(index, { group: value })}
          />
          <Field
            label="alert"
            value={rule.alert}
            onChange={(value) => update(index, { alert: value })}
          />
          <Field
            label="expr"
            value={rule.expr}
            onChange={(value) => update(index, { expr: value })}
          />
          <Field label="for" value={rule.for} onChange={(value) => update(index, { for: value })} />
          <Field
            label="severity"
            value={rule.severity}
            onChange={(value) => update(index, { severity: value })}
          />
          <Field
            label="summary"
            value={rule.summary}
            onChange={(value) => update(index, { summary: value })}
          />
        </fieldset>
      ))}
    </FormShell>
  );
}

function AlertForm({
  content,
  readOnly,
  onPropose,
}: {
  content: string;
  readOnly: boolean;
  onPropose: (next: string) => void;
}) {
  const parsed = useParsed(content, readAlertmanager, EMPTY_ALERT);
  const [form, setForm] = useState<AlertmanagerForm>(parsed.value);
  return (
    <FormShell
      readOnly={readOnly}
      error={parsed.error}
      onApply={() => onPropose(writeAlertmanager(content, form))}
    >
      <div className="grid gap-2 md:grid-cols-2">
        <Field
          label="root receiver"
          value={form.rootReceiver}
          onChange={(value) => setForm({ ...form, rootReceiver: value })}
        />
        <Field
          label="group_by"
          value={form.groupBy}
          onChange={(value) => setForm({ ...form, groupBy: value })}
        />
      </div>
      <h3 className="text-sm font-semibold">Child routes</h3>
      {form.routes.map((route, index) => (
        <div key={`route-${index}`} className="grid gap-2 md:grid-cols-2">
          <Field
            label="matchers"
            value={route.matchers}
            onChange={(value) =>
              setForm({
                ...form,
                routes: form.routes.map((item, i) =>
                  i === index ? { ...item, matchers: value } : item
                ),
              })
            }
          />
          <Field
            label="receiver"
            value={route.receiver}
            onChange={(value) =>
              setForm({
                ...form,
                routes: form.routes.map((item, i) =>
                  i === index ? { ...item, receiver: value } : item
                ),
              })
            }
          />
        </div>
      ))}
      <button
        type="button"
        className="text-xs font-semibold text-primary"
        onClick={() =>
          setForm({ ...form, routes: [...form.routes, { matchers: '', receiver: '' }] })
        }
      >
        Add route
      </button>
      <h3 className="text-sm font-semibold">Receivers</h3>
      {form.receivers.map((receiver, index) => (
        <div key={`rx-${index}`} className="grid gap-2 md:grid-cols-3">
          <Field
            label="name"
            value={receiver.name}
            onChange={(value) =>
              setForm({
                ...form,
                receivers: form.receivers.map((item, i) =>
                  i === index ? { ...item, name: value } : item
                ),
              })
            }
          />
          <Field
            label="webhook URL"
            value={receiver.url}
            onChange={(value) =>
              setForm({
                ...form,
                receivers: form.receivers.map((item, i) =>
                  i === index ? { ...item, url: value } : item
                ),
              })
            }
          />
          <Field
            label="bearer token file"
            value={receiver.bearerTokenFile}
            onChange={(value) =>
              setForm({
                ...form,
                receivers: form.receivers.map((item, i) =>
                  i === index ? { ...item, bearerTokenFile: value } : item
                ),
              })
            }
          />
        </div>
      ))}
    </FormShell>
  );
}

function FormShell({
  children,
  readOnly,
  error,
  onAdd,
  onApply,
}: {
  children: React.ReactNode;
  readOnly: boolean;
  error?: string | null;
  onAdd?: () => void;
  onApply: () => void;
}) {
  return (
    <div className="space-y-3">
      {error ? <p className="text-sm text-destructive">{error}</p> : null}
      {children}
      {readOnly ? null : (
        <div className="flex flex-wrap gap-2">
          {onAdd ? (
            <button
              type="button"
              onClick={onAdd}
              className="rounded-md border border-border px-3 py-1.5 text-sm"
            >
              Add row
            </button>
          ) : null}
          <button
            type="button"
            onClick={onApply}
            className="inline-flex items-center gap-1.5 rounded-md bg-navy px-3 py-1.5 text-sm font-semibold text-primary-foreground"
          >
            <Icon name="DocumentMagnifyingGlassIcon" size={14} />
            Review diff
          </button>
        </div>
      )}
    </div>
  );
}

function Field({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  const id = `sf-${label.replace(/\s+/g, '-')}`;
  return (
    <label htmlFor={id} className="block text-xs">
      <span className="text-muted-foreground">{label}</span>
      <input
        id={id}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="mt-1 h-8 w-full rounded-md border border-input bg-card px-2 font-mono-data text-xs"
      />
    </label>
  );
}
