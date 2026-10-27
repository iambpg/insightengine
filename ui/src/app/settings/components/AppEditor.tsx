'use client';

import React, { useEffect, useRef, useState } from 'react';
import Icon from '@/components/ui/AppIcon';
import Badge from '@/components/ui/Badge';
import Modal from '@/components/ui/Modal';
import { api } from '@/lib/apiClient';
import { ApiError, isApiError } from '@/lib/apiError';
import type {
  ActionResult,
  DiffResult,
  FileDocument,
  HistoryEntry,
  MibFile,
  OverviewApp,
  SettingsApp,
  SettingsFileMeta,
  ValidateMessage,
  ValidateResult,
} from '@/lib/contract';
import type { RoleName } from '@/lib/types';
import { canEditFile, canRunAction } from '@/lib/settings/access';
import { structuredKind } from '@/lib/settings/structured';
import type { CodeEditorHandle } from './CodeEditor';
import DiffBlock from './DiffBlock';
import StructuredForm from './StructuredForm';

interface AppEditorProps {
  app: SettingsApp;
  overview?: OverviewApp;
  role: RoleName;
  onOpenApp: (id: string) => void;
  onDirty: (dirty: boolean) => void;
}

type EditorComponent = React.ForwardRefExoticComponent<
  {
    value: string;
    onChange: (value: string) => void;
    language: FileDocument['language'];
    readOnly?: boolean;
  } & React.RefAttributes<CodeEditorHandle>
>;

function messageOf(error: unknown): string {
  if (isApiError(error)) return error.message;
  return 'The request failed. Check your connection and try again.';
}

function validationOf(error: ApiError): ValidateResult | null {
  const details = error.details;
  if (!details || typeof details !== 'object' || !('messages' in details)) return null;
  return details as ValidateResult;
}

function formatWhen(value?: string | null): string {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toISOString().replace('T', ' ').slice(0, 16) + ' UTC';
}

export default function AppEditor({ app, overview, role, onOpenApp, onDirty }: AppEditorProps) {
  const [fileId, setFileId] = useState(app.files[0]?.id ?? '');
  const file = app.files.find((item) => item.id === fileId) ?? app.files[0];
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [base, setBase] = useState<FileDocument | null>(null);
  const [draft, setDraft] = useState('');
  const [comment, setComment] = useState('');
  const [messages, setMessages] = useState<ValidateMessage[] | null>(null);
  const [diff, setDiff] = useState<DiffResult | null>(null);
  const [diffMode, setDiffMode] = useState<'unified' | 'side'>('unified');
  const [busy, setBusy] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [conflict, setConflict] = useState<FileDocument | null>(null);
  const [mergeOpen, setMergeOpen] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [history, setHistory] = useState<HistoryEntry[] | null>(null);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [preview, setPreview] = useState<{ title: string; content: string } | null>(null);
  const [restoreApply, setRestoreApply] = useState(false);
  const [surface, setSurface] = useState<'raw' | 'form'>('raw');
  const [formKey, setFormKey] = useState(0);
  const [restartOpen, setRestartOpen] = useState(false);
  const [actionOutput, setActionOutput] = useState<string | null>(null);
  const [mibs, setMibs] = useState<MibFile[] | null>(null);
  const [generated, setGenerated] = useState<{
    output: string;
    diff: DiffResult;
    candidate: string;
    ok: boolean;
  } | null>(null);
  const [Editor, setEditor] = useState<EditorComponent | null>(null);
  const editorRef = useRef<CodeEditorHandle>(null);
  const onDirtyRef = useRef(onDirty);
  onDirtyRef.current = onDirty;
  const withheld = Boolean(file && file.hasSecrets && !file.editable);
  const readOnly = withheld || !canEditFile(role, file);
  const dirty = Boolean(base && draft !== base.content);

  useEffect(() => {
    onDirtyRef.current(dirty);
  }, [dirty]);

  useEffect(() => {
    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      if (!dirty) return;
      event.preventDefault();
      event.returnValue = '';
    };
    window.addEventListener('beforeunload', onBeforeUnload);
    return () => window.removeEventListener('beforeunload', onBeforeUnload);
  }, [dirty]);

  useEffect(() => {
    let live = true;
    import('./CodeEditor').then((mod) => {
      if (live) setEditor(() => mod.default);
    });
    return () => {
      live = false;
    };
  }, []);

  useEffect(() => {
    if (!app.files.some((item) => item.id === fileId)) {
      setFileId(app.files[0]?.id ?? '');
    }
  }, [app, fileId]);

  useEffect(() => {
    if (!file) return undefined;
    let cancelled = false;
    setSurface('raw');
    setDiff(null);
    setMessages(null);
    setConflict(null);
    setMergeOpen(false);
    setStatus(null);
    if (file.hasSecrets && !file.editable) {
      setBase(null);
      setDraft('');
      setLoading(false);
      setLoadError(null);
      return undefined;
    }
    setLoading(true);
    setLoadError(null);
    api
      .getFile(app.id, file.id)
      .then((doc) => {
        if (cancelled) return;
        setBase(doc);
        setDraft(doc.content);
      })
      .catch((error) => {
        if (!cancelled) setLoadError(messageOf(error));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [app.id, file]);

  useEffect(() => {
    if (app.id !== 'snmp-generator') return undefined;
    let cancelled = false;
    api
      .listMibs()
      .then((rows) => {
        if (!cancelled) setMibs(rows);
      })
      .catch((error) => {
        if (!cancelled) setStatus(messageOf(error));
      });
    return () => {
      cancelled = true;
    };
  }, [app.id]);

  const chooseFile = (next: string) => {
    if (next === fileId) return;
    if (dirty && !window.confirm('Discard unsaved changes to this file?')) return;
    setFileId(next);
  };

  const runValidated = async () => {
    if (!file) return;
    setBusy('validate');
    setStatus(null);
    try {
      const result = await api.validateFile(app.id, file.id, draft);
      setMessages(result.messages);
      setDiff(null);
    } catch (error) {
      setStatus(messageOf(error));
    } finally {
      setBusy(null);
    }
  };

  const runDiff = async () => {
    if (!file) return;
    setBusy('diff');
    setStatus(null);
    try {
      setDiff(await api.diffFile(app.id, file.id, draft));
      setMessages(null);
    } catch (error) {
      setStatus(messageOf(error));
    } finally {
      setBusy(null);
    }
  };

  const runSave = async (apply: boolean, etag = base?.etag) => {
    if (!file || !base || !etag) return;
    if (!comment.trim()) {
      setStatus('A comment is required to save.');
      return;
    }
    setBusy(apply ? 'apply' : 'save');
    setStatus(null);
    try {
      const result = await api.saveFile(app.id, file.id, {
        content: draft,
        etag,
        comment: comment.trim(),
        apply,
      });
      const fresh = await api.getFile(app.id, file.id);
      setBase(fresh);
      setDraft(fresh.content);
      setComment('');
      setConflict(null);
      setMergeOpen(false);
      setMessages(null);
      const applied = result.applyResult?.message ? ` ${result.applyResult.message}` : '';
      setStatus(apply ? `Saved and applied.${applied}` : 'Saved.');
    } catch (error) {
      if (isApiError(error) && error.status === 422) {
        const validation = validationOf(error);
        setMessages(validation?.messages ?? [{ severity: 'error', text: error.message }]);
        setStatus('Validation failed. The draft was kept and nothing was written.');
      } else if (isApiError(error) && error.status === 409) {
        try {
          setConflict(await api.getFile(app.id, file.id));
        } catch (loadError) {
          setStatus(messageOf(loadError));
        }
        setMergeOpen(false);
      } else {
        setStatus(messageOf(error));
      }
    } finally {
      setBusy(null);
    }
  };

  const reloadServer = () => {
    if (!conflict) return;
    setBase(conflict);
    setDraft(conflict.content);
    setConflict(null);
    setMergeOpen(false);
    setStatus('Reloaded the server version. Your draft was discarded.');
  };

  const overwriteServer = async () => {
    if (!conflict) return;
    await runSave(false, conflict.etag);
  };

  const discard = async () => {
    if (!file || withheld) return;
    setBusy('discard');
    try {
      const doc = await api.getFile(app.id, file.id);
      setBase(doc);
      setDraft(doc.content);
      setDiff(null);
      setMessages(null);
      setConflict(null);
      setStatus('Discarded unsaved changes.');
    } catch (error) {
      setStatus(messageOf(error));
    } finally {
      setBusy(null);
    }
  };

  const openHistory = async () => {
    if (!file) return;
    setHistoryOpen(true);
    setHistory(null);
    setHistoryError(null);
    try {
      setHistory(await api.fileHistory(app.id, file.id));
    } catch (error) {
      setHistoryError(messageOf(error));
    }
  };

  const viewVersion = async (entry: HistoryEntry) => {
    if (!file) return;
    try {
      const doc = await api.historyContent(app.id, file.id, entry.id);
      setPreview({ title: `${entry.comment} · ${entry.user}`, content: doc.content });
    } catch (error) {
      setStatus(messageOf(error));
    }
  };

  const restoreVersion = async (entry: HistoryEntry) => {
    if (!file) return;
    if (dirty && !window.confirm('Restore and discard the current draft?')) return;
    setBusy('restore');
    try {
      await api.restoreHistory(app.id, file.id, entry.id, { apply: restoreApply });
      const doc = await api.getFile(app.id, file.id);
      setBase(doc);
      setDraft(doc.content);
      setHistoryOpen(false);
      setStatus(`Restored “${entry.comment}”.`);
    } catch (error) {
      setStatus(messageOf(error));
    } finally {
      setBusy(null);
    }
  };

  const performAction = async (actionId: string) => {
    setBusy(actionId);
    setActionOutput(null);
    try {
      const result: ActionResult = await api.runAction(app.id, actionId);
      setStatus(result.message);
      setActionOutput(result.output ?? null);
      if (actionId === 'generate') await afterGenerate(result);
    } catch (error) {
      setStatus(messageOf(error));
    } finally {
      setBusy(null);
    }
  };

  const afterGenerate = async (result: ActionResult) => {
    const candidate = await api.getFile('snmp-generator', 'candidate-snmp.yml');
    const candidateDiff = await api.diffFile('snmp-exporter', 'snmp.yml', candidate.content);
    setGenerated({
      output: result.output ?? result.message,
      diff: candidateDiff,
      candidate: candidate.content,
      ok: result.ok,
    });
    if (file?.id === 'candidate-snmp.yml') {
      setBase(candidate);
      setDraft(candidate.content);
    }
  };

  const useAsLive = async () => {
    if (!generated) return;
    if (!comment.trim()) {
      setStatus('Enter a comment before replacing the live snmp.yml.');
      return;
    }
    setBusy('promote');
    try {
      const live = await api.getFile('snmp-exporter', 'snmp.yml');
      const saved = await api.saveFile('snmp-exporter', 'snmp.yml', {
        content: generated.candidate,
        etag: live.etag,
        comment: comment.trim(),
        apply: true,
      });
      setComment('');
      setStatus(
        saved.applied
          ? `Live snmp.yml updated. ${saved.applyResult?.message ?? ''}`
          : 'Live snmp.yml updated.'
      );
    } catch (error) {
      if (isApiError(error) && error.status === 422) {
        const validation = validationOf(error);
        setMessages(validation?.messages ?? [{ severity: 'error', text: error.message }]);
        setStatus('The candidate did not validate. snmp.yml was not changed.');
      } else {
        setStatus(messageOf(error));
      }
    } finally {
      setBusy(null);
    }
  };

  const uploadMib = async (list: FileList | null) => {
    const next = list?.[0];
    if (!next) return;
    setBusy('mib');
    try {
      await api.uploadMib(next);
      setMibs(await api.listMibs());
      setStatus(`Uploaded ${next.name}.`);
    } catch (error) {
      setStatus(messageOf(error));
    } finally {
      setBusy(null);
    }
  };

  const removeMib = async (name: string) => {
    setBusy('mib');
    try {
      await api.deleteMib(name);
      setMibs(await api.listMibs());
      setStatus(`Deleted ${name}.`);
    } catch (error) {
      setStatus(messageOf(error));
    } finally {
      setBusy(null);
    }
  };

  const kind = file ? structuredKind(file.id, file.path) : null;
  const lineCount = draft ? draft.split('\n').length : 0;

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-xl font-semibold tracking-tight">{app.name}</h2>
            <StateBadge state={overview?.container.state ?? app.container.state} />
          </div>
          <p className="mt-1 max-w-3xl text-sm text-muted-foreground">{app.description}</p>
          <p className="mt-1 font-mono-data text-xs text-muted-foreground">
            {app.container.name}
            {app.version ? ` · ${app.version}` : ''}
            {' · last reload '}
            {formatWhen(overview?.lastReloadAt)}
          </p>
          {overview?.lastError ? (
            <p className="mt-1 text-sm text-destructive">{overview.lastError}</p>
          ) : null}
        </div>
        {app.uiUrl ? (
          <a href={app.uiUrl} className="text-sm font-medium text-primary hover:underline">
            Open {app.name}
          </a>
        ) : null}
      </header>

      <div className="flex flex-wrap gap-2">
        {app.actions.map((action) => {
          const allowed = canRunAction(role, action);
          if (action.kind === 'link') {
            const target = action.id.startsWith('link:') ? action.id.slice(5) : '';
            return (
              <button
                key={action.id}
                type="button"
                onClick={() => target && onOpenApp(target)}
                className="inline-flex h-9 items-center gap-1.5 rounded-md border border-border bg-card px-3 text-sm font-medium hover:bg-muted"
              >
                <Icon name="ArrowTopRightOnSquareIcon" size={14} />
                {action.label}
              </button>
            );
          }
          return (
            <button
              key={action.id}
              type="button"
              disabled={!allowed || busy === action.id}
              title={allowed ? action.label : 'Administrators only'}
              onClick={() =>
                action.kind === 'restart' ? setRestartOpen(true) : performAction(action.id)
              }
              className={`inline-flex h-9 items-center gap-1.5 rounded-md px-3 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-50 ${
                action.dangerous
                  ? 'border border-destructive/40 text-destructive'
                  : 'border border-border bg-card hover:bg-muted'
              }`}
            >
              {action.label}
            </button>
          );
        })}
      </div>

      <div className="flex flex-wrap gap-1" role="tablist" aria-label="Configuration files">
        {app.files.map((item) => (
          <button
            key={item.id}
            type="button"
            role="tab"
            aria-selected={item.id === file?.id}
            onClick={() => chooseFile(item.id)}
            className={`rounded-md px-3 py-1.5 text-sm ${item.id === file?.id ? 'bg-navy font-semibold text-primary-foreground' : 'bg-muted text-muted-foreground hover:text-foreground'}`}
          >
            {item.label}
          </button>
        ))}
      </div>

      {file ? (
        <FileBanner file={file} readOnly={readOnly} maskedKeys={base?.maskedKeys ?? []} />
      ) : null}

      {loading ? <p role="status">Loading configuration…</p> : null}
      {loadError ? (
        <div
          role="alert"
          className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive"
        >
          {loadError}
        </div>
      ) : null}

      {!loading && !loadError && file && !withheld ? (
        <>
          <div className="flex flex-wrap items-end gap-2">
            <label htmlFor="change-comment" className="min-w-[220px] flex-1 text-xs">
              <span className="font-medium">Comment</span>
              <span className="text-destructive"> *</span>
              <input
                id="change-comment"
                value={comment}
                onChange={(event) => setComment(event.target.value)}
                placeholder="Why is this change needed?"
                className="mt-1 h-9 w-full rounded-md border border-input bg-card px-2 text-sm"
              />
            </label>
            <ToolbarButton
              label="Validate"
              busy={busy === 'validate'}
              disabled={!!busy}
              onClick={runValidated}
            />
            <ToolbarButton
              label="Diff"
              busy={busy === 'diff'}
              disabled={!!busy || !base}
              onClick={runDiff}
            />
            <ToolbarButton
              label="Save"
              busy={busy === 'save'}
              disabled={!!busy || readOnly || !dirty || !comment.trim()}
              onClick={() => runSave(false)}
              primary
            />
            <ToolbarButton
              label="Save and apply"
              busy={busy === 'apply'}
              disabled={!!busy || readOnly || !dirty || !comment.trim()}
              onClick={() => runSave(true)}
              primary
            />
            <ToolbarButton
              label="Discard"
              busy={busy === 'discard'}
              disabled={!!busy || !dirty}
              onClick={discard}
            />
            <ToolbarButton label="History" disabled={!!busy} onClick={openHistory} />
          </div>

          {kind ? (
            <div className="flex gap-1" role="tablist" aria-label="Editor mode">
              {(['form', 'raw'] as const).map((mode) => (
                <button
                  key={mode}
                  type="button"
                  role="tab"
                  aria-selected={surface === mode}
                  onClick={() => {
                    setSurface(mode);
                    if (mode === 'form') setFormKey((value) => value + 1);
                  }}
                  className={`rounded-md px-3 py-1 text-sm ${surface === mode ? 'bg-primary text-primary-foreground' : 'bg-muted'}`}
                >
                  {mode === 'form' ? 'Form' : 'Raw'}
                </button>
              ))}
            </div>
          ) : null}

          {surface === 'form' && kind ? (
            <StructuredForm
              key={`${file.id}-${formKey}`}
              kind={kind}
              filename={file.path.split('/').pop() ?? file.id}
              content={draft}
              readOnly={readOnly}
              onApply={(next) => {
                setDraft(next);
                setSurface('raw');
                setStatus('Form applied to the draft. Review it, then Save.');
              }}
            />
          ) : (
            <div>
              {Editor ? (
                <Editor
                  ref={editorRef}
                  value={draft}
                  onChange={setDraft}
                  language={file.language}
                  readOnly={readOnly}
                />
              ) : (
                <div role="status" className="h-[420px] animate-pulse rounded-md bg-muted">
                  Loading editor…
                </div>
              )}
              <p className="mt-1 text-xs text-muted-foreground">
                {file.language} · {lineCount.toLocaleString()} lines · Ctrl-F to search · fold from
                the gutter
              </p>
            </div>
          )}

          {messages ? (
            <ul
              aria-label="Validation messages"
              className="space-y-1 rounded-md border border-border bg-card p-3 text-sm"
            >
              {messages.map((message, index) => (
                <li key={`${message.text}-${index}`} className="flex flex-wrap items-start gap-2">
                  <Badge
                    tone={
                      message.severity === 'error'
                        ? 'destructive'
                        : message.severity === 'warning'
                          ? 'warning'
                          : 'info'
                    }
                  >
                    {message.severity}
                  </Badge>
                  <span>{message.text}</span>
                  {message.line ? (
                    <button
                      type="button"
                      className="font-mono-data text-xs text-primary hover:underline"
                      onClick={() => {
                        setSurface('raw');
                        editorRef.current?.goToLine(message.line ?? 1);
                      }}
                    >
                      Line {message.line}
                    </button>
                  ) : null}
                </li>
              ))}
            </ul>
          ) : null}

          {diff ? <DiffBlock diff={diff} mode={diffMode} onMode={setDiffMode} /> : null}
        </>
      ) : null}

      {status ? (
        <p role="status" className="text-sm">
          {status}
        </p>
      ) : null}
      {actionOutput ? (
        <pre className="scroll-thin max-h-40 overflow-auto rounded-md bg-navy p-3 font-mono-data text-xs text-primary-foreground">
          {actionOutput}
        </pre>
      ) : null}

      {conflict ? (
        <div
          role="alert"
          className="space-y-3 rounded-md border border-warning/50 bg-warning/10 p-3 text-sm"
        >
          <p>This file was saved by someone else since you loaded it.</p>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={reloadServer}
              className="rounded-md border border-border bg-card px-3 py-1.5"
            >
              Reload server version
            </button>
            <button
              type="button"
              onClick={() => setMergeOpen(true)}
              className="rounded-md border border-border bg-card px-3 py-1.5"
            >
              Show merge view
            </button>
          </div>
          {mergeOpen ? (
            <div className="grid gap-3 lg:grid-cols-2">
              <div>
                <p className="mb-1 text-xs font-semibold">Server copy</p>
                <pre className="scroll-thin max-h-64 overflow-auto rounded-md border border-border bg-card p-2 font-mono-data text-xs">
                  {conflict.content}
                </pre>
              </div>
              <div>
                <p className="mb-1 text-xs font-semibold">Your draft</p>
                <pre className="scroll-thin max-h-64 overflow-auto rounded-md border border-border bg-card p-2 font-mono-data text-xs">
                  {draft}
                </pre>
              </div>
              <button
                type="button"
                onClick={overwriteServer}
                disabled={!comment.trim() || busy === 'save'}
                className="rounded-md bg-navy px-3 py-1.5 text-sm font-semibold text-primary-foreground disabled:opacity-50 lg:col-span-2"
              >
                Save my draft over the server version
              </button>
            </div>
          ) : null}
        </div>
      ) : null}

      {app.id === 'snmp-generator' ? (
        <section
          className="space-y-3 rounded-md border border-border bg-card p-4"
          aria-label="SNMP generator"
        >
          <h3 className="text-base font-semibold">MIBs and generate</h3>
          <p className="text-sm text-muted-foreground">
            Generate runs generator.yml against the MIB directory, validates the candidate with
            snmp_exporter --dry-run, and does not touch the live snmp.yml until you say so.
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <label className="inline-flex h-9 cursor-pointer items-center rounded-md border border-border px-3 text-sm">
              Upload MIB
              <input
                aria-label="Upload MIB"
                type="file"
                accept=".mib,.my,.txt"
                className="sr-only"
                onChange={(event) => {
                  uploadMib(event.target.files);
                  event.target.value = '';
                }}
              />
            </label>
          </div>
          <ul className="divide-y divide-border rounded-md border border-border text-sm">
            {(mibs ?? []).map((mib) => (
              <li key={mib.name} className="flex items-center justify-between px-3 py-2">
                <span className="font-mono-data">{mib.name}</span>
                <button
                  type="button"
                  className="text-xs text-destructive"
                  onClick={() => removeMib(mib.name)}
                >
                  Delete
                </button>
              </li>
            ))}
          </ul>
          {generated ? (
            <div className="space-y-2">
              <pre className="scroll-thin max-h-40 overflow-auto rounded-md bg-muted p-3 font-mono-data text-xs">
                {generated.output}
              </pre>
              <DiffBlock diff={generated.diff} mode="unified" onMode={() => undefined} />
              <button
                type="button"
                disabled={!generated.ok || !!busy}
                onClick={useAsLive}
                className="rounded-md bg-primary px-3 py-1.5 text-sm font-semibold text-primary-foreground disabled:opacity-50"
              >
                Use as live snmp.yml
              </button>
            </div>
          ) : null}
        </section>
      ) : null}

      {historyOpen ? (
        <div className="fixed inset-y-0 right-0 z-[70] flex w-full max-w-md flex-col border-l border-border bg-card shadow-pop">
          <header className="flex items-center justify-between border-b border-border px-4 py-3">
            <h3 className="font-semibold">History</h3>
            <button type="button" aria-label="Close history" onClick={() => setHistoryOpen(false)}>
              <Icon name="XMarkIcon" size={18} />
            </button>
          </header>
          <label className="flex items-center gap-2 px-4 py-3 text-sm">
            <input
              type="checkbox"
              checked={restoreApply}
              onChange={(event) => setRestoreApply(event.target.checked)}
            />
            Reload the app after restore
          </label>
          <div className="scroll-thin flex-1 space-y-2 overflow-y-auto px-4 pb-6">
            {historyError ? <p className="text-sm text-destructive">{historyError}</p> : null}
            {history === null ? <p role="status">Loading history…</p> : null}
            {history?.map((entry) => (
              <article key={entry.id} className="rounded-md border border-border p-3 text-sm">
                <p className="font-medium">{entry.comment}</p>
                <p className="text-xs text-muted-foreground">
                  {entry.user} · {formatWhen(entry.savedAt)}
                </p>
                <div className="mt-2 flex gap-2">
                  <button
                    type="button"
                    className="rounded-md border border-border px-2 py-1 text-xs"
                    onClick={() => viewVersion(entry)}
                  >
                    View
                  </button>
                  <button
                    type="button"
                    className="rounded-md bg-navy px-2 py-1 text-xs font-semibold text-primary-foreground disabled:opacity-50"
                    disabled={readOnly || busy === 'restore'}
                    onClick={() => restoreVersion(entry)}
                  >
                    Restore
                  </button>
                </div>
              </article>
            ))}
          </div>
        </div>
      ) : null}

      <Modal
        open={!!preview}
        onClose={() => setPreview(null)}
        title={preview?.title ?? 'Version'}
        width="max-w-3xl"
      >
        <pre className="scroll-thin max-h-96 overflow-auto font-mono-data text-xs">
          {preview?.content}
        </pre>
      </Modal>

      <Modal
        open={restartOpen}
        onClose={() => setRestartOpen(false)}
        title={`Restart ${app.name}?`}
        description="Restarting drops in-flight scrapes or sessions until the container is healthy again. Only an Administrator can do this."
        footer={
          <>
            <button
              type="button"
              onClick={() => setRestartOpen(false)}
              className="rounded-md border border-border px-3 py-1.5 text-sm"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={() => {
                setRestartOpen(false);
                performAction('restart');
              }}
              className="rounded-md bg-destructive px-3 py-1.5 text-sm font-semibold text-destructive-foreground"
            >
              Restart container
            </button>
          </>
        }
      />
    </div>
  );
}

function FileBanner({
  file,
  readOnly,
  maskedKeys,
}: {
  file: SettingsFileMeta;
  readOnly: boolean;
  maskedKeys: string[];
}) {
  if (!readOnly && maskedKeys.length === 0) return null;
  return (
    <div className="space-y-2">
      {readOnly ? (
        <p className="rounded-md border border-info/30 bg-info/10 px-3 py-2 text-sm">
          {file.readOnlyReason ?? 'This file is read-only.'}
        </p>
      ) : null}
      {maskedKeys.length > 0 ? (
        <p className="flex flex-wrap items-center gap-2 text-sm">
          <Icon name="LockClosedIcon" size={14} />
          Masked secrets cannot be edited here:
          {maskedKeys.map((key) => (
            <span key={key} className="cm-secret-chip">
              locked {key}
            </span>
          ))}
        </p>
      ) : null}
    </div>
  );
}

function StateBadge({ state }: { state: string }) {
  const tone =
    state === 'running'
      ? 'success'
      : state === 'unhealthy'
        ? 'destructive'
        : state === 'exited'
          ? 'warning'
          : 'neutral';
  return <Badge tone={tone}>{state}</Badge>;
}

function ToolbarButton({
  label,
  onClick,
  disabled,
  busy,
  primary,
}: {
  label: string;
  onClick: () => void;
  disabled?: boolean;
  busy?: boolean;
  primary?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={`inline-flex h-9 items-center rounded-md px-3 text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-50 ${
        primary ? 'bg-primary text-primary-foreground' : 'border border-border bg-card'
      }`}
    >
      {busy ? 'Working…' : label}
    </button>
  );
}
