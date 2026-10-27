import React from 'react';

// Shared SVG gradients/filters for the brushed-metal look. `uid` keeps ids unique per Faceplate instance.
export default function FaceplateDefs({ uid }: { uid: string }) {
  return (
    <defs>
      <linearGradient id={`${uid}-metal`} x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stopColor="var(--metal-hi)" />
        <stop offset="0.08" stopColor="var(--metal-1)" />
        <stop offset="0.55" stopColor="var(--metal-2)" />
        <stop offset="1" stopColor="var(--metal-3)" />
      </linearGradient>
      <linearGradient id={`${uid}-brush`} x1="0" y1="0" x2="1" y2="0">
        <stop offset="0" stopColor="var(--metal-hi)" stopOpacity="0.0" />
        <stop offset="0.3" stopColor="var(--metal-hi)" stopOpacity="0.18" />
        <stop offset="0.5" stopColor="var(--metal-hi)" stopOpacity="0.04" />
        <stop offset="0.75" stopColor="var(--metal-hi)" stopOpacity="0.16" />
        <stop offset="1" stopColor="var(--metal-hi)" stopOpacity="0.0" />
      </linearGradient>
      <pattern id={`${uid}-grille`} width="6" height="6" patternUnits="userSpaceOnUse">
        <rect width="6" height="6" fill="var(--metal-3)" />
        <circle cx="3" cy="3" r="1.5" fill="var(--navy)" />
      </pattern>
      <pattern id={`${uid}-vent`} width="4" height="8" patternUnits="userSpaceOnUse">
        <rect width="4" height="8" fill="var(--metal-3)" />
        <rect x="0" y="0" width="2" height="8" fill="var(--navy)" />
      </pattern>
      <linearGradient id={`${uid}-bay`} x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stopColor="var(--navy)" />
        <stop offset="1" stopColor="var(--metal-3)" />
      </linearGradient>
      <linearGradient id={`${uid}-plate`} x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stopColor="var(--metal-hi)" />
        <stop offset="1" stopColor="var(--metal-1)" />
      </linearGradient>
      <radialGradient id={`${uid}-apbody`} cx="0.35" cy="0.3" r="0.9">
        <stop offset="0" stopColor="var(--card)" />
        <stop offset="0.7" stopColor="var(--secondary)" />
        <stop offset="1" stopColor="var(--input)" />
      </radialGradient>
      <filter id={`${uid}-shadow`} x="-5%" y="-10%" width="110%" height="140%">
        <feDropShadow dx="0" dy="3" stdDeviation="3.5" floodColor="var(--navy)" floodOpacity="0.35" />
      </filter>
      <filter id={`${uid}-glow`} x="-80%" y="-80%" width="260%" height="260%">
        <feGaussianBlur stdDeviation="1.8" result="b" />
        <feMerge>
          <feMergeNode in="b" />
          <feMergeNode in="SourceGraphic" />
        </feMerge>
      </filter>
      <filter id={`${uid}-glow-big`} x="-80%" y="-80%" width="260%" height="260%">
        <feGaussianBlur stdDeviation="4" result="b" />
        <feMerge>
          <feMergeNode in="b" />
          <feMergeNode in="SourceGraphic" />
        </feMerge>
      </filter>
    </defs>
  );
}