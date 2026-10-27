import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '@/lib/apiClient';
import { resetMockBackend } from '@/lib/mock/mockBackend';
import { listSettingsApps } from '@/lib/mock/store';
import AppEditor from './AppEditor';

const goToLine = vi.hoisted(() => vi.fn());

vi.mock('./CodeEditor', async () => {
  const ReactActual = await import('react');
  const Editor = ReactActual.forwardRef(function Editor(
    props: { value: string; onChange: (value: string) => void; readOnly?: boolean },
    ref: React.Ref<{ goToLine: (line: number) => void }>
  ) {
    ReactActual.useImperativeHandle(ref, () => ({ goToLine }));
    return ReactActual.createElement('textarea', {
      'aria-label': 'Configuration editor',
      value: props.value,
      readOnly: props.readOnly,
      onChange: (event: { target: { value: string } }) => props.onChange(event.target.value),
    });
  });
  return { default: Editor };
});

function prometheusApp() {
  const app = listSettingsApps().find((item) => item.id === 'prometheus');
  if (!app) throw new Error('prometheus app missing from the mock catalog');
  return app;
}

function renderEditor() {
  return render(
    <AppEditor
      app={prometheusApp()}
      role="Administrator"
      onOpenApp={() => undefined}
      onDirty={() => undefined}
    />
  );
}

describe('AppEditor', () => {
  beforeEach(() => {
    resetMockBackend();
    goToLine.mockReset();
    window.confirm = () => true;
  });

  it('loads a file, reports a validate error with line jump, and shows a diff', async () => {
    const user = userEvent.setup();
    renderEditor();
    const editor = await screen.findByLabelText('Configuration editor');
    expect((editor as HTMLTextAreaElement).value).toContain('job_name: prometheus');

    fireEvent.change(editor, { target: { value: 'scrape_configs: [' } });
    await user.click(screen.getByRole('button', { name: 'Validate' }));
    const list = await screen.findByRole('list', { name: 'Validation messages' });
    expect(list).toHaveTextContent(/error/i);
    const line = screen.getByRole('button', { name: /^Line / });
    await user.click(line);
    expect(goToLine).toHaveBeenCalled();

    await user.click(screen.getByRole('button', { name: 'Diff' }));
    expect(
      await screen.findByRole('region', { name: 'Diff against saved version' })
    ).toBeInTheDocument();
    expect((editor as HTMLTextAreaElement).value).toBe('scrape_configs: [');
  });

  it('saves with a comment and keeps the draft when validation fails', async () => {
    const user = userEvent.setup();
    renderEditor();
    const editor = await screen.findByLabelText('Configuration editor');
    const comment = screen.getByLabelText(/Comment/);
    expect(screen.getByRole('button', { name: /^Save$/ })).toBeDisabled();

    fireEvent.change(editor, {
      target: { value: `${(editor as HTMLTextAreaElement).value}\n# edited by test\n` },
    });
    await user.type(comment, 'widen the scrape note');
    await user.click(screen.getByRole('button', { name: /^Save$/ }));
    expect(await screen.findByText('Saved.')).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('Configuration editor'), {
      target: { value: 'scrape_configs: [' },
    });
    await user.clear(comment);
    await user.type(comment, 'this should not write');
    await user.click(screen.getByRole('button', { name: /^Save$/ }));
    expect(await screen.findByText(/nothing was written/i)).toBeInTheDocument();
    expect((screen.getByLabelText('Configuration editor') as HTMLTextAreaElement).value).toBe(
      'scrape_configs: ['
    );
  });

  it('offers reload or merge when the etag conflicts, and can restore a version', async () => {
    const user = userEvent.setup();
    renderEditor();
    const editor = await screen.findByLabelText('Configuration editor');
    const original = (editor as HTMLTextAreaElement).value;
    const saved = await api.getFile('prometheus', 'prometheus.yml');
    await api.saveFile('prometheus', 'prometheus.yml', {
      content: `${original}\n# saved elsewhere\n`,
      etag: saved.etag,
      comment: 'another session',
      apply: false,
    });

    fireEvent.change(editor, { target: { value: `${original}\n# local draft\n` } });
    await user.type(screen.getByLabelText(/Comment/), 'my edit');
    await user.click(screen.getByRole('button', { name: /^Save$/ }));
    expect(await screen.findByRole('alert')).toHaveTextContent(/saved by someone else/i);
    expect(screen.getByRole('button', { name: 'Reload server version' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Show merge view' })).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'History' }));
    expect(await screen.findByText('Imported with the stack')).toBeInTheDocument();
    const restoreButtons = screen.getAllByRole('button', { name: 'Restore' });
    await user.click(restoreButtons[restoreButtons.length - 1]);
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent(/Restored/));
    expect((screen.getByLabelText('Configuration editor') as HTMLTextAreaElement).value).toContain(
      'job_name: prometheus'
    );
  });

  it('warns before unload when the draft is dirty', async () => {
    renderEditor();
    const editor = await screen.findByLabelText('Configuration editor');
    fireEvent.change(editor, {
      target: { value: `${(editor as HTMLTextAreaElement).value}\n# dirty\n` },
    });
    await waitFor(() => {
      const event = new Event('beforeunload', { cancelable: true });
      window.dispatchEvent(event);
      expect(event.defaultPrevented).toBe(true);
    });
  });
});
