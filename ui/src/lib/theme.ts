export const THEMES = [
  { id: 'day', label: 'Day' },
  { id: 'night', label: 'Night' },
  { id: 'ocean', label: 'Ocean' },
  { id: 'sand', label: 'Sand' },
] as const;

export type ThemeId = (typeof THEMES)[number]['id'];

export const THEME_KEY = 'ie-theme';

export function isThemeId(value: string | null): value is ThemeId {
  return THEMES.some((theme) => theme.id === value);
}

export function readTheme(): ThemeId {
  if (typeof window === 'undefined') return 'day';
  try {
    const stored = window.localStorage.getItem(THEME_KEY);
    return isThemeId(stored) ? stored : 'day';
  } catch {
    return 'day';
  }
}

/** Paint the theme on the document so every page that uses the shared colours follows it. */
export function applyTheme(id: ThemeId) {
  const root = document.documentElement;
  if (id === 'day') root.removeAttribute('data-theme');
  else root.dataset.theme = id;
  try {
    window.localStorage.setItem(THEME_KEY, id);
  } catch {
    /* private mode can refuse storage; the current page still changes */
  }
  window.dispatchEvent(new Event('ie-theme'));
}
