import React from 'react';
import Icon from '@/components/ui/AppIcon';

interface EmptyStateProps {
  icon: string;
  title: string;
  description: string;
  actionLabel?: string;
  onAction?: () => void;
}

export default function EmptyState({ icon, title, description, actionLabel, onAction }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-14 text-center">
      <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-muted text-muted-foreground">
        <Icon name={icon} size={26} />
      </div>
      <h3 className="text-base font-semibold">{title}</h3>
      <p className="mt-1 max-w-sm text-sm text-muted-foreground">{description}</p>
      {actionLabel && onAction ? (
        <button
          type="button"
          onClick={onAction}
          className="mt-5 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-all duration-150 hover:opacity-90 active:scale-95"
        >
          {actionLabel}
        </button>
      ) : null}
    </div>
  );
}