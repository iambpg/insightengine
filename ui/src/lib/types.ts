export type PortState = 'up' | 'down' | 'warning' | 'fault' | 'disabled';
export type PortType = 'RJ45' | 'SFP' | 'SFP+' | 'QSFP' | 'MGMT' | 'CONSOLE' | 'USB';
export type DeviceHealth = 'healthy' | 'warning' | 'critical' | 'unreachable';

export type FormFactor =
  | 'access-switch-24' |'access-switch-48' |'switch-stack' |'ceiling-ap' |'wireless-controller' |'firewall' |'branch-router' |'modular-chassis' |'generic';

export interface PortNeighbour {
  device: string;
  port: string;
}

export interface PortInfo {
  id: string;
  name: string;
  type: PortType;
  speed: string;
  state: PortState;
  utilisation: number;
  errors: number;
  neighbour?: PortNeighbour;
  poe?: boolean;
  label?: string;
}

export interface RadioInfo {
  id: string;
  band: '2.4 GHz' | '5 GHz' | '6 GHz';
  channel: number;
  state: PortState;
  clients: number;
  utilisation: number;
  standard?: string;
  channelWidth?: string;
  txPower?: string;
  noiseFloor?: string;
  avgRssi?: string;
  retryRate?: number;
  ssids?: string[];
  throughput?: string;
}

export interface StackMember {
  id: string;
  number: number;
  health: 'healthy' | 'warning' | 'fault';
  note: string;
  ports: PortInfo[];
  psuFault?: boolean;
  fanWarning?: boolean;
}

export interface ChassisModule {
  id: string;
  kind: 'supervisor' | 'linecard' | 'fan' | 'psu';
  slot: string;
  label: string;
  state: PortState;
  ports: PortInfo[];
}

export interface FaceplateDevice {
  form_factor: FormFactor;
  role: string;
  hostname?: string;
  ports?: PortInfo[];
  members?: StackMember[];
  modules?: ChassisModule[];
  radios?: RadioInfo[];
  apState?: PortState;
  moduleSlotFilled?: boolean;
  model?: string;
  modelName?: string;
}

export interface DeviceRow {
  id: string;
  hostname: string;
  role: string;
  site: string;
  siteId: string;
  mgmtIp: string;
  modelFamily: string;
  health: DeviceHealth;
  portsUp: number;
  portsTotal: number;
  portsWarn: number;
  portsFault: number;
  uptime: string;
  lastPoll: string;
  formFactor: FormFactor;
}

export interface SiteRow {
  id: string;
  name: string;
  region: string;
  city: string;
  deviceCount: number;
  health: DeviceHealth;
  alerts: number;
  lastDiscovery: string;
}

/** Device Netdisco found that is not in NetBox. Matches GET /api/v1/discovery/unapproved. */
export interface DiscoveredDevice {
  id: string;
  ip: string;
  hostname?: string;
  sysName?: string;
  vendor?: string;
  model?: string;
  platform?: string;
  sysDescr?: string;
  firstSeen: string;
  lastSeen: string;
  suggested: {
    role?: string;
    site?: string;
    platform?: string;
  };
}

export interface IssueItem {
  id: string;
  severity: 'critical' | 'warning' | 'info';
  title: string;
  detail: string;
  since: string;
  target: string;
}

export interface HealthCheck {
  id: string;
  name: string;
  result: 'pass' | 'warn' | 'fail';
  detail: string;
}

export interface HardwareItem {
  id: string;
  name: string;
  kind: 'power' | 'fan' | 'temp' | 'cpu' | 'memory' | 'storage';
  status: 'ok' | 'warn' | 'fail';
  value: string;
  detail: string;
}

export interface SeriesPoint {
  t: number;
  label: string;
  inBps: number | null;
  outBps: number | null;
  errors: number | null;
  util: number | null;
}

export interface DeviceInterfaceRow {
  name: string;
  type: string;
  enabled: boolean;
  mac: string;
  description: string;
}

export interface DeviceAddressRow {
  address: string;
  interface: string;
  status: string;
}

export interface DeviceNeighbor {
  localPort: string;
  remoteName: string;
  remotePort: string;
  remoteAddress: string;
  protocol: string;
}

export interface DeviceBackup {
  available: boolean;
  reason?: string;
  status?: string;
  at?: string;
  config?: string;
}

export interface DeviceSource {
  name: string;
  ok: boolean;
  detail: string;
}

export interface DeviceDetailData {
  id: string;
  hostname: string;
  role: string;
  site: string;
  siteId?: string;
  mgmtIp: string;
  modelFamily: string;
  health: DeviceHealth;
  uptime: string;
  lastPoll: string;
  firmware: string;
  serialMasked: string;
  faceplate: FaceplateDevice;
  issues: IssueItem[];
  checks: HealthCheck[];
  hardware: HardwareItem[];
  checkRunAt: string;
  interfaces?: DeviceInterfaceRow[];
  addresses?: DeviceAddressRow[];
  neighbors?: DeviceNeighbor[];
  backup?: DeviceBackup;
  history?: SeriesPoint[];
  sources?: DeviceSource[];
}

export interface LauncherApp {
  id: string;
  name: string;
  url: string;
  status: 'up' | 'down' | 'unknown';
}

export interface LauncherCatalog {
  host: string;
  role: string;
  apps: LauncherApp[];
}

export interface CliCommandSpec {
  id: string;
  group: string;
  label: string;
  command: string;
}

export interface CliCatalog {
  platform: string;
  platformLabel: string;
  commands: CliCommandSpec[];
  credentialsConfigured: boolean;
  hostname: string;
  mgmtIp: string;
  message: string;
}

export interface WebhookDelivery {
  id: string;
  at: string;
  alertname: string;
  status: number;
  durationMs: number;
}

export type RoleName = 'Administrator' | 'Engineer' | 'Operator' | 'Read-only';

export interface UserRow {
  id: string;
  name: string;
  email: string;
  role: RoleName;
  lastActive: string;
  mfa: boolean;
}

export type AlertSeverity = 'critical' | 'warning' | 'info';
export type AlertStatus = 'open' | 'acknowledged';

export interface AlertItem {
  id: string;
  severity: AlertSeverity;
  title: string;
  detail: string;
  site: string;
  siteId: string;
  deviceHostname: string;
  formFactor: FormFactor;
  category: string;
  raisedAt: string;
  ageMinutes: number;
  status: AlertStatus;
  acknowledgedBy?: string;
  acknowledgedAt?: string;
}