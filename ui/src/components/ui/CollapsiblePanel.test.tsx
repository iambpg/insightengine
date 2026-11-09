import React from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import CollapsiblePanel from './CollapsiblePanel';

describe('CollapsiblePanel', () => {
  it('expands by default and collapses on header click', async () => {
    const user = userEvent.setup();
    render(
      <CollapsiblePanel title="Faceplate" subtitle="Ports and modules">
        <p>Panel body</p>
      </CollapsiblePanel>,
    );
    const toggle = screen.getByRole('button', { name: /Faceplate/ });
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByText('Panel body')).toBeInTheDocument();
    await user.click(toggle);
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByText('Panel body')).toBeNull();
    await user.click(toggle);
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByText('Panel body')).toBeInTheDocument();
  });
});
