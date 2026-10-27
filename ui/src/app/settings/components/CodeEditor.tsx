'use client';

import React, { forwardRef, useEffect, useImperativeHandle, useRef } from 'react';
import { Annotation, EditorState, StateField } from '@codemirror/state';
import { Decoration, EditorView, WidgetType, type DecorationSet } from '@codemirror/view';
import { LanguageSupport, StreamLanguage, type StringStream } from '@codemirror/language';
import { basicSetup } from 'codemirror';
import { yaml } from '@codemirror/lang-yaml';
import { json } from '@codemirror/lang-json';
import { python } from '@codemirror/lang-python';
import type { FileLanguage } from '@/lib/contract';
import { findSecrets, rangeHitsSecret } from '@/lib/settings/secrets';

export interface CodeEditorHandle {
  goToLine: (line: number) => void;
}

interface CodeEditorProps {
  value: string;
  onChange: (value: string) => void;
  language: FileLanguage;
  readOnly?: boolean;
}

const externalSet = Annotation.define<boolean>();

class SecretWidget extends WidgetType {
  constructor(readonly secretName: string) {
    super();
  }

  eq(other: WidgetType) {
    return other instanceof SecretWidget && other.secretName === this.secretName;
  }

  toDOM() {
    const span = document.createElement('span');
    span.className = 'cm-secret-chip';
    span.textContent = `locked ${this.secretName}`;
    span.title = 'Masked secret. It cannot be edited here.';
    return span;
  }

  ignoreEvent() {
    return true;
  }
}

function secretDecorations(state: EditorState): DecorationSet {
  const marks = findSecrets(state.doc.toString()).map((span) =>
    Decoration.replace({ widget: new SecretWidget(span.secretName) }).range(span.from, span.to)
  );
  return Decoration.set(marks);
}

const secretField = StateField.define<DecorationSet>({
  create: secretDecorations,
  update(value, transaction) {
    return transaction.docChanged ? secretDecorations(transaction.state) : value;
  },
  provide: (field) => [
    EditorView.decorations.from(field),
    EditorView.atomicRanges.of((view) => view.state.field(field)),
  ],
});

const protectSecrets = EditorState.transactionFilter.of((transaction) => {
  if (!transaction.docChanged || transaction.annotation(externalSet)) return transaction;
  const text = transaction.startState.doc.toString();
  let blocked = false;
  transaction.changes.iterChanges((fromA, toA) => {
    if (rangeHitsSecret(text, fromA, toA)) blocked = true;
  });
  return blocked ? [] : transaction;
});

const theme = EditorView.theme({
  '&': { fontSize: '13px', backgroundColor: '#ffffff' },
  '.cm-scroller': {
    fontFamily: 'var(--font-mono), ui-monospace, monospace',
    minHeight: '420px',
    maxHeight: '68vh',
  },
  '.cm-gutters': { backgroundColor: '#f5f8fc', color: '#5a6a82', borderRight: '1px solid #d9e2ee' },
  '.cm-activeLine': { backgroundColor: 'rgba(54, 207, 255, 0.08)' },
  '.cm-activeLineGutter': { backgroundColor: 'rgba(54, 207, 255, 0.12)' },
});

function hashComment(stream: StringStream) {
  if (stream.match(/#.*/)) return 'comment';
  return null;
}

const tomlLanguage = new LanguageSupport(
  StreamLanguage.define({
    token(stream: StringStream) {
      const comment = hashComment(stream);
      if (comment) return comment;
      if (stream.sol() && stream.match(/\[[^\]]+\]/)) return 'heading';
      if (stream.match(/[A-Za-z0-9_.-]+(?=\s*=)/)) return 'propertyName';
      if (stream.match(/=/)) return 'operator';
      if (stream.match(/"""[\s\S]*?"""|'''[\s\S]*?'''|"[^"]*"|'[^']*'/)) return 'string';
      if (stream.match(/\b(true|false)\b/)) return 'bool';
      if (stream.match(/-?\d+(\.\d+)?/)) return 'number';
      stream.next();
      return null;
    },
  })
);

const iniLanguage = new LanguageSupport(
  StreamLanguage.define({
    token(stream: StringStream) {
      if (stream.sol()) {
        if (stream.match(/[;#].*/)) return 'comment';
        if (stream.match(/\[[^\]]+\]/)) return 'heading';
      }
      if (stream.match(/[A-Za-z0-9_.-]+(?=\s*=)/)) return 'propertyName';
      if (stream.match(/=/)) return 'operator';
      if (stream.match(/"[^"]*"|'[^']*'/)) return 'string';
      stream.next();
      return null;
    },
  })
);

const caddyLanguage = new LanguageSupport(
  StreamLanguage.define({
    token(stream: StringStream) {
      if (stream.match(/#.*/)) return 'comment';
      if (stream.match(/\{|\}/)) return 'brace';
      if (stream.match(/"(?:[^"\\]|\\.)*"/)) return 'string';
      if (stream.sol() && stream.match(/[A-Za-z0-9_*.:-]+/)) return 'keyword';
      if (stream.match(/[A-Za-z0-9_./:-]+/)) return 'variableName';
      stream.next();
      return null;
    },
  })
);

function languageExtension(language: FileLanguage) {
  if (language === 'yaml') return yaml();
  if (language === 'json') return json();
  if (language === 'python') return python();
  if (language === 'toml') return tomlLanguage;
  if (language === 'ini') return iniLanguage;
  if (language === 'caddyfile') return caddyLanguage;
  return [];
}

const CodeEditor = forwardRef<CodeEditorHandle, CodeEditorProps>(function CodeEditor(
  { value, onChange, language, readOnly = false },
  ref
) {
  const hostRef = useRef<HTMLDivElement>(null);
  const viewRef = useRef<EditorView | null>(null);
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;

  useEffect(() => {
    if (!hostRef.current) return undefined;
    const view = new EditorView({
      parent: hostRef.current,
      state: EditorState.create({
        doc: value,
        extensions: [
          basicSetup,
          theme,
          languageExtension(language),
          secretField,
          protectSecrets,
          EditorState.readOnly.of(readOnly),
          EditorView.editable.of(!readOnly),
          EditorView.updateListener.of((update) => {
            if (update.docChanged) onChangeRef.current(update.state.doc.toString());
          }),
        ],
      }),
    });
    viewRef.current = view;
    return () => {
      view.destroy();
      viewRef.current = null;
    };
    // Recreate when the language or read-only mode changes. Value sync is a separate effect.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [language, readOnly]);

  useEffect(() => {
    const view = viewRef.current;
    if (!view) return;
    const current = view.state.doc.toString();
    if (current === value) return;
    view.dispatch({
      changes: { from: 0, to: current.length, insert: value },
      annotations: externalSet.of(true),
    });
  }, [value]);

  useImperativeHandle(ref, () => ({
    goToLine(line: number) {
      const view = viewRef.current;
      if (!view) return;
      const clamped = Math.min(Math.max(1, line), view.state.doc.lines);
      const lineInfo = view.state.doc.line(clamped);
      view.dispatch({
        selection: { anchor: lineInfo.from },
        scrollIntoView: true,
      });
      view.focus();
    },
  }));

  return (
    <div
      ref={hostRef}
      aria-label="Configuration editor"
      className="overflow-hidden rounded-md border border-border"
    />
  );
});

export default CodeEditor;
