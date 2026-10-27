import type { AppGroup, ContainerState, FileLanguage, SettingsAction } from '@/lib/contract';
import type { RoleName } from '@/lib/types';

const EDITORS: RoleName[] = ['Administrator', 'Engineer'];
const ADMINS: RoleName[] = ['Administrator'];

export interface CatalogFile {
  id: string;
  path: string;
  label: string;
  language: FileLanguage;
  editable: boolean;
  readOnlyReason?: string;
  hasSecrets: boolean;
  withheld?: boolean;
  adminOnly?: boolean;
  content: string;
}

export interface CatalogApp {
  id: string;
  name: string;
  description: string;
  group: AppGroup;
  service: string;
  state: ContainerState;
  health?: string;
  uptimeSeconds?: number;
  version?: string;
  uiUrl?: string;
  lastReloadAt?: string | null;
  lastError?: string | null;
  actions: SettingsAction[];
  files: CatalogFile[];
}

const reload = (label = 'Reload'): SettingsAction => ({
  id: 'reload',
  label,
  kind: 'reload',
  dangerous: false,
  roles: EDITORS,
});
const restart = (): SettingsAction => ({
  id: 'restart',
  label: 'Restart',
  kind: 'restart',
  dangerous: true,
  roles: ADMINS,
});
const validateAll = (): SettingsAction => ({
  id: 'validate-all',
  label: 'Validate all',
  kind: 'validate',
  dangerous: false,
  roles: EDITORS,
});
const link = (appId: string, label: string): SettingsAction => ({
  id: `link:${appId}`,
  label,
  kind: 'link',
  dangerous: false,
  roles: EDITORS,
});

const PROMETHEUS_YML = `# InsightEngine Prometheus. Scrape jobs come from NetBox http_sd and static exporters.
global:
  scrape_interval: 30s
  evaluation_interval: 30s
  external_labels:
    stack: insightengine

rule_files:
  - /etc/prometheus/rules/insightengine.yml

scrape_configs:
  - job_name: prometheus
    metrics_path: /metrics
    scrape_interval: 30s
    static_configs:
      - targets:
          - localhost:9090
  - job_name: snmp
    metrics_path: /snmp
    scrape_interval: 60s
    static_configs:
      - targets:
          - snmp-exporter-ntt:9116
    params:
      module:
        - if_mib
      auth:
        - public_v2
  - job_name: blackbox-icmp
    metrics_path: /probe
    scrape_interval: 30s
    static_configs:
      - targets:
          - 10.22.14.17
          - 10.22.14.61
    relabel_configs:
      - source_labels: [__address__]
        target_label: __param_target
      - target_label: __address__
        replacement: blackbox-exporter-ntt:9115
  - job_name: netbox-http-sd
    metrics_path: /snmp
    scrape_interval: 60s
    http_sd_configs:
      - url: http://netbox-ntt:8080/api/plugins/insightengine/prometheus-sd/
`;

const RULES_YML = `groups:
  - name: insightengine
    rules:
      - alert: DeviceDown
        expr: up == 0
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "{{ $labels.instance }} is not responding"
      - alert: PortErrors
        expr: rate(ifInErrors[5m]) > 5
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Input errors on {{ $labels.ifName }}"
`;

const ALERTMANAGER_YML = `route:
  receiver: insightengine
  group_by:
    - alertname
    - instance
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 4h
  routes:
    - matchers:
        - severity = critical
      receiver: insightengine-critical

receivers:
  - name: insightengine
    webhook_configs:
      - url: http://ie-config-ntt:8080/api/v1/alerts/webhook
        send_resolved: true
  - name: insightengine-critical
    webhook_configs:
      - url: http://ie-config-ntt:8080/api/v1/alerts/webhook
        send_resolved: true
        http_config:
          bearer_token_file: /etc/alertmanager/ie-token
`;

const GENERATOR_YML = `# Source for snmp-generator. Secrets stay masked; edit them on the host, not here.
modules:
  if_mib:
    walk:
      - 1.3.6.1.2.1.2
      - 1.3.6.1.2.1.31
  system:
    walk:
      - 1.3.6.1.2.1.1

auths:
  public_v2:
    community: public
    version: 2
    security_level: noAuthNoPriv
  v3_ops:
    username: ops
    security_level: authPriv
    auth_protocol: SHA
    priv_protocol: AES
    auth_password: __SECRET__:snmp_v3_auth
    priv_password: __SECRET__:snmp_v3_priv
`;

const SNMP_YML = `# Sample of the generated snmp.yml. A full generator run is thousands of lines;
# the editor lazy-loads, folds, and searches so that file stays usable.
auths:
  public_v2:
    community: public
    version: 2
    security_level: noAuthNoPriv
  v3_ops:
    username: ops
    security_level: authPriv
    auth_protocol: SHA
    priv_protocol: AES
    password: __SECRET__:snmp_v3_auth
    priv_password: __SECRET__:snmp_v3_priv

modules:
  if_mib:
    walk:
      - 1.3.6.1.2.1.2
      - 1.3.6.1.2.1.31
    metrics:
      - name: ifInOctets
        oid: 1.3.6.1.2.1.2.2.1.10
        type: counter
        help: Incoming octets
        indexes:
          - labelname: ifIndex
            type: gauge
      - name: ifOutOctets
        oid: 1.3.6.1.2.1.2.2.1.16
        type: counter
        help: Outgoing octets
        indexes:
          - labelname: ifIndex
            type: gauge
  system:
    walk:
      - 1.3.6.1.2.1.1
    metrics:
      - name: sysUpTime
        oid: 1.3.6.1.2.1.1.3
        type: gauge
        help: Uptime in ticks
`;

const BLACKBOX_YML = `modules:
  icmp:
    prober: icmp
    timeout: 5s
  http_2xx:
    prober: http
    timeout: 5s
    http:
      valid_status_codes: [200]
      method: GET
`;

const TELEGRAF_CONF = `[agent]
  interval = "30s"
  round_interval = true
  hostname = "ie-host"

[[inputs.cpu]]
  percpu = false
  totalcpu = true

[[inputs.mem]]

[[inputs.disk]]
  ignore_fs = ["tmpfs", "devtmpfs"]

[[outputs.prometheus_client]]
  listen = ":9273"
`;

const GRAFANA_DS = `apiVersion: 1
datasources:
  - name: Prometheus
    type: prometheus
    access: proxy
    url: http://prometheus-ntt:9090
    isDefault: true
  - name: Loki
    type: loki
    access: proxy
    url: http://loki-ntt:3100
`;

const CADDYFILE = `{
	admin 127.0.0.1:2019
}

:80 {
	encode gzip
	handle /api/v1/* {
		reverse_proxy ie-config-ntt:8080
	}
	handle /setup/* {
		reverse_proxy ie-setup-ntt:8080
	}
	handle /healthz {
		reverse_proxy ie-ui-ntt:8080
	}
	handle {
		reverse_proxy ie-ui-ntt:8080
	}
}
`;

const NETBOX_PY = `# NetBox extra configuration served by ie-config.
# Masked secrets cannot be changed from this editor.
ALLOWED_HOSTS = ["netbox", "localhost"]
SECRET_KEY = "__SECRET__:netbox_secret_key"
BANNER_TOP = "InsightEngine inventory"
REMOTE_AUTH_ENABLED = False
`;

const NETDISCO_YML = `# Which devices Netdisco polls. Prefixes come from the netbox-sync app.
schedule: "0 */6 * * *"
workers: 4
snmp_auth: public_v2
timeout: 8
`;

const NETBOX_SYNC_YML = `# Prefixes Netdisco should walk.
# tag ie-scan: only NetBox prefixes carrying that tag.
# all-active: every active prefix.
mode: tag
tag: ie-scan
schedule: "0 */6 * * *"
`;

const ACTIVEPIECES_JSON = `{
  "worker": "insightengine",
  "webhookBase": "http://activepieces-ntt:80",
  "postgres": {
    "host": "postgres-ntt",
    "database": "activepieces"
  }
}
`;

const LOKI_YML = `auth_enabled: false
server:
  http_listen_port: 3100
common:
  path_prefix: /loki
  storage:
    filesystem:
      chunks_directory: /loki/chunks
      rules_directory: /loki/rules
  replication_factor: 1
schema_config:
  configs:
    - from: 2024-01-01
      store: tsdb
      object_store: filesystem
      schema: v13
      index:
        prefix: index_
        period: 24h
limits_config:
  retention_period: 168h
`;

const PROMTAIL_YML = `server:
  http_listen_port: 9080
clients:
  - url: http://loki-ntt:3100/loki/api/v1/push
scrape_configs:
  - job_name: syslog
    syslog:
      listen_address: 0.0.0.0:1514
      labels:
        job: syslog
`;

const OXIDIZED_YML = `---
username: backup
password: __SECRET__:oxidized_password
interval: 3600
use_syslog: false
debug: false
threads: 2
timeout: 20
retries: 3
prompt: !ruby/regexp /^([\\w.@-]+[#>]\\s?)$/
rest: 0.0.0.0:8888
vars: {}
groups: {}
models: {}
pid: /home/oxidized/.config/oxidized/pid
input:
  default: ssh
  debug: false
  ssh:
    secure: false
output:
  default: file
source:
  default: http
  http:
    url: http://netbox-ntt:8080/api/plugins/insightengine/oxidized/
    scheme: http
    map:
      name: hostname
      model: platform
      group: site
`;

const TRAPD_TOML = `[listen]
address = "0.0.0.0:162"
protocol = "udp"

[community]
# The engine keeps the community string in a secret file.
name = "__SECRET__:trap_community"

[forward]
loki_url = "http://loki-ntt:3100/loki/api/v1/push"
`;

const POSTGRES_CONF = `# Read-only. PostgreSQL is managed by the stack; change it in the engine compose, not here.
listen_addresses = '*'
port = 5432
max_connections = 100
shared_buffers = 256MB
log_destination = 'stderr'
logging_collector = off
`;

const HOST_JSON = `{
  "hostname": "ie-host",
  "docker": "27.3.1",
  "stack": "ntt",
  "cpus": 8,
  "memoryBytes": 17179869184,
  "diskFreeBytes": 128849018880,
  "containers": 18
}
`;

const CANDIDATE_YML = `# No candidate yet. Edit generator.yml, upload MIBs, then Generate.
# This file is replaced by the generator and is not the live snmp.yml.
`;

export const STACK_SLUG = 'ntt';

export function buildCatalog(): CatalogApp[] {
  return [
    app(
      'prometheus',
      'Prometheus',
      'Scrape jobs, rules, and the reload endpoint.',
      'metrics',
      'running',
      {
        version: 'v2.55.1',
        uptimeSeconds: 864000,
        lastReloadAt: '2026-10-27T08:14:00Z',
        actions: [reload(), restart(), validateAll()],
        files: [
          file(
            'prometheus.yml',
            '/etc/prometheus/prometheus.yml',
            'prometheus.yml',
            'yaml',
            PROMETHEUS_YML
          ),
          file(
            'insightengine-rules.yml',
            '/etc/prometheus/rules/insightengine.yml',
            'Alert rules',
            'yaml',
            RULES_YML
          ),
        ],
      }
    ),
    app(
      'alertmanager',
      'Alertmanager',
      'Route tree and webhook receivers for InsightEngine.',
      'alerting',
      'running',
      {
        version: 'v0.27.0',
        uptimeSeconds: 864000,
        lastReloadAt: '2026-10-26T19:02:00Z',
        actions: [reload(), restart(), validateAll()],
        files: [
          file(
            'alertmanager.yml',
            '/etc/alertmanager/alertmanager.yml',
            'alertmanager.yml',
            'yaml',
            ALERTMANAGER_YML
          ),
          withheld('ie-token', '/etc/alertmanager/ie-token', 'Webhook bearer token'),
        ],
      }
    ),
    app(
      'snmp-exporter',
      'SNMP exporter',
      'Generated snmp.yml. Edit it through the generator, or raw if you must.',
      'snmp',
      'running',
      {
        version: 'v0.26.0',
        uptimeSeconds: 172800,
        lastReloadAt: '2026-10-27T11:40:00Z',
        actions: [
          reload(),
          restart(),
          validateAll(),
          link('snmp-generator', 'Open SNMP generator'),
        ],
        files: [
          file('snmp.yml', '/etc/snmp_exporter/snmp.yml', 'snmp.yml', 'yaml', SNMP_YML, {
            hasSecrets: true,
          }),
        ],
      }
    ),
    app(
      'snmp-generator',
      'SNMP generator',
      'generator.yml, MIB files, and a candidate snmp.yml you promote explicitly.',
      'snmp',
      'exited',
      {
        version: 'v0.26.0',
        uptimeSeconds: 0,
        actions: [
          { id: 'generate', label: 'Generate', kind: 'generate', dangerous: false, roles: EDITORS },
          validateAll(),
          link('snmp-exporter', 'Open SNMP exporter'),
        ],
        files: [
          file(
            'generator.yml',
            '/opt/snmp-generator/generator.yml',
            'generator.yml',
            'yaml',
            GENERATOR_YML,
            { hasSecrets: true }
          ),
          file(
            'candidate-snmp.yml',
            '/opt/snmp-generator/snmp.candidate.yml',
            'Candidate snmp.yml',
            'yaml',
            CANDIDATE_YML,
            {
              editable: false,
              readOnlyReason:
                'Generated candidate. Review the diff, then use it as the live snmp.yml.',
            }
          ),
        ],
      }
    ),
    app('blackbox-exporter', 'Blackbox exporter', 'ICMP and HTTP probes.', 'metrics', 'running', {
      version: 'v0.25.0',
      uptimeSeconds: 400000,
      lastReloadAt: '2026-10-20T06:00:00Z',
      actions: [reload(), restart(), validateAll()],
      files: [
        file('blackbox.yml', '/etc/blackbox/blackbox.yml', 'blackbox.yml', 'yaml', BLACKBOX_YML),
      ],
    }),
    app('telegraf', 'Telegraf', 'Host metrics shipped to Prometheus.', 'metrics', 'running', {
      version: '1.32.1',
      uptimeSeconds: 500000,
      actions: [reload('Reload Telegraf'), restart(), validateAll()],
      files: [
        file(
          'telegraf.conf',
          '/etc/telegraf/telegraf.conf',
          'telegraf.conf',
          'toml',
          TELEGRAF_CONF
        ),
      ],
    }),
    app(
      'grafana',
      'Grafana',
      'Datasource provisioning. Dashboards stay in Grafana.',
      'platform',
      'running',
      {
        version: '11.3.0',
        uptimeSeconds: 700000,
        uiUrl: '/grafana/',
        actions: [reload('Reload provisioning'), restart()],
        files: [
          file(
            'datasources.yml',
            '/etc/grafana/provisioning/datasources/datasources.yml',
            'Datasources',
            'yaml',
            GRAFANA_DS
          ),
        ],
      }
    ),
    app(
      'caddy',
      'Caddy',
      'Edge proxy. Administrator edits only; a bad file takes the UI down.',
      'platform',
      'running',
      {
        version: '2.8.4',
        uptimeSeconds: 900000,
        lastReloadAt: '2026-10-25T12:11:00Z',
        actions: [reload('Reload Caddy'), restart(), validateAll()],
        files: [
          file('Caddyfile', '/etc/caddy/Caddyfile', 'Caddyfile', 'caddyfile', CADDYFILE, {
            adminOnly: true,
          }),
        ],
      }
    ),
    app(
      'netbox',
      'NetBox',
      'Inventory configuration. The secret key is masked.',
      'network',
      'unhealthy',
      {
        version: '4.1.6',
        uptimeSeconds: 12000,
        health: 'starting',
        lastError: 'Health check timed out on /login',
        uiUrl: '/netbox/',
        actions: [restart(), validateAll()],
        files: [
          file(
            'configuration.py',
            '/etc/netbox/config/configuration.py',
            'configuration.py',
            'python',
            NETBOX_PY,
            { hasSecrets: true }
          ),
        ],
      }
    ),
    app(
      'netdisco',
      'Netdisco',
      'Discovery worker. Prefixes to scan are configured on NetBox sync.',
      'network',
      'running',
      {
        version: '2.7',
        uptimeSeconds: 200000,
        actions: [reload(), restart()],
        files: [
          file(
            'deployment.yml',
            '/home/netdisco/deployment.yml',
            'deployment.yml',
            'yaml',
            NETDISCO_YML
          ),
        ],
      }
    ),
    app(
      'netbox-sync',
      'NetBox sync',
      'Which NetBox prefixes Netdisco scans, and how often.',
      'network',
      'running',
      {
        version: '1.4.0',
        uptimeSeconds: 200000,
        lastReloadAt: '2026-10-27T06:00:00Z',
        actions: [reload(), restart()],
        files: [
          file('scan.yml', '/etc/netbox-sync/scan.yml', 'Scan selection', 'yaml', NETBOX_SYNC_YML),
        ],
      }
    ),
    app(
      'activepieces',
      'Activepieces',
      'Automation worker connection. Tokens stay in a secret file.',
      'automation',
      'running',
      {
        version: '0.39.0',
        uptimeSeconds: 300000,
        uiUrl: '/automation/',
        actions: [restart()],
        files: [
          file(
            'config.json',
            '/etc/activepieces/config.json',
            'config.json',
            'json',
            ACTIVEPIECES_JSON
          ),
          withheld('secrets.env', '/etc/activepieces/secrets.env', 'Environment secrets'),
        ],
      }
    ),
    app('loki', 'Loki', 'Log store used by syslog and trapd.', 'platform', 'running', {
      version: '3.2.1',
      uptimeSeconds: 600000,
      actions: [reload(), restart(), validateAll()],
      files: [file('loki.yml', '/etc/loki/local-config.yaml', 'loki.yml', 'yaml', LOKI_YML)],
    }),
    app(
      'promtail',
      'Promtail (syslog)',
      'Syslog listener that pushes into Loki.',
      'platform',
      'running',
      {
        version: '3.2.1',
        uptimeSeconds: 600000,
        actions: [reload(), restart(), validateAll()],
        files: [
          file('promtail.yml', '/etc/promtail/config.yml', 'promtail.yml', 'yaml', PROMTAIL_YML),
        ],
      }
    ),
    app(
      'oxidized',
      'Oxidized',
      'Configuration backup. The device password is masked.',
      'network',
      'running',
      {
        version: '0.30.1',
        uptimeSeconds: 250000,
        actions: [restart(), validateAll()],
        files: [
          file('config', '/home/oxidized/.config/oxidized/config', 'config', 'yaml', OXIDIZED_YML, {
            hasSecrets: true,
          }),
        ],
      }
    ),
    app(
      'trapd',
      'trapd',
      'SNMP trap receiver. The community string is masked.',
      'network',
      'running',
      {
        version: '1.2.0',
        uptimeSeconds: 250000,
        actions: [reload(), restart()],
        files: [
          file('trapd.toml', '/etc/trapd/trapd.toml', 'trapd.toml', 'toml', TRAPD_TOML, {
            hasSecrets: true,
          }),
        ],
      }
    ),
    app(
      'postgres',
      'PostgreSQL',
      'Database status. Read-only: the engine owns this service.',
      'data',
      'running',
      {
        version: '16.4',
        uptimeSeconds: 1200000,
        actions: [],
        files: [
          file(
            'postgresql.conf',
            '/var/lib/postgresql/data/postgresql.conf',
            'postgresql.conf',
            'ini',
            POSTGRES_CONF,
            {
              editable: false,
              readOnlyReason: 'PostgreSQL is managed by the stack. This view is read-only.',
            }
          ),
        ],
      }
    ),
    app('host', 'Host', 'Docker host and stack status. Read-only.', 'data', 'running', {
      uptimeSeconds: 2_000_000,
      actions: [],
      files: [
        file(
          'status.json',
          '/var/lib/insightengine/host-status.json',
          'Host status',
          'json',
          HOST_JSON,
          {
            editable: false,
            readOnlyReason: 'Host status is reported by the engine and cannot be edited here.',
          }
        ),
      ],
    }),
  ];
}

function app(
  id: string,
  name: string,
  description: string,
  group: AppGroup,
  state: ContainerState,
  extra: {
    version?: string;
    uptimeSeconds?: number;
    health?: string;
    uiUrl?: string;
    lastReloadAt?: string | null;
    lastError?: string | null;
    actions: SettingsAction[];
    files: CatalogFile[];
  }
): CatalogApp {
  return {
    id,
    name,
    description,
    group,
    service: id,
    state,
    health: extra.health ?? (state === 'running' ? 'healthy' : undefined),
    uptimeSeconds: extra.uptimeSeconds,
    version: extra.version,
    uiUrl: extra.uiUrl,
    lastReloadAt: extra.lastReloadAt ?? null,
    lastError: extra.lastError ?? null,
    actions: extra.actions,
    files: extra.files,
  };
}

function file(
  id: string,
  path: string,
  label: string,
  language: FileLanguage,
  content: string,
  opts: {
    editable?: boolean;
    readOnlyReason?: string;
    hasSecrets?: boolean;
    adminOnly?: boolean;
  } = {}
): CatalogFile {
  return {
    id,
    path,
    label,
    language,
    content,
    editable: opts.editable !== false,
    readOnlyReason: opts.readOnlyReason,
    hasSecrets: opts.hasSecrets === true,
    adminOnly: opts.adminOnly,
  };
}

function withheld(id: string, path: string, label: string): CatalogFile {
  return {
    id,
    path,
    label,
    language: 'text',
    content: '',
    editable: false,
    hasSecrets: true,
    withheld: true,
    readOnlyReason: 'Secret files are never returned and cannot be edited here.',
  };
}
