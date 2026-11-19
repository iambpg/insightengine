'use client';

import React, { useMemo, useState } from 'react';
import Link from 'next/link';
import { devicePath } from '@/lib/apiMode';
import type { DeviceDetailData, DeviceNeighbor } from '@/lib/types';
import { portNameLine } from '@/components/faceplate/portText';

export type NeighbourKind = 'switch' | 'router' | 'ap' | 'firewall' | 'phone' | 'unknown';

const SHOWN = 12;
const PANEL_H = 320;

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

function sourceLabel(row: DeviceNeighbor): string {
  const raw = (row.source || row.protocol || '').trim().toLowerCase();
  if (raw === 'cdp') return 'CDP';
  if (raw === 'lldp') return 'LLDP';
  if (!raw) return '—';
  return raw.toUpperCase();
}

function KindIcon({ kind, glow }: { kind: NeighbourKind | 'self'; glow?: boolean }) {
  const color = kind === 'self' ? '#7dd3fc' : '#e2e8f0';
  return (
    <svg width={22} height={22} viewBox="0 0 24 24" aria-hidden="true" style={{ display: 'block', filter: glow ? 'drop-shadow(0 0 6px #38bdf8)' : undefined }}>
      {kind === 'ap' ? (
        <>
          <path d="M8 16a6 6 0 0 1 8 0" fill="none" stroke={color} strokeWidth="1.6" strokeLinecap="round" />
          <path d="M5.5 13.2a9 9 0 0 1 13 0" fill="none" stroke={color} strokeWidth="1.6" strokeLinecap="round" />
          <circle cx="12" cy="18" r="1.4" fill={color} />
        </>
      ) : kind === 'firewall' ? (
        <path d="M12 3 5 6v6c0 4.2 2.8 7.2 7 8.5 4.2-1.3 7-4.3 7-8.5V6l-7-3Z" fill="none" stroke={color} strokeWidth="1.6" />
      ) : kind === 'phone' || kind === 'unknown' ? (
        <path d="M8 4h3l1.2 3-1.8 1.1a10 10 0 0 0 5.5 5.5L17 12l3 1.2v3A2 2 0 0 1 18 18 14 14 0 0 1 6 6a2 2 0 0 1 2-2Z" fill="none" stroke={color} strokeWidth="1.6" strokeLinejoin="round" />
      ) : kind === 'router' ? (
        <>
          <rect x="4" y="8" width="16" height="8" rx="1.5" fill="none" stroke={color} strokeWidth="1.6" />
          <path d="M8 8V5M12 8V4M16 8V5" stroke={color} strokeWidth="1.6" strokeLinecap="round" />
        </>
      ) : (
        <>
          <rect x="3" y="6" width="18" height="6" rx="1.4" fill="none" stroke={color} strokeWidth="1.6" />
          <rect x="3" y="13" width="18" height="6" rx="1.4" fill="none" stroke={color} strokeWidth="1.6" />
          <circle cx="7" cy="9" r="0.8" fill={color} />
          <circle cx="7" cy="16" r="0.8" fill={color} />
        </>
      )}
    </svg>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, padding: '4px 0', borderBottom: '1px solid #e2e8f0' }}>
      <dt style={{ color: '#64748b', fontSize: 11 }}>{label}</dt>
      <dd style={{ margin: 0, fontFamily: 'ui-monospace, monospace', fontSize: 11, textAlign: 'right' }}>{value}</dd>
    </div>
  );
}

export default function CdpNeighbourPanel({ device }: { device: DeviceDetailData }) {
  const neighbors = device.neighbors ?? [];
  const [selected, setSelected] = useState<string>('self');
  const [hover, setHover] = useState<string>('');
  const [tab, setTab] = useState<'info' | 'list' | 'interfaces'>('info');
  const shown = neighbors.slice(0, SHOWN);
  const extra = neighbors.length - shown.length;
  const model = device.faceplate?.modelName || device.modelFamily || '—';
  const indexed = useMemo(() => shown.map((row, index) => ({ row, index, key: neighbourKey(row, index) })), [shown]);
  const current = indexed.find((item) => item.key === selected) || null;
  const active = neighbors.length > 0;

  const spots = indexed.map((item, index) => {
    const angle = -Math.PI / 2 + (index * 2 * Math.PI) / Math.max(indexed.length, 1);
    return {
      ...item,
      x: 50 + Math.cos(angle) * 36,
      y: 50 + Math.sin(angle) * 34,
    };
  });

  return (
    <section aria-label="CDP Neighbours" data-testid="cdp-neighbour-panel" style={{ display: 'flex', height: PANEL_H, border: '1px solid #1e293b', borderRadius: 12, overflow: 'hidden', background: '#fff' }}>
      <div style={{ position: 'relative', width: '70%', height: '100%', background: '#071426', backgroundImage: 'linear-gradient(rgba(148,163,184,.14) 1px, transparent 1px), linear-gradient(90deg, rgba(148,163,184,.14) 1px, transparent 1px), radial-gradient(ellipse at 50% 48%, rgba(56,189,248,.16), transparent 58%)', backgroundSize: '28px 28px, 28px 28px, 100% 100%' }}>
        <svg viewBox="0 0 100 100" preserveAspectRatio="none" style={{ position: 'absolute', inset: 0, width: '100%', height: '100%' }} aria-hidden="true">
          <ellipse cx="50" cy="52" rx="42" ry="30" fill="none" stroke="rgba(125,211,252,.18)" strokeWidth="0.4" />
          <ellipse cx="28" cy="40" rx="14" ry="8" fill="rgba(148,163,184,.08)" />
          <ellipse cx="68" cy="46" rx="16" ry="9" fill="rgba(148,163,184,.07)" />
          {spots.map((spot) => {
            const known = neighbourKnown(spot.row);
            return (
              <g key={`line-${spot.key}`}>
                <line x1="50" y1="50" x2={spot.x} y2={spot.y} stroke={known ? '#22c55e' : '#94a3b8'} strokeWidth={known ? 0.7 : 0.45} strokeDasharray={known ? undefined : '1.2 1.1'} style={{ filter: known ? 'drop-shadow(0 0 1px #22c55e)' : undefined }} />
                <circle cx={spot.x} cy={spot.y} r="1.1" fill={known ? '#4ade80' : '#94a3b8'} />
              </g>
            );
          })}
        </svg>
        <button
          type="button"
          data-testid="cdp-self"
          onClick={() => { setSelected('self'); setTab('info'); }}
          style={{ position: 'absolute', left: '50%', top: '50%', transform: 'translate(-50%, -50%)', zIndex: 2, display: 'flex', alignItems: 'center', gap: 8, padding: '8px 10px', borderRadius: 10, border: selected === 'self' ? '2px solid #fff' : '1px solid #38bdf8', background: 'rgba(14,42,78,.92)', color: '#e0f2fe', boxShadow: selected === 'self' ? '0 0 0 3px #0ea5e9, 0 0 18px #38bdf8' : '0 0 16px rgba(56,189,248,.85)', cursor: 'pointer' }}
        >
          <KindIcon kind="self" glow />
          <span style={{ textAlign: 'left' }}>
            <span style={{ display: 'block', fontSize: 12, fontWeight: 700 }}>{device.hostname}</span>
            <span style={{ display: 'block', fontSize: 10, color: '#7dd3fc' }}>{model}</span>
          </span>
        </button>
        {spots.map((spot) => {
          const kind = neighbourKind(spot.row);
          const picked = selected === spot.key;
          const known = neighbourKnown(spot.row);
          return (
            <button
              key={spot.key}
              type="button"
              data-testid={`cdp-node-${spot.index}`}
              data-kind={kind}
              title={`${spot.row.localPort} → ${spot.row.remotePort}`}
              onMouseEnter={() => setHover(`${spot.row.localPort} → ${spot.row.remotePort}`)}
              onMouseLeave={() => setHover('')}
              onClick={() => { setSelected(spot.key); setTab('info'); }}
              style={{ position: 'absolute', left: `${spot.x}%`, top: `${spot.y}%`, transform: 'translate(-50%, -50%)', zIndex: 2, width: indexed.length > 8 ? 96 : 128, padding: '5px 7px', borderRadius: 8, border: picked ? '2px solid #fff' : '1px solid rgba(226,232,240,.35)', background: 'rgba(15,23,42,.88)', color: '#f8fafc', boxShadow: picked ? '0 0 0 3px #22c55e, 0 0 14px #4ade80' : '0 4px 12px rgba(0,0,0,.35)', cursor: 'pointer', textAlign: 'left' }}
            >
              <span style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                <KindIcon kind={kind} />
                <span>
                  <span style={{ display: 'block', fontSize: 11, fontWeight: 650, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: indexed.length > 8 ? 62 : 88 }}>{spot.row.remoteName || spot.row.remoteAddress || 'unknown'}</span>
                  <span style={{ display: 'block', fontSize: 9, color: known ? '#86efac' : '#94a3b8' }}>{spot.row.remotePlatform || kind}</span>
                </span>
              </span>
            </button>
          );
        })}
        {hover ? (
          <div style={{ position: 'absolute', left: 12, bottom: 12, zIndex: 3, padding: '4px 8px', borderRadius: 6, background: '#0f172a', color: '#e2e8f0', fontSize: 11, fontFamily: 'ui-monospace, monospace' }}>{hover}</div>
        ) : null}
        {extra > 0 ? (
          <div data-testid="cdp-more" style={{ position: 'absolute', right: 12, top: 12, zIndex: 3, padding: '3px 8px', borderRadius: 999, background: '#1e293b', color: '#e2e8f0', fontSize: 11 }}>+{extra} more</div>
        ) : null}
      </div>
      <aside style={{ width: '30%', height: '100%', display: 'flex', flexDirection: 'column', padding: 12, boxSizing: 'border-box', background: '#f8fafc' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
          <h2 style={{ margin: 0, fontSize: 14, fontWeight: 700 }}>CDP Neighbors</h2>
          <span data-testid="cdp-status" style={{ borderRadius: 999, padding: '2px 8px', fontSize: 11, fontWeight: 700, color: active ? '#14532d' : '#334155', background: active ? '#22c55e' : '#cbd5e1' }}>{active ? 'Active' : 'No data'}</span>
        </div>
        {device.neighborNote ? <p style={{ margin: '8px 0 0', fontSize: 12, color: '#64748b' }}>{device.neighborNote}</p> : null}
        {!active && !device.neighborNote ? <p style={{ margin: '8px 0 0', fontSize: 12, color: '#64748b' }}>No Netdisco LLDP or CDP neighbours were returned.</p> : null}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 10 }}>
          <KindIcon kind={current ? neighbourKind(current.row) : 'self'} glow={!current} />
          <div>
            <div style={{ fontSize: 13, fontWeight: 700 }}>{current ? (current.row.remoteName || current.row.remoteAddress || 'unknown') : device.hostname}</div>
            <div style={{ fontSize: 11, color: '#64748b' }}>{current ? (current.row.remoteAddress || '—') : device.mgmtIp}</div>
            <div style={{ fontSize: 11, color: '#64748b' }}>{current ? (current.row.remotePlatform || '—') : model}</div>
          </div>
        </div>
        {current?.row.netboxId ? (
          <Link href={devicePath(current.row.netboxId, 'generic')} style={{ marginTop: 6, fontSize: 12, fontWeight: 650 }}>Open device</Link>
        ) : null}
        <div role="tablist" aria-label="CDP neighbour details" style={{ display: 'flex', gap: 6, marginTop: 10 }}>
          {([
            ['info', 'CDP Info'],
            ['list', `Neighbors (${neighbors.length})`],
            ['interfaces', 'Interfaces'],
          ] as const).map(([id, label]) => (
            <button key={id} type="button" role="tab" aria-selected={tab === id} onClick={() => setTab(id)} style={{ border: 0, borderBottom: tab === id ? '2px solid #0f172a' : '2px solid transparent', background: 'transparent', padding: '4px 2px', fontSize: 11, fontWeight: 650, cursor: 'pointer' }}>{label}</button>
          ))}
        </div>
        <div style={{ marginTop: 8, overflow: 'auto', minHeight: 0, flex: 1 }}>
          {tab === 'info' ? (
            <dl style={{ margin: 0 }}>
              <Fact label="Device ID" value={dash(current ? (current.row.remoteDeviceId || current.row.remoteName) : device.hostname)} />
              <Fact label="Platform" value={dash(current ? current.row.remotePlatform : model)} />
              <Fact label="Capabilities" value={dash(current ? current.row.remoteCapabilities : device.role)} />
              <Fact label="Local port" value={dash(current?.row.localPort)} />
              <Fact label="Port ID" value={dash(current?.row.remotePort)} />
              <Fact label="TTL / last seen" value={dash(current?.row.lastSeen)} />
              <Fact label="Source" value={current ? sourceLabel(current.row) : '—'} />
            </dl>
          ) : null}
          {tab === 'list' ? (
            neighbors.length === 0 ? (
              <p style={{ fontSize: 12, color: '#64748b' }}>{device.neighborNote || 'No Netdisco LLDP or CDP neighbours were returned.'}</p>
            ) : (
              <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
                {neighbors.map((row, index) => {
                  const key = neighbourKey(row, index);
                  const known = neighbourKnown(row);
                  return (
                    <li key={key}>
                      <button type="button" onClick={() => { setSelected(key); setTab('info'); }} style={{ display: 'flex', width: '100%', gap: 6, alignItems: 'center', border: 0, background: selected === key ? '#e2e8f0' : 'transparent', padding: '4px 2px', cursor: 'pointer', textAlign: 'left', fontSize: 12 }}>
                        <span style={{ width: 8, height: 8, borderRadius: 99, background: known ? '#22c55e' : '#94a3b8', flexShrink: 0 }} />
                        <span>{row.remoteName || row.remoteAddress || 'unknown'} ({neighbourKind(row)})</span>
                      </button>
                    </li>
                  );
                })}
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
    return <p className="mt-1 text-sm text-muted-foreground">NetBox did not return interfaces or IP addresses for this device.</p>;
  }
  return (
    <ul className="mt-2 max-h-72 space-y-1 overflow-auto font-mono-data text-xs">
      {(device.interfaces ?? []).map((row) => (
        <li key={row.name}>
          {portNameLine(row)}
          {row.description ? ` · ${row.description}` : ''}
          {' · '}{row.enabled ? 'enabled' : 'disabled'} · {row.type || '—'}
        </li>
      ))}
      {(device.addresses ?? []).slice(0, 20).map((row) => (
        <li key={row.address}>{row.address}{row.interface ? ` on ${row.interface}` : ''}</li>
      ))}
    </ul>
  );
}
