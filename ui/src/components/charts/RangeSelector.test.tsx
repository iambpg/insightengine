import React from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import RangeSelector from '@/components/charts/RangeSelector';

describe('RangeSelector', () => {
  it('offers a five minute range and a five minute custom window', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const onCustomMin = vi.fn();
    const { rerender } = render(
      <RangeSelector value="24h" onChange={onChange} customMin={180} onCustomMin={onCustomMin} label="Aggregate throughput" />,
    );
    await user.click(screen.getByRole('radio', { name: '5m' }));
    expect(onChange).toHaveBeenCalledWith('5m');
    rerender(
      <RangeSelector value="custom" onChange={onChange} customMin={5} onCustomMin={onCustomMin} label="Aggregate throughput" />,
    );
    expect(screen.getByRole('combobox')).toHaveValue('5');
    expect(screen.getByRole('option', { name: '5 min' })).toBeInTheDocument();
  });
});