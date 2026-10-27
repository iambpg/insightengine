import React from 'react';
import Icon from '@/components/ui/AppIcon';

export default function ExampleDataBanner({ text = 'Example data — mock JSON from the API client; no live devices are connected.' }: { text?: string }) {
  return (
    <div
      role="note"
      className="flex items-center gap-2 rounded-md border border-warning/40 bg-warning/10 px-3 py-1.5 text-xs font-medium text-foreground"
    >
      <Icon name="BeakerIcon" size={14} />
      <span>
        <span className="label-caps mr-1.5">Example data</span>
        {text}
      </span>
    </div>
  );
}