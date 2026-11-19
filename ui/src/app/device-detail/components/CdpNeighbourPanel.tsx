'use client';

import React, { useMemo, useState } from 'react';
import Link from 'next/link';
import { devicePath } from '@/lib/apiMode';
import type { DeviceDetailData, DeviceNeighbor } from '@/lib/types';
import { portNameLine } from '@/components/faceplate/portText';

export type NeighbourKind = 'switch' | 'router' | 'ap' | 'firewall' | 'phone' | 'unknown';

const SHOWN = 12;
const PREVIEW = 5;
const PANEL_H = 456;

const CAPABILITY_BITS = ['Router', 'Trans-Bridge', 'Source-Route-Bridge', 'Switch', 'Host', 'IGMP', 'Repeater', 'Phone'] as const;
const CAPABILITY_WORDS = ['Source-Route-Bridge', 'Trans-Bridge', 'Two-port Mac Relay', 'VoIP Phone', 'Router', 'Switch', 'IGMP', 'Phone', 'Host', 'Repeater'];

/** CDP capability names only. A platform string, or an empty field, becomes an em dash. */
export function formatCapabilities(raw: string | undefined): string {
  const text = (raw || '').trim();
  if (!text) return '—';
  if (/^0x[0-9a-f]+$/i.test(text) || /^\d+$/.test(text)) {
    const bits = Number.parseInt(text.replace(/^0x/i, ''), /^0x/i.test(text) ? 16 : 10);
    if (!Number.isFinite(bits)) return '—';
    const names = CAPABILITY_BITS.filter((_, index) => (bits & (1 << index)) !== 0);
    return names.length ? names.join(', ') : '—';
  }
  const pattern = new RegExp(`\\b(${CAPABILITY_WORDS.map((word) => word.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')})\\b`, 'gi');
  const found: string[] = [];
  for (const match of text.matchAll(pattern)) {
    const word = match[1];
    const canonical = CAPABILITY_WORDS.find((item) => item.toLowerCase() === word.toLowerCase()) || word;
    found.push(canonical);
  }
  const leftover = text.replace(pattern, ' ').replace(/[,;/|]+/g, ' ').replace(/\s+/g, ' ').trim();
  if (leftover || found.length === 0) return '—';
  return found.join(', ');
}

/** Icon from the platform and capability text Netdisco or CDP reported. */
export function neighbourKind(row: DeviceNeighbor): NeighbourKind {
  const text = `${row.remotePlatform || ''} ${row.remoteCapabilities || ''} ${row.remoteType || ''} ${row.remoteName || ''}`.toLowerCase();
  if (/phone|cp-\d|ip phone/.test(text)) return 'phone';
  if (/air-|c91\d|access point|\bap\b|wifi/.test(text)) return 'ap';
  if (/pa-|forti|asa|firewall/.test(text)) return 'firewall';
  if (/\brouter\b|isr\d|asr\d/.test(text)) return 'router';
  if (/switch|catalyst|c9[23]\d|nexus/.test(text)) return 'switch';
  return 'unknown';
}

export function neighbourKnown(row: DeviceNeighbor): boolean {
  return Boolean((row.remoteName || '').trim() || (row.remoteAddress || '').trim());
}

function neighbourKey(row: DeviceNeighbor, index: number): string {
  return `${row.localPort}|${row.remoteName}|${row.remotePort}|${row.source || ''}|${index}`;
}

function dash(value: string | undefined): string {
  const text = (value || '').trim();
  return text || '—';
}

function kindLabel(kind: NeighbourKind): string {
  if (kind === 'ap') return 'AP';
  return kind.charAt(0).toUpperCase() + kind.slice(1);
}

function sourceLabel(row: DeviceNeighbor): string {
  const raw = (row.source || row.protocol || '').trim().toLowerCase();
  if (raw === 'cdp') return 'CDP';
  if (raw === 'lldp') return 'LLDP';
  if (!raw) return '—';
  return raw.toUpperCase();
}

function selfKind(device: DeviceDetailData): NeighbourKind {
  return neighbourKind({
    localPort: '',
    remoteName: device.hostname,
    remotePort: '',
    remoteAddress: '',
    protocol: '',
    remotePlatform: `${device.modelFamily || ''} ${device.role || ''} ${device.faceplate?.modelName || ''}`,
  });
}

function DeviceIcon({ kind, size }: { kind: NeighbourKind; size: number }) {
  const gid = `cdp-${kind}-${size}`;
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" aria-hidden="true" style={{ display: 'block', flexShrink: 0 }}>
      <defs>
        <linearGradient id={`${gid}-blue`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#7dd3fc" />
          <stop offset="0.45" stopColor="#2563eb" />
          <stop offset="1" stopColor="#1e3a8a" />
        </linearGradient>
        <linearGradient id={`${gid}-gloss`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#ffffff" stopOpacity="0.7" />
          <stop offset="1" stopColor="#ffffff" stopOpacity="0" />
        </linearGradient>
      </defs>
      {kind === 'router' ? (
        <>
          <ellipse cx="32" cy="46" rx="18" ry="7" fill="#1e3a8a" />
          <rect x="14" y="20" width="36" height="26" fill={`url(#${gid}-blue)`} />
          <ellipse cx="32" cy="20" rx="18" ry="7" fill="#93c5fd" />
          <ellipse cx="32" cy="20" rx="18" ry="7" fill={`url(#${gid}-gloss)`} />
          <path d="M24 32h16M36 28l4 4-4 4M28 36l-4-4 4-4" fill="none" stroke="#fff" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
        </>
      ) : kind === 'ap' ? (
        <>
          <circle cx="32" cy="40" r="14" fill="#f8fafc" stroke="#cbd5e1" strokeWidth="1.5" />
          <ellipse cx="32" cy="36" rx="10" ry="5" fill={`url(#${gid}-gloss)`} />
          <path d="M22 28a12 12 0 0 1 20 0" fill="none" stroke="#38bdf8" strokeWidth="2.4" strokeLinecap="round" />
          <path d="M17 22a18 18 0 0 1 30 0" fill="none" stroke="#38bdf8" strokeWidth="2.4" strokeLinecap="round" />
          <circle cx="32" cy="40" r="2.4" fill="#0284c7" />
        </>
      ) : kind === 'firewall' ? (
        <>
          <path d="M32 8c2 6 8 8 8 14a8 8 0 0 1-16 0c0-6 6-8 8-14Z" fill="#fb923c" />
          <path d="M32 12c1 3 4 4 4 7a4 4 0 0 1-8 0c0-3 3-4 4-7Z" fill="#fde68a" />
          <rect x="14" y="28" width="36" height="24" rx="2" fill="#b91c1c" />
          <path d="M14 36h36M14 44h36M26 28v24M38 28v24" stroke="#7f1d1d" strokeWidth="2" />
        </>
      ) : kind === 'phone' || kind === 'unknown' ? (
        <>
          <circle cx="32" cy="32" r="18" fill={kind === 'phone' ? '#64748b' : '#475569'} />
          <ellipse cx="32" cy="24" rx="12" ry="6" fill={`url(#${gid}-gloss)`} />
          {kind === 'phone' ? (
            <path d="M26 24h4l2 5-3 2a12 12 0 0 0 6 6l2-3 5 2v4a3 3 0 0 1-3 3 16 16 0 0 1-16-16 3 3 0 0 1 3-3Z" fill="#e2e8f0" />
          ) : (
            <circle cx="32" cy="32" r="5" fill="#cbd5e1" />
          )}
        </>
      ) : (
        <>
          <rect x="12" y="16" width="40" height="32" rx="6" fill={`url(#${gid}-blue)`} />
          <rect x="12" y="16" width="40" height="12" rx="6" fill={`url(#${gid}-gloss)`} />
          <path d="M22 32h20M38 28l4 4-4 4M26 36l-4-4 4-4M32 24v16M28 28l4-4 4 4M28 36l4 4 4-4" fill="none" stroke="#fff" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
        </>
      )}
    </svg>
  );
}

function Fact({ label, value, testId }: { label: string; value: string; testId?: string }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, padding: '2px 0', borderBottom: '1px solid rgba(148,163,184,.22)' }}>
      <dt style={{ color: '#94a3b8', fontSize: 11 }}>{label}</dt>
      <dd data-testid={testId} style={{ margin: 0, color: '#f8fafc', fontFamily: 'ui-monospace, monospace', fontSize: 11, textAlign: 'right' }}>{value}</dd>
    </div>
  );
}

function NeighbourLine({ row, index, selected, onSelect }: { row: DeviceNeighbor; index: number; selected: boolean; onSelect: () => void }) {
  const known = neighbourKnown(row);
  const key = neighbourKey(row, index);
  return (
    <li key={key}>
      <button type="button" onClick={onSelect} style={{ display: 'flex', width: '100%', gap: 6, alignItems: 'center', border: 0, background: selected ? 'rgba(56,189,248,.16)' : 'transparent', color: '#f8fafc', padding: '3px 2px', cursor: 'pointer', textAlign: 'left', fontSize: 12 }}>
        <span style={{ width: 8, height: 8, borderRadius: 99, background: known ? '#22c55e' : '#94a3b8', boxShadow: known ? '0 0 6px #22c55e' : undefined, flexShrink: 0 }} />
        <span>{row.remoteName || row.remoteAddress || 'unknown'} <span style={{ color: '#94a3b8' }}>({kindLabel(neighbourKind(row))})</span></span>
      </button>
    </li>
  );
}

export default function CdpNeighbourPanel({ device }: { device: DeviceDetailData }) {
  const neighbors = device.neighbors ?? [];
  const [selected, setSelected] = useState<string>('self');
  const [hover, setHover] = useState<string>('');
  const [tab, setTab] = useState<'info' | 'list' | 'interfaces'>('info');
  const shown = neighbors.slice(0, SHOWN);
  const extra = neighbors.length - shown.length;
  const preview = neighbors.slice(0, PREVIEW);
  const previewExtra = neighbors.length - preview.length;
  const model = device.faceplate?.modelName || device.modelFamily || '—';
  const indexed = useMemo(() => shown.map((row, index) => ({ row, index, key: neighbourKey(row, index) })), [shown]);
  const current = indexed.find((item) => item.key === selected) || null;
  const active = neighbors.length > 0;
  const centreKind = selfKind(device);

  const spots = indexed.map((item, index) => {
    const angle = -Math.PI / 2 + (index * 2 * Math.PI) / Math.max(indexed.length, 1);
    return {
      ...item,
      x: 50 + Math.cos(angle) * 36,
      y: 50 + Math.sin(angle) * 34,
    };
  });

  const pick = (key: string) => { setSelected(key); setTab('info'); };

  return (
    <section aria-label="CDP Neighbours" data-testid="cdp-neighbour-panel" style={{ display: 'flex', height: PANEL_H, border: '1px solid #1e3a5f', borderRadius: 12, overflow: 'hidden', background: '#06101f' }}>
      <div style={{ position: 'relative', width: '70%', height: '100%', background: '#06101f', backgroundImage: 'linear-gradient(rgba(56,189,248,.08) 1px, transparent 1px), linear-gradient(90deg, rgba(56,189,248,.08) 1px, transparent 1px), radial-gradient(ellipse at 30% 45%, rgba(30,64,120,.35), transparent 42%), radial-gradient(ellipse at 68% 58%, rgba(30,64,120,.28), transparent 46%), radial-gradient(ellipse at 50% 50%, rgba(14,165,233,.16), transparent 55%)', backgroundSize: '28px 28px, 28px 28px, 100% 100%, 100% 100%, 100% 100%' }}>
        <svg viewBox="0 0 100 100" preserveAspectRatio="none" style={{ position: 'absolute', inset: 0, width: '100%', height: '100%' }} aria-hidden="true">
          <ellipse cx="22" cy="38" rx="16" ry="10" fill="rgba(125,211,252,.05)" />
          <ellipse cx="48" cy="46" rx="18" ry="11" fill="rgba(125,211,252,.05)" />
          <ellipse cx="74" cy="42" rx="14" ry="9" fill="rgba(125,211,252,.04)" />
          {spots.map((spot) => {
            const known = neighbourKnown(spot.row);
            return (
              <g key={`line-${spot.key}`}>
                <line x1="50" y1="50" x2={spot.x} y2={spot.y} stroke={known ? '#4ade80' : '#94a3b8'} strokeWidth={known ? 3 : 2} strokeDasharray={known ? undefined : '5 4'} vectorEffect="non-scaling-stroke" opacity={known ? 0.45 : 0.8} />
                <line x1="50" y1="50" x2={spot.x} y2={spot.y} stroke={known ? '#4ade80' : '#94a3b8'} strokeWidth={known ? 1.6 : 1.2} strokeDasharray={known ? undefined : '5 4'} vectorEffect="non-scaling-stroke" />
              </g>
            );
          })}
        </svg>
        <div aria-hidden="true" style={{ position: 'absolute', left: '50%', top: '50%', width: 150, height: 150, transform: 'translate(-50%, -58%)', borderRadius: '50%', background: 'radial-gradient(circle, rgba(56,189,248,.75) 0%, rgba(37,99,235,.28) 38%, transparent 70%)', pointerEvents: 'none', zIndex: 1 }} />
        <button
          type="button"
          data-testid="cdp-self"
          onClick={() => pick('self')}
          style={{ position: 'absolute', left: '50%', top: '50%', transform: 'translate(-50%, -58%)', zIndex: 2, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4, padding: 0, border: 0, background: 'transparent', color: '#f8fafc', cursor: 'pointer' }}
        >
          <DeviceIcon kind={centreKind} size={58} />
          <span style={{ textAlign: 'center', textShadow: '0 0 8px #0ea5e9' }}>
            <span style={{ display: 'block', fontSize: 12, fontWeight: 700 }}>{device.hostname}</span>
            <span style={{ display: 'block', fontSize: 10, color: '#7dd3fc' }}>{model}</span>
          </span>
        </button>
        {spots.map((spot) => {
          const kind = neighbourKind(spot.row);
          const picked = selected === spot.key;
          const known = neighbourKnown(spot.row);
          const icon = indexed.length > 8 ? 30 : 42;
          return (
            <button
              key={spot.key}
              type="button"
              data-testid={`cdp-node-${spot.index}`}
              data-kind={kind}
              data-selected={picked ? 'true' : 'false'}
              title={`${spot.row.localPort} → ${spot.row.remotePort}`}
              onMouseEnter={() => setHover(`${spot.row.localPort} → ${spot.row.remotePort}`)}
              onMouseLeave={() => setHover('')}
              onClick={() => pick(spot.key)}
              style={{ position: 'absolute', left: `${spot.x}%`, top: `${spot.y}%`, transform: 'translate(-50%, -42%)', zIndex: 2, width: indexed.length > 8 ? 92 : 118, padding: 0, border: 0, background: 'transparent', color: '#f8fafc', boxShadow: picked ? '0 0 0 3px #22c55e, 0 0 14px #4ade80' : undefined, borderRadius: 10, cursor: 'pointer', textAlign: 'center' }}
            >
              <span style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 3 }}>
                <DeviceIcon kind={kind} size={icon} />
                <span style={{ display: 'block', width: '100%', padding: '3px 6px', borderRadius: 8, background: 'rgba(6,16,32,.9)', border: picked ? '1px solid #4ade80' : '1px solid rgba(125,211,252,.28)', boxSizing: 'border-box' }}>
                  <span style={{ display: 'block', fontSize: 11, fontWeight: 700, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{spot.row.remoteName || spot.row.remoteAddress || 'unknown'}</span>
                  <span style={{ display: 'block', fontSize: 9, color: known ? '#86efac' : '#94a3b8', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{spot.row.remotePlatform || kindLabel(kind)}</span>
                </span>
              </span>
            </button>
          );
        })}
        {spots.map((spot) => {
          const known = neighbourKnown(spot.row);
          return (
            <span key={`dot-${spot.key}`} aria-hidden="true" style={{ position: 'absolute', left: `${spot.x}%`, top: `${spot.y}%`, width: 8, height: 8, marginLeft: -4, marginTop: -4, borderRadius: 99, background: known ? '#4ade80' : '#94a3b8', boxShadow: known ? '0 0 8px #4ade80' : undefined, zIndex: 3, pointerEvents: 'none' }} />
          );
        })}
        {hover ? (
          <div style={{ position: 'absolute', left: 12, bottom: 12, zIndex: 4, padding: '4px 8px', borderRadius: 6, background: '#0f172a', color: '#e2e8f0', fontSize: 11, fontFamily: 'ui-monospace, monospace', border: '1px solid rgba(74,222,128,.45)' }}>{hover}</div>
        ) : null}
        {extra > 0 ? (
          <div data-testid="cdp-more" style={{ position: 'absolute', right: 12, top: 12, zIndex: 4, padding: '3px 8px', borderRadius: 999, background: '#0f2744', color: '#e2e8f0', fontSize: 11, border: '1px solid rgba(125,211,252,.35)' }}>+{extra} more</div>
        ) : null}
      </div>
      <aside style={{ width: '30%', height: '100%', display: 'flex', flexDirection: 'column', padding: 12, boxSizing: 'border-box', color: '#f8fafc', background: 'linear-gradient(180deg, #0c2344 0%, #071526 100%)', boxShadow: 'inset 0 0 0 1px rgba(56,189,248,.85), inset 0 0 22px rgba(56,189,248,.28)' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
          <h2 style={{ margin: 0, fontSize: 14, fontWeight: 700, color: '#f8fafc' }}>CDP Neighbors</h2>
          <span data-testid="cdp-status" style={{ borderRadius: 999, padding: '2px 8px', fontSize: 11, fontWeight: 700, color: active ? '#052e16' : '#e2e8f0', background: active ? '#22c55e' : '#64748b' }}>{active ? 'Active' : 'No data'}</span>
        </div>
        {device.neighborNote ? <p style={{ margin: '8px 0 0', fontSize: 12, color: '#94a3b8' }}>{device.neighborNote}</p> : null}
        {!active && !device.neighborNote ? <p style={{ margin: '8px 0 0', fontSize: 12, color: '#94a3b8' }}>No Netdisco LLDP or CDP neighbours were returned.</p> : null}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 10 }}>
          <DeviceIcon kind={current ? neighbourKind(current.row) : centreKind} size={36} />
          <div>
            <div style={{ fontSize: 13, fontWeight: 700, color: '#f8fafc' }}>{current ? (current.row.remoteName || current.row.remoteAddress || 'unknown') : device.hostname}</div>
            <div style={{ fontSize: 11, color: '#94a3b8' }}>{current ? (current.row.remoteAddress || '—') : device.mgmtIp}</div>
            <div style={{ fontSize: 11, color: '#94a3b8' }}>{current ? (current.row.remotePlatform || '—') : model}</div>
          </div>
        </div>
        {current?.row.netboxId ? (
          <Link href={devicePath(current.row.netboxId, 'generic')} style={{ marginTop: 6, fontSize: 12, fontWeight: 650, color: '#7dd3fc' }}>Open device</Link>
        ) : null}
        <div role="tablist" aria-label="CDP neighbour details" style={{ display: 'flex', gap: 8, marginTop: 10 }}>
          {([
            ['info', 'CDP Info'],
            ['list', `Neighbors (${neighbors.length})`],
            ['interfaces', 'Interfaces'],
          ] as const).map(([id, label]) => (
            <button key={id} type="button" role="tab" aria-selected={tab === id} onClick={() => setTab(id)} style={{ border: 0, borderBottom: tab === id ? '2px solid #7dd3fc' : '2px solid transparent', background: 'transparent', color: tab === id ? '#f8fafc' : '#94a3b8', padding: '4px 0', fontSize: 11, fontWeight: 650, cursor: 'pointer' }}>{label}</button>
          ))}
        </div>
        <div style={{ marginTop: 8, overflow: 'auto', minHeight: 0, flex: 1 }}>
          {tab === 'info' ? (
            <>
              <dl style={{ margin: 0 }}>
                <Fact label="Device ID" value={dash(current ? (current.row.remoteDeviceId || current.row.remoteName) : device.hostname)} />
                <Fact label="Platform" value={dash(current ? current.row.remotePlatform : model)} />
                <Fact label="Capabilities" testId="cdp-capabilities" value={formatCapabilities(current?.row.remoteCapabilities)} />
                <Fact label="Local port" value={dash(current?.row.localPort)} />
                <Fact label="Port ID" value={dash(current?.row.remotePort)} />
                <Fact label="TTL / last seen" value={dash(current?.row.lastSeen)} />
                <Fact label="Source" value={current ? sourceLabel(current.row) : '—'} />
              </dl>
              {neighbors.length > 0 ? (
                <div data-testid="cdp-preview" style={{ marginTop: 8 }}>
                  <div style={{ fontSize: 11, fontWeight: 700, color: '#e2e8f0' }}>Neighbors</div>
                  <ul style={{ listStyle: 'none', margin: '4px 0 0', padding: 0 }}>
                    {preview.map((row, index) => (
                      <NeighbourLine key={neighbourKey(row, index)} row={row} index={index} selected={selected === neighbourKey(row, index)} onSelect={() => pick(neighbourKey(row, index))} />
                    ))}
                  </ul>
                  {previewExtra > 0 ? <div data-testid="cdp-preview-more" style={{ marginTop: 2, fontSize: 11, color: '#94a3b8' }}>+{previewExtra}</div> : null}
                </div>
              ) : null}
            </>
          ) : null}
          {tab === 'list' ? (
            neighbors.length === 0 ? (
              <p style={{ fontSize: 12, color: '#94a3b8' }}>{device.neighborNote || 'No Netdisco LLDP or CDP neighbours were returned.'}</p>
            ) : (
              <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
                {neighbors.map((row, index) => (
                  <NeighbourLine key={neighbourKey(row, index)} row={row} index={index} selected={selected === neighbourKey(row, index)} onSelect={() => pick(neighbourKey(row, index))} />
                ))}
              </ul>
            )
          ) : null}
          {tab === 'interfaces' ? <InterfaceList device={device} /> : null}
        </div>
      </aside>
    </section>
  );
}

function InterfaceList({ device }: { device: DeviceDetailData }) {
  if ((device.interfaces ?? []).length === 0 && (device.addresses ?? []).length === 0) {
    return <p style={{ marginTop: 4, fontSize: 12, color: '#94a3b8' }}>NetBox did not return interfaces or IP addresses for this device.</p>;
  }
  return (
    <ul style={{ listStyle: 'none', margin: '4px 0 0', padding: 0, color: '#e2e8f0', fontFamily: 'ui-monospace, monospace', fontSize: 11 }}>
      {(device.interfaces ?? []).map((row) => (
        <li key={row.name} style={{ marginBottom: 4 }}>
          {portNameLine(row)}
          {row.description ? ` · ${row.description}` : ''}
          {' · '}{row.enabled ? 'enabled' : 'disabled'} · {row.type || '—'}
        </li>
      ))}
      {(device.addresses ?? []).slice(0, 20).map((row) => (
        <li key={row.address} style={{ marginBottom: 4 }}>{row.address}{row.interface ? ` on ${row.interface}` : ''}</li>
      ))}
    </ul>
  );
}
