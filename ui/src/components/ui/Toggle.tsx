'use client';

import React from 'react';

interface ToggleProps {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
}

export default function Toggle({ checked, onChange, label }: ToggleProps) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      onClick={() => onChange(!checked)}
      className={`relative inline-flex h-6 w-11 shrink-0 items-center rounded-full border transition-colors duration-200 ${
        checked ? 'border-primary bg-primary' : 'border-input bg-muted'
      }`}
    >
      <span
        className={`inline-block h-4 w-4 rounded-full bg-card shadow transition-transform duration-200 ${
          checked ? 'translate-x-6' : 'translate-x-1'
        }`}
      />
    </button>
  );
}