import React from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it } from 'vitest';
import ThemeMenu from './ThemeMenu';
import { THEME_KEY } from '@/lib/theme';

describe('app themes', () => {
  beforeEach(() => {
    window.localStorage.clear();
    document.documentElement.removeAttribute('data-theme');
  });

  it('switches the document theme and keeps the choice', async () => {
    const user = userEvent.setup();
    render(<ThemeMenu />);
    await user.click(screen.getByRole('button', { name: 'Theme, Day' }));
    await user.click(screen.getByRole('menuitemradio', { name: 'Night' }));
    expect(document.documentElement.dataset.theme).toBe('night');
    expect(window.localStorage.getItem(THEME_KEY)).toBe('night');
    await user.click(screen.getByRole('button', { name: 'Theme, Night' }));
    await user.click(screen.getByRole('menuitemradio', { name: 'Ocean' }));
    expect(document.documentElement.dataset.theme).toBe('ocean');
    await user.click(screen.getByRole('button', { name: 'Theme, Ocean' }));
    await user.click(screen.getByRole('menuitemradio', { name: 'Sand' }));
    expect(document.documentElement.dataset.theme).toBe('sand');
    await user.click(screen.getByRole('button', { name: 'Theme, Sand' }));
    await user.click(screen.getByRole('menuitemradio', { name: 'Day' }));
    expect(document.documentElement.hasAttribute('data-theme')).toBe(false);
    expect(window.localStorage.getItem(THEME_KEY)).toBe('day');
  });
});
