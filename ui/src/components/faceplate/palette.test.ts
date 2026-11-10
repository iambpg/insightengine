import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import React from 'react';
import { FaceplateLegend } from './Faceplate';
import { STATE_COLOR, STATE_GLYPH, STATE_LABEL } from './palette';
import { PORT_STATE_META } from '@/components/ui/Badge';
import { faceplateSummaryLine, SNMP_MISSING_HINT } from './summary';

describe('port state palette', () => {
  it('draws unknown grey and keeps admin-down a different colour', () => {
    expect(STATE_COLOR.unknown.fill).toBe('var(--unknown)');
    expect(STATE_COLOR.disabled.fill).toBe('var(--disabled)');
    expect(STATE_COLOR.unknown.fill).not.toBe(STATE_COLOR.disabled.fill);
    expect(STATE_COLOR.fault.fill).toBe('var(--destructive)');
    expect(STATE_GLYPH.unknown).toBe('?');
    expect(STATE_GLYPH.disabled).toBe('▬');
    expect(STATE_LABEL.unknown).toBe('Unknown');
    expect(PORT_STATE_META.unknown.label).toBe('Unknown');
    expect(PORT_STATE_META.disabled.glyph).toBe('▬');
  });

  it('includes unknown in the legend', () => {
    render(React.createElement(FaceplateLegend));
    expect(screen.getByText('Unknown')).toBeTruthy();
    expect(screen.getByText('Disabled')).toBeTruthy();
    const unknown = screen.getByText('Unknown').closest('li');
    expect(unknown?.querySelector('span')?.getAttribute('style') || '').toContain('var(--unknown)');
  });

  it('summarises up, down, disabled, unknown and the SNMP time', () => {
    const line = faceplateSummaryLine({ up: 20, down: 2, disabled: 1, unknown: 3, fault: 1 }, '2026-11-01 21:20:00');
    expect(line).toBe('20 up · 2 down · 1 disabled · 3 unknown · 1 critical · SNMP 2026-11-01 21:20:00');
    expect(SNMP_MISSING_HINT).toBe('no SNMP interface data from Prometheus for this device');
  });
});
