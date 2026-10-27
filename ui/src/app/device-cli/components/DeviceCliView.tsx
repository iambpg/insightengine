'use client';

import React, { useEffect, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import Icon from '@/components/ui/AppIcon';
import ExampleDataBanner from '@/components/ui/ExampleDataBanner';
import { HealthBadge } from '@/components/ui/Badge';
import { Skeleton } from '@/components/ui/Skeleton';
import { api } from '@/lib/apiClient';
import { isMockMode } from '@/lib/apiMode';
import { FACEPLATE_SAMPLES } from '@/lib/mockData';
import type { DeviceDetailData } from '@/lib/types';

interface CliCommand {
  id: string;
  label: string;
  command: string;
  icon: string;
  danger?: boolean;
}

interface CliGroup {
  title: string;
  commands: CliCommand[];
}

interface HistoryEntry {
  id: number;
  command: string;
  output: string;
  time: string;
}

const GROUPS: CliGroup[] = [
  {
    title: 'System',
    commands: [
      { id: 'ver', label: 'Show version', command: 'show version', icon: 'InformationCircleIcon' },
      { id: 'inv', label: 'Show inventory', command: 'show inventory', icon: 'CubeIcon' },
      { id: 'env', label: 'Show environment', command: 'show environment all', icon: 'BoltIcon' },
      { id: 'cpu', label: 'CPU and memory', command: 'show processes cpu | memory', icon: 'CpuChipIcon' },
      { id: 'log', label: 'Show logs', command: 'show logging | last 20', icon: 'DocumentTextIcon' },
    ],
  },
  {
    title: 'Interfaces',
    commands: [
      { id: 'ifb', label: 'Interface summary', command: 'show ip interface brief', icon: 'Squares2X2Icon' },
      { id: 'ifs', label: 'Interface status', command: 'show interfaces status', icon: 'SignalIcon' },
      { id: 'err', label: 'Interface errors', command: 'show interfaces counters errors', icon: 'ExclamationTriangleIcon' },
      { id: 'poe', label: 'PoE status', command: 'show power inline', icon: 'BoltIcon' },
    ],
  },
  {
    title: 'Layer 2 and 3',
    commands: [
      { id: 'vlan', label: 'VLANs', command: 'show vlan brief', icon: 'ListBulletIcon' },
      { id: 'mac', label: 'MAC table', command: 'show mac address-table', icon: 'TableCellsIcon' },
      { id: 'stp', label: 'Spanning tree', command: 'show spanning-tree summary', icon: 'ShareIcon' },
      { id: 'rt', label: 'Routing table', command: 'show ip route', icon: 'ArrowsRightLeftIcon' },
      { id: 'nb', label: 'LLDP neighbors', command: 'show lldp neighbors', icon: 'GlobeAltIcon' },
    ],
  },
  {
    title: 'Connectivity',
    commands: [
      { id: 'pgw', label: 'Ping gateway', command: 'ping 10.22.14.1', icon: 'ArrowUpTrayIcon' },
      { id: 'pdns', label: 'Ping DNS', command: 'ping 10.22.0.53', icon: 'ArrowUpTrayIcon' },
      { id: 'tr', label: 'Traceroute core', command: 'traceroute 10.22.0.1', icon: 'MapPinIcon' },
    ],
  },
];

function buildOutput(id: string, d: DeviceDetailData): string {
  const h = d.hostname;
  switch (id) {
    case 'ver':
      return `${d.modelFamily}\nSoftware version : ${d.firmware}\nHostname         : ${h}\nUptime           : ${d.uptime}\nSerial number    : ${d.serialMasked}\nManagement IP    : ${d.mgmtIp}\nLast reload      : power-on`;
    case 'inv':
      return `NAME: "Chassis"   DESCR: "${d.modelFamily}"\nPID: ${d.modelFamily.replace(/\s+/g, '-').toUpperCase()}   SN: ${d.serialMasked}\nNAME: "Power Supply 1"   DESCR: "AC 715W"   SN: LIT••••••3A\nNAME: "Power Supply 2"   DESCR: "AC 715W"   SN: LIT••••••9C\nNAME: "Fan Tray"   DESCR: "Hot-swap fan tray (3 fans)"`;
    case 'env':
      return `PSU 1      : OK     (715W, 38% load)\nPSU 2      : OK     (715W, 36% load)\nFAN 1      : OK     (6120 RPM)\nFAN 2      : WARN   (2890 RPM, below 50%)\nFAN 3      : OK     (6080 RPM)\nTemp inlet : 31 C   (limit 45 C)\nTemp core  : 47 C   (limit 70 C)`;
    case 'cpu':
      return `CPU utilisation  5 sec: 12%   1 min: 14%   5 min: 13%\nMemory total     : 4096 MB\nMemory used      : 2412 MB (59%)\nMemory free      : 1684 MB\nTop process      : IP Input   (3.2%)\nFlash free       : 612 MB of 1024 MB`;
    case 'log':
      return `Oct 27 16:39:52 ${h} %LINK-3-UPDOWN: Interface Gi1/0/17, changed state to down\nOct 27 16:39:58 ${h} %LINK-3-UPDOWN: Interface Gi1/0/17, changed state to up\nOct 27 16:31:04 ${h} %ENVMON-4-FAN_WARN: Fan 2 speed below threshold\nOct 27 16:12:40 ${h} %PM-4-ERR_DISABLE: crc-error detected on Gi1/0/22\nOct 27 15:58:11 ${h} %SYS-5-CONFIG_I: Configured from console by admin\nOct 27 15:20:33 ${h} %STP-6-ROOT_CHANGE: Root port changed to Te1/1/1`;
    case 'ifb':
      return `Interface        IP-Address      Status   Protocol\nVlan1            unassigned      up       up\nVlan10           10.22.10.2      up       up\nVlan99 (mgmt)    ${d.mgmtIp}   up       up\nGi1/0/1          unassigned      up       up\nGi1/0/9          unassigned      up       up\nGi1/0/22         unassigned      up       up\nTe1/1/1          unassigned      up       up\nTe1/1/2          unassigned      down     down`;
    case 'ifs':
      return `Port       Name          Status       Vlan  Duplex  Speed  Type\nGi1/0/1    uplink-core   connected    trunk a-full  a-1000 10/100/1000BaseTX\nGi1/0/9    desk-114      connected    10    a-full  a-1000 10/100/1000BaseTX\nGi1/0/17   ap-hall       connected    20    a-full  a-1000 10/100/1000BaseTX\nGi1/0/22   desk-131      err-disabled 10    auto    auto   10/100/1000BaseTX\nTe1/1/1    to-dist-a     connected    trunk full    10G    SFP-10GBase-SR\nTe1/1/2    to-dist-b     notconnect   1     auto    auto   Not Present`;
    case 'err':
      return `Port       Align-Err  FCS-Err  Xmit-Err  Rcv-Err  UnderSize\nGi1/0/9            0     1842         0     1842          0\nGi1/0/17           0      311         0      311          0\nGi1/0/22           0     6620         0     6620          0\nTe1/1/1            0        0         0        0          0`;
    case 'poe':
      return `Available: 740.0W   Used: 286.4W   Remaining: 453.6W\nInterface  Admin  Oper  Power(W)  Device        Class\nGi1/0/3    auto   on    15.4      Cisco IP Phone  3\nGi1/0/17   auto   on    22.8      AP ceiling      4\nGi1/0/24   auto   fault  0.0      n/a             n/a`;
    case 'vlan':
      return `VLAN Name           Status    Ports\n1    default        active    Gi1/0/30-48\n10   users          active    Gi1/0/2-16\n20   wireless-mgmt  active    Gi1/0/17-20\n30   voice          active    Gi1/0/21-29\n99   management     active    Te1/1/1-2`;
    case 'mac':
      return `Vlan  Mac Address       Type     Ports\n10    a4bb.6d12.3c01    DYNAMIC  Gi1/0/9\n10    a4bb.6d12.3c4e    DYNAMIC  Gi1/0/11\n20    00f6.6350.19a2    DYNAMIC  Gi1/0/17\n30    0021.a0c4.7f10    DYNAMIC  Gi1/0/3\n99    5c5a.c7b1.2290    STATIC   Vlan99\nTotal Mac Addresses for this criterion: 5`;
    case 'stp':
      return `Switch is in rapid-pvst mode\nRoot bridge for: none\nName        Blocking Listening Learning Forwarding STP Active\nVLAN0010           0         0        0         9          9\nVLAN0020           0         0        0         5          5\nVLAN0099           0         0        0         2          2`;
    case 'rt':
      return `Gateway of last resort is 10.22.14.1 to network 0.0.0.0\nS*   0.0.0.0/0 [1/0] via 10.22.14.1\nC    10.22.10.0/24 is directly connected, Vlan10\nC    10.22.14.0/24 is directly connected, Vlan99\nO    10.22.0.0/16 [110/20] via 10.22.14.1, 3d02h, Vlan99`;
    case 'nb':
      return `Device ID        Local Intf  Hold-time  Capability  Port ID\ncore-rtm01-01    Te1/1/1     112        R,B         Te1/0/1\nap-rtm01-07      Gi1/0/17    94         W           eth0\nphone-rtm-0031   Gi1/0/3     120        T           port1\nTotal entries displayed: 3`;
    case 'pgw':
      return `Sending 5, 100-byte ICMP Echos to 10.22.14.1, timeout is 2 seconds:\n!!!!!\nSuccess rate is 100 percent (5/5), round-trip min/avg/max = 1/1/2 ms`;
    case 'pdns':
      return `Sending 5, 100-byte ICMP Echos to 10.22.0.53, timeout is 2 seconds:\n!!!!!\nSuccess rate is 100 percent (5/5), round-trip min/avg/max = 2/3/5 ms`;
    case 'tr':
      return `Tracing the route to 10.22.0.1\n  1  10.22.14.1   1 msec  1 msec  1 msec\n  2  10.22.0.1     3 msec  2 msec  3 msec`;
    default:
      return '% Unknown command';
  }
}

const ALL_COMMANDS: CliCommand[] = GROUPS.flatMap((g) => g.commands);

const IPV4 = /^(\d{1,3})(\.\d{1,3}){3}$/;

function normalize(s: string): string {
  return s.trim().replace(/\s+/g, ' ').toLowerCase();
}

function resolveTyped(raw: string, d: DeviceDetailData): string | null {
  const typed = normalize(raw);
  const exact = ALL_COMMANDS.find((c) => normalize(c.command) === typed);
  if (exact) return buildOutput(exact.id, d);

  const parts = raw.trim().split(/\s+/);
  const verb = parts[0]?.toLowerCase();
  const target = parts[1];

  if (verb === 'ping' && target) {
    if (!IPV4.test(target)) return `% Unrecognized host or address: ${target}`;
    return `Sending 5, 100-byte ICMP Echos to ${target}, timeout is 2 seconds:\n!!!!!\nSuccess rate is 100 percent (5/5), round-trip min/avg/max = 1/2/4 ms`;
  }
  if ((verb === 'traceroute' || verb === 'tracert') && target) {
    if (!IPV4.test(target)) return `% Unrecognized host or address: ${target}`;
    return `Tracing the route to ${target}\n  1  10.22.14.1   1 msec  1 msec  1 msec\n  2  ${target}   3 msec  2 msec  3 msec`;
  }
  if (typed === 'show clock') {
    const n = new Date();
    return `${[n.getHours(), n.getMinutes(), n.getSeconds()].map((x) => String(x).padStart(2, '0')).join(':')} UTC`;
  }
  if (typed === 'show hostname' || typed === 'hostname') return d.hostname;
  if (typed === 'show ip' || typed === 'show management-ip') return d.mgmtIp;
  if (typed === 'help' || typed === '?') {
    return `Available commands:\n${ALL_COMMANDS.map((c) => `  ${c.command}`).join('\n')}\n  ping <ip>\n  traceroute <ip>\n  show clock\n  clear      (clear the screen)\n  help       (show this list)`;
  }
  if (typed.startsWith('show ') || typed.startsWith('ping') || typed.startsWith('traceroute')) {
    return `% Incomplete or unsupported command: "${raw.trim()}"\nType "help" to list the supported commands.`;
  }
  return null;
}

export default function DeviceCliView() {
  const [form, setForm] = useState<string>('switch-stack');
  const [deviceKey, setDeviceKey] = useState<string>('switch-stack');
  const [device, setDevice] = useState<DeviceDetailData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [runningId, setRunningId] = useState<string | null>(null);
  const [runningLabel, setRunningLabel] = useState<string>('');
  const [copied, setCopied] = useState(false);
  const [input, setInput] = useState('');
  const [recall, setRecall] = useState<string[]>([]);
  const [recallIdx, setRecallIdx] = useState<number>(-1);
  const counter = useRef(0);
  const screenRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const q = params.get('form');
    const id = params.get('id');
    if (q && Object.keys(FACEPLATE_SAMPLES).includes(q)) setForm(q);
    if (!isMockMode() && id) setDeviceKey(id);
    else if (q) setDeviceKey(q);
  }, []);

  useEffect(() => {
    let cancelled = false;
    setDevice(null);
    setError(null);
    setHistory([]);
    api
      .getDevice(deviceKey)
      .then((d) => !cancelled && setDevice(d))
      .catch(() => !cancelled && setError('Failed to connect to this device. Check your connection and try again.'));
    return () => {
      cancelled = true;
    };
  }, [deviceKey]);

  useEffect(() => {
    const el = screenRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [history, runningId]);

  const prompt = useMemo(() => (device ? `${device.hostname}#` : 'device#'), [device]);

  const execute = (commandText: string, produce: () => string) => {
    if (!device || runningId) return;
    setRunningId('run');
    setRunningLabel(commandText);
    setTimeout(() => {
      counter.current += 1;
      const now = new Date();
      const time = [now.getHours(), now.getMinutes(), now.getSeconds()].map((n) => String(n).padStart(2, '0')).join(':');
      setHistory((h) => [...h, { id: counter.current, command: commandText, output: produce(), time }]);
      setRunningId(null);
      setRunningLabel('');
      inputRef.current?.focus();
    }, 450);
  };

  const run = (cmd: CliCommand) => {
    if (!device) return;
    execute(cmd.command, () => buildOutput(cmd.id, device));
  };

  const submitTyped = () => {
    const raw = input.trim();
    if (!raw || !device || runningId) return;
    setRecall((r) => [...r, raw]);
    setRecallIdx(-1);
    setInput('');
    const typed = normalize(raw);
    if (typed === 'clear' || typed === 'cls') {
      setHistory([]);
      return;
    }
    const out = resolveTyped(raw, device);
    execute(raw, () => out ?? `% Unknown command: "${raw}"\nType "help" to list the supported commands.`);
  };

  const onInputKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      submitTyped();
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      if (recall.length === 0) return;
      const next = recallIdx === -1 ? recall.length - 1 : Math.max(0, recallIdx - 1);
      setRecallIdx(next);
      setInput(recall[next]);
    } else if (e.key === 'ArrowDown') {
      e.preventDefault();
      if (recallIdx === -1) return;
      const next = recallIdx + 1;
      if (next >= recall.length) {
        setRecallIdx(-1);
        setInput('');
      } else {
        setRecallIdx(next);
        setInput(recall[next]);
      }
    } else if (e.key === 'l' && e.ctrlKey) {
      e.preventDefault();
      setHistory([]);
    }
  };

  const copyAll = () => {
    const text = history.map((h) => `${prompt} ${h.command}\n${h.output}`).join('\n\n');
    navigator.clipboard?.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1200);
    });
  };

  if (error) {
    return (
      <div role="alert" className="flex items-center justify-between gap-3 rounded-md border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
        <span className="flex items-center gap-2"><Icon name="ExclamationCircleIcon" size={18} />{error}</span>
        <button type="button" onClick={() => setForm((f) => f)} className="rounded-md border border-destructive/40 px-3 py-1 text-xs font-semibold">Retry</button>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <nav aria-label="Breadcrumb" className="flex items-center gap-1.5 px-1 text-xs text-muted-foreground">
        <Link href="/" className="hover:text-foreground hover:underline">Devices</Link>
        <Icon name="ChevronRightIcon" size={12} />
        <Link href={`/device-detail?form=${form}`} className="font-mono-data hover:text-foreground hover:underline">{device?.hostname ?? '…'}</Link>
        <Icon name="ChevronRightIcon" size={12} />
        <span className="text-foreground">Device CLI</span>
      </nav>

      <header className="rounded-none border-x-0 border-y border-border bg-card p-4 shadow-card">
        {device ? (
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex flex-wrap items-center gap-3">
              <h1 className="font-mono-data text-xl font-semibold tracking-tight">{device.hostname}</h1>
              <HealthBadge health={device.health} />
              <span className="font-mono-data text-xs text-muted-foreground">{device.mgmtIp} · {device.modelFamily}</span>
              <span className="inline-flex items-center gap-1.5 rounded-full bg-success/15 px-2.5 py-0.5 text-xs font-semibold text-success">
                <span className="h-1.5 w-1.5 rounded-full bg-success" />Session open
              </span>
            </div>
            <Link
              href={`/device-detail?form=${form}`}
              className="inline-flex items-center gap-1.5 rounded-md border border-border bg-card px-3 py-2 text-sm font-medium transition-all hover:bg-muted active:scale-95"
            >
              <Icon name="ArrowLeftIcon" size={16} />Back to device
            </Link>
          </div>
        ) : (
          <Skeleton className="h-8 w-96" />
        )}
      </header>

      <div className="grid grid-cols-1 gap-3 xl:grid-cols-[320px_1fr]">
        <aside className="rounded-none border-x-0 border-y border-border bg-card shadow-card" aria-label="Predefined commands">
          <div className="border-b border-border px-4 py-2.5">
            <h2 className="text-base font-semibold">Commands</h2>
            <p className="text-xs text-muted-foreground">Click a button to run it on the device. Read-only checks.</p>
          </div>
          <div className="scroll-thin max-h-[560px] space-y-4 overflow-y-auto p-3">
            {GROUPS.map((g) => (
              <div key={`grp-${g.title}`}>
                <p className="label-caps mb-1.5 text-muted-foreground">{g.title}</p>
                <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2 xl:grid-cols-1">
                  {g.commands.map((c) => (
                    <button
                      key={`cmd-${c.id}`}
                      type="button"
                      disabled={!device || !!runningId}
                      onClick={() => run(c)}
                      title={c.command}
                      className="group flex items-center gap-2 rounded-md border border-border bg-card px-3 py-2 text-left text-sm transition-all hover:border-primary hover:bg-primary/5 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary"
                    >
                      <Icon name={runningLabel === c.command ? 'ArrowPathIcon' : c.icon} size={16} className={runningLabel === c.command ? 'animate-spin text-primary' : 'text-muted-foreground group-hover:text-primary'} />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate font-medium">{c.label}</span>
                        <span className="block truncate font-mono-data text-[11px] text-muted-foreground">{c.command}</span>
                      </span>
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </aside>

        <section className="flex min-w-0 flex-col overflow-hidden rounded-none border-x-0 border-y border-border bg-navy shadow-card" aria-label="Terminal">
          <div className="flex items-center justify-between gap-2 border-b border-navy-3 px-4 py-2">
            <div className="flex items-center gap-2 text-primary-foreground">
              <Icon name="CommandLineIcon" size={16} />
              <span className="font-mono-data text-xs">{device ? `${device.hostname} · ${device.mgmtIp}` : 'connecting…'}</span>
            </div>
            <div className="flex items-center gap-1.5">
              <button
                type="button"
                onClick={copyAll}
                disabled={history.length === 0}
                className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs text-down transition-colors hover:bg-navy-3 hover:text-primary-foreground disabled:opacity-40"
              >
                <Icon name={copied ? 'CheckIcon' : 'ClipboardIcon'} size={14} />{copied ? 'Copied' : 'Copy output'}
              </button>
              <button
                type="button"
                onClick={() => setHistory([])}
                disabled={history.length === 0}
                className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs text-down transition-colors hover:bg-navy-3 hover:text-primary-foreground disabled:opacity-40"
              >
                <Icon name="TrashIcon" size={14} />Clear
              </button>
            </div>
          </div>

          <div
            ref={screenRef}
            onClick={() => inputRef.current?.focus()}
            className="scroll-thin h-[720px] max-h-[calc(100vh-220px)] min-h-[520px] overflow-y-auto p-4 font-mono-data text-[13px] leading-relaxed text-primary-foreground"
            aria-live="polite"
          >
            {!device && <Skeleton className="h-5 w-64" />}
            {device && history.length === 0 && !runningId && (
              <div className="text-down">
                <p>Connected to {device.hostname} ({device.mgmtIp}).</p>
                <p>Choose a command from the list or type your own below. Type &quot;help&quot; to see what is supported.</p>
              </div>
            )}
            {history.map((h) => (
              <div key={`out-${h.id}`} className="mb-4">
                <p>
                  <span className="text-cyan">{prompt}</span> <span className="font-semibold">{h.command}</span>
                  <span className="ml-3 text-[11px] text-down">{h.time}</span>
                </p>
                <pre className="mt-1 overflow-x-auto whitespace-pre text-primary-foreground/85">{h.output}</pre>
              </div>
            ))}
            {runningId && (
              <p>
                <span className="text-cyan">{prompt}</span>{' '}
                <span className="font-semibold">{runningLabel}</span>
                <span className="ml-2 animate-pulse text-down">running…</span>
              </p>
            )}
            {device && !runningId && (
              <div className="flex items-center gap-2">
                <label htmlFor="cli-input" className="shrink-0 text-cyan">{prompt}</label>
                <input
                  id="cli-input"
                  ref={inputRef}
                  type="text"
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={onInputKeyDown}
                  autoComplete="off"
                  autoCapitalize="off"
                  autoCorrect="off"
                  spellCheck={false}
                  placeholder="type a command, e.g. show version"
                  aria-label="Type a command and press Enter"
                  className="min-w-0 flex-1 border-0 bg-transparent p-0 font-mono-data text-[13px] font-semibold text-primary-foreground caret-cyan outline-none placeholder:font-normal placeholder:text-down/60 focus:ring-0"
                />
              </div>
            )}
          </div>
        </section>
      </div>

      <ExampleDataBanner text="Command output is simulated example data. No live connection is made to the device." />
    </div>
  );
}
