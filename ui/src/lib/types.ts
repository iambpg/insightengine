export type PortState = 'up' | 'down' | 'warning' | 'fault' | 'disabled' | 'unknown';
export type PortType = 'RJ45' | 'SFP' | 'SFP+' | 'QSFP' | 'MGMT' | 'CONSOLE' | 'USB';
export type DeviceHealth = 'healthy' | 'warning' | 'critical' | 'unreachable';

export type FormFactor =
  | 'access-switch-24' |'access-switch-48' |'switch-stack' |'ceiling-ap' |'wireless-controller' |'firewall' |'branch-router' |'modular-chassis' |'generic';

export interface PortNeighbour {
  device: string;
  port: string;
  deviceId?: string;
  source?: string;
}

export interface PortInfo {
  id: string;
  name: string;
  type: PortType;
  speed: string;
  state: PortState;
  utilisation: number;
  errors: number;
  inBps?: number;
  outBps?: number;
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
  snmpAt?: string;
  snmpMissing?: boolean;
  moduleSlotFilled?: boolean;
  model?: string;
  modelName?: string;
  partNumber?: string;
  slug?: string;
  manufacturer?: string;
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
  status?: string;
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

/** One cause of a device health badge. The badge is the worst of these items. */
export interface HealthCause {
  id: string;
  severity: 'critical' | 'warning' | 'info';
  title: string;
  detail: string;
  value: string;
  threshold: string;
  source: string;
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

export interface HealthGroup {
  id: string;
  label: string;
  supported: boolean;
  status: 'ok' | 'warn' | 'fail' | 'unsupported' | 'unknown';
  value: string;
  detail: string;
}

export interface HealthInterfaceRow {
  name: string;
  ifIndex: string;
  utilization: number | null;
  dropsRate: number | null;
  errorsRate: number | null;
  criticalPath: boolean;
}

export interface AccessPointRadio {
  slot: string;
  channel: number | string | null;
  utilization: number | null;
  clients: number | null;
  noise?: number | null;
  interference?: number | null;
  txPowerDbm?: number | null;
  width?: number | null;
  rssiAvg?: number | null;
  snrAvg?: number | null;
  band?: string;
}

export interface AccessPointSsid {
  ssid: string;
  radio: string;
  band: string;
  clients: number | null;
}

export interface AccessPointEvent {
  t: number;
  what: string;
  ap: string;
  radio: string;
  from: string | number;
  to: string | number;
}

export interface AccessPointRow {
  name: string;
  mac: string;
  wlc: string;
  site: string;
  status: string;
  clients: number | null;
  uptimeSeconds: number | null;
  radios: AccessPointRadio[];
  model?: string;
  serial?: string;
  ip?: string;
  location?: string;
  ios?: string;
  mode?: string;
  siteTag?: string;
  policyTag?: string;
  rfTag?: string;
  neighborSwitch?: string;
  neighborPort?: string;
  netboxSite?: string;
  inNetbox?: boolean;
  netboxId?: string;
  suggestedSite?: string;
  ssids?: AccessPointSsid[];
  rssiAvg?: number | null;
  snrAvg?: number | null;
}

export interface DeviceHealthPanel {
  profile: string;
  profileLabel: string;
  groups: HealthGroup[];
  interfacesSupported: boolean;
  interfaces: HealthInterfaceRow[];
  interfacesNote: string;
  wlc: { joinedAps: number | null; clients: number | null; note: string } | null;
  accessPoint: {
    note: string;
    status: string;
    clients: number | null;
    uptimeSeconds: number | null;
    radios: AccessPointRadio[];
    name?: string;
    wlc?: string;
    model?: string;
    serial?: string;
    ip?: string;
    mac?: string;
    location?: string;
    ios?: string;
    mode?: string;
    siteTag?: string;
    neighborSwitch?: string;
    neighborPort?: string;
    ssids?: AccessPointSsid[];
  } | null;
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
  source?: string;
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

export interface InventorySide {
  vendor: string;
  model: string;
  serial: string;
  os: string;
  portCount: number;
}

export interface SourceComparison {
  netbox: InventorySide;
  netdisco: InventorySide;
  faceplateSource: 'netbox' | 'netdisco' | 'prometheus' | 'none' | string;
  differ: boolean;
}

export interface DeviceParentLink {
  id: string;
  hostname: string;
  parentInterface: string;
  uplinkInterface: string;
  formFactor?: string;
  parentDown?: boolean;
}

export interface HierarchyNode {
  id: string;
  hostname: string;
  role: string;
  mgmtIp: string;
  formFactor: string;
  root: boolean;
  parentId: string;
  parentHostname: string;
  parentInterface: string;
  uplinkInterface: string;
  hops: number | null;
  flagged: boolean;
  reason: string;
  wlc: string;
  parentDown: boolean;
  differs: boolean;
  children: DeviceParentLink[];
}

export interface HierarchyReport {
  autoApply: boolean;
  roots: string[];
  flagged: string[];
  nodes: HierarchyNode[];
  degraded?: string[];
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
  parent?: DeviceParentLink | null;
  children?: DeviceParentLink[];
  wlc?: string;
  unparented?: boolean;
  parentDown?: boolean;
  healthItems?: HealthCause[];
  inNetbox?: boolean;
  status?: string;
  netdiscoOnly?: boolean;
  uptime: string;
  lastPoll: string;
  firmware: string;
  serialMasked: string;
  faceplate: FaceplateDevice;
  issues: IssueItem[];
  checks: HealthCheck[];
  hardware: HardwareItem[];
  healthPanel?: DeviceHealthPanel;
  checkRunAt: string;
  interfaces?: DeviceInterfaceRow[];
  addresses?: DeviceAddressRow[];
  neighbors?: DeviceNeighbor[];
  neighborNote?: string;
  backup?: DeviceBackup;
  history?: SeriesPoint[];
  sources?: DeviceSource[];
  comparison?: SourceComparison;
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

export type RoleName = 'Administrator' | 'Engineer' | 'Operator' | 'Read-only' | 'Admin' | 'Viewer';

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
  deviceId?: string;
  formFactor: FormFactor;
  category: string;
  raisedAt: string;
  ageMinutes: number;
  status: AlertStatus;
  acknowledgedBy?: string;
  acknowledgedAt?: string;
}