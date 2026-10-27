#!/usr/bin/env python3
"""
=============================================================================
      Insights Engine (IE) NTT Monitoring Stack — Automated Deployment Script
=============================================================================
This script automates the full deployment workflow described in README.md:

  1. System update & Git installation
  2. Git clone of the repository
  3. Docker Engine & Compose installation
  4. Docker Compose pull (with progress bar)
  5. Container startup (2-minute settle, then status display)

Usage:
    sudo python3 deploy_monitoring_stack.py

Prerequisites:
    - Ubuntu / Debian-based Linux distribution
    - sudo / root access
    - Internet connectivity
"""

import os
import sys
import re
import subprocess
import time
import shutil
import threading


# ═══════════════════════════════════════════════════════════════════════════════
# Configuration — edit these values to match your environment
# ═══════════════════════════════════════════════════════════════════════════════

GIT_REPO_URL = None  # Will be prompted at runtime
GIT_USER_EMAIL = "Hishaam02@gmail.com"
GIT_USER_NAME = "Hishaam"
CLONE_DIR = "/opt/ie"
COMPOSE_DIR = os.path.join(CLONE_DIR, "dockering")

# Timeouts  (seconds)
PULL_TIMEOUT = 300           # max wait for docker compose pull


# ═══════════════════════════════════════════════════════════════════════════════
# Deploy configuration — collected from user prompts, written to .env and
# alertmanager.yml before containers are started.
# ═══════════════════════════════════════════════════════════════════════════════

deploy_config: dict[str, str] = {}


# ═══════════════════════════════════════════════════════════════════════════════
# Helper utilities
# ═══════════════════════════════════════════════════════════════════════════════

def print_banner(text: str) -> None:
    """Print a clearly visible section header."""
    width = shutil.get_terminal_size().columns
    line = "═" * width
    print(f"\n\033[94m{line}\033[0m")
    print(f"\033[94m  {text}\033[0m")
    print(f"\033[94m{line}\033[0m\n")


def run_cmd(cmd: list[str], check: bool = True, capture: bool = False,
            timeout: int | None = None) -> subprocess.CompletedProcess:
    """
    Run a shell command and return the result.

    Parameters
    ----------
    cmd : list[str]
        Command and arguments (e.g. ["apt", "update"]).
    check : bool
        If True, raise CalledProcessError on non-zero exit.
    capture : bool
        If True, capture stdout/stderr instead of printing live.
    timeout : int | None
        Optional timeout in seconds.
    """
    print(f"  \033[90m$ {' '.join(cmd)}\033[0m")
    sys.stdout.flush()
    try:
        if capture:
            result = subprocess.run(
                cmd, capture_output=True, text=True, check=check, timeout=timeout
            )
        else:
            result = subprocess.run(cmd, check=check, timeout=timeout)
    except subprocess.CalledProcessError as e:
        print(f"\n  \033[91m✖ Command failed with exit code {e.returncode}\033[0m")
        if e.stdout:
            print(e.stdout)
        if e.stderr:
            print(e.stderr)
        raise
    except subprocess.TimeoutExpired:
        print(f"\n  \033[91m✖ Command timed out after {timeout}s\033[0m")
        raise
    return result


def get_effective_user() -> str:
    """Return the original (non-root) username, even when running under sudo."""
    return os.getenv("SUDO_USER") or os.getenv("USER", "root")


def confirm_step(description: str, timeout_sec: int = 10) -> bool:
    """Pause and ask the user to confirm before continuing. Auto-continues after timeout_sec."""
    print(f"\n  \033[93m⏸  PAUSE: {description}\033[0m")
    print(f"  \033[93m  (Auto-continuing in {timeout_sec}s — press Y or N to override)\033[0m")
    print(f"  \033[93m  Continue? [Y/n]: \033[0m", end="", flush=True)

    try:
        # Use threading-based timeout approach (cross-platform)
        import threading
        result = [None]

        def get_input():
            result[0] = sys.stdin.readline().strip().lower()

        thread = threading.Thread(target=get_input, daemon=True)
        thread.start()
        thread.join(timeout=timeout_sec)

        if thread.is_alive():
            print("\n  \033[92m  Auto-continuing.\033[0m")
            return True

        response = result[0]
        if response in ("n", "no"):
            print("  \033[91m  Skipped by user.\033[0m")
            return False
        return True
    except Exception:
        # Fallback: simple input with no timeout
        response = input("  \033[93m  Continue? [Y/n]: \033[0m").strip().lower()
        if response in ("n", "no"):
            print("  \033[91m  Skipped by user.\033[0m")
            return False
        return True


def prompt_git_url() -> None:
    """Prompt the user for the Git repository clone URL and update the global variable."""
    global GIT_REPO_URL
    print_banner("Git Repository URL")
    print("  Enter the Git clone URL for the monitoring stack repository.")
    print("  This can be an HTTPS, SSH, or token-based URL.\n")
    url = input("  Git clone URL: ").strip()
    while not url:
        print("  \033[93mURL cannot be empty. Please try again.\033[0m")
        url = input("  Git clone URL: ").strip()
    GIT_REPO_URL = url
    print(f"  \033[92m✓ Repository URL set: {GIT_REPO_URL}\033[0m\n")


def prompt_input(label: str, default: str = "", password: bool = False) -> str:
    """Prompt the user for a single value with an optional default."""
    prompt_text = f"  {label}"
    if default and not password:
        prompt_text += f" [{default}]"
    prompt_text += ": "
    value = input(f"\033[93m{prompt_text}\033[0m").strip()
    if not value and default and not password:
        return default
    return value


def prompt_password(label: str, confirm: bool = True) -> str:
    """Prompt for a password with optional confirmation."""
    import getpass
    while True:
        value = getpass.getpass(f"\033[93m  {label}: \033[0m").strip()
        if not value:
            print("  \033[91mValue cannot be empty.\033[0m")
            continue
        if confirm:
            value2 = getpass.getpass(f"\033[93m  Confirm {label}: \033[0m").strip()
            if value != value2:
                print("  \033[91mValues do not match. Please try again.\033[0m")
                continue
        return value


def generate_secret_key(length: int = 50) -> str:
    """Generate a random secret key suitable for Django/NetBox."""
    import secrets as _secrets
    import string
    alphabet = string.ascii_letters + string.digits + "-_"
    return "".join(_secrets.choice(alphabet) for _ in range(length))


def generate_hex_key(length: int = 32) -> str:
    """Generate a hexadecimal key of `length` chars (default 32 = 16 bytes).

    Activepieces requires AP_ENCRYPTION_KEY to be a 32-char hexadecimal string.
    """
    import secrets as _secrets
    return _secrets.token_hex(length // 2)


def generate_bcrypt_hash(password: str) -> str:
    """Generate a bcrypt hash compatible with Caddy basicauth using htpasswd or python."""
    # Try htpasswd first (most reliable for Caddy)
    try:
        result = subprocess.run(
            ["htpasswd", "-nbBC", "14", "", password],
            capture_output=True, text=True, check=True, timeout=5,
        )
        # htpasswd output: ":$2a$14$..." — strip the leading colon and empty user
        hash_val = result.stdout.strip().lstrip(":")
        return hash_val
    except (FileNotFoundError, subprocess.CalledProcessError):
        pass

    # Fallback: python bcrypt library
    try:
        bcrypt = __import__("bcrypt")
        return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=14)).decode()
    except ImportError:
        pass

    # Fallback: use Caddy inside a temporary container
    print("  \033[93m⚠ htpasswd and bcrypt not available. Using Caddy container to generate hash.\033[0m")
    try:
        result = subprocess.run(
            ["docker", "run", "--rm", "caddy:2.11.2-alpine",
             "caddy", "hash-password", "--plaintext", password],
            capture_output=True, text=True, check=True, timeout=30,
        )
        return result.stdout.strip()
    except Exception:
        print("  \033[91m✖ Cannot generate bcrypt hash. Install apache2-utils or python3-bcrypt.\033[0m")
        raise


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 1c — Configuration prompts (.env, alertmanager.yml, SNMP credentials)
# ═══════════════════════════════════════════════════════════════════════════════

def phase_configure_environment():
    """Prompt for all deployment-specific values and write .env, alertmanager.yml, api_token.txt."""
    global deploy_config
    print_banner("PHASE 1c — Environment Configuration")

    user = get_effective_user()

    # ── Host configuration ──────────────────────────────────────────────
    print("\n  \033[96m── Host Configuration ─────────────────────────────\033[0m\n")
    host_ip = prompt_input("Server IP address (reachable by operators)")
    while not host_ip:
        print("  \033[91mServer IP is required.\033[0m")
        host_ip = prompt_input("Server IP address")

    # Determine UID/GID automatically
    import pwd
    try:
        pw = pwd.getpwnam(user)
        host_uid = str(pw.pw_uid)
        host_gid = str(pw.pw_gid)
    except KeyError:
        host_uid = "1000"
        host_gid = "1000"

    print(f"  \033[90mDetected user: {user} (UID={host_uid}, GID={host_gid})\033[0m")
    deploy_config.update({
        "HOST_IP": host_ip,
        "HOST_USER": user,
        "HOST_UID": host_uid,
        "HOST_GID": host_gid,
    })

    # ── Passwords ──────────────────────────────────────────────────────
    print("\n  \033[96m── Passwords ─────────────────────────────────────\033[0m")
    print("  \033[90mA single master password is recommended for all services in a single-site deployment.\033[0m")
    print("  \033[90mUse a different password for production multi-site deployments.\033[0m\n")

    use_single = input("\033[93m  Use a single password for all services? [Y/n]: \033[0m").strip().lower()
    if use_single in ("", "y", "yes"):
        master_password = prompt_password("Master password")
        grafana_password = master_password
        netbox_db_password = master_password
        redis_password = master_password
        netbox_superuser_password = master_password
        ap_db_password = master_password
    else:
        grafana_password = prompt_password("Grafana admin password")
        netbox_db_password = prompt_password("NetBox database password")
        redis_password = prompt_password("Redis password")
        netbox_superuser_password = prompt_password("NetBox superuser password")
        ap_db_password = prompt_password("Activepieces database password")

    # Generate NetBox secret key
    netbox_secret_key = generate_secret_key(50)
    print(f"\n  \033[90mGenerated NetBox secret key ({len(netbox_secret_key)} chars)\033[0m")

    # Generate Activepieces encryption key (32 hex chars)
    ap_encryption_key = generate_hex_key(32)
    print(f"  \033[90mGenerated Activepieces encryption key ({len(ap_encryption_key)} hex chars)\033[0m")

    # Generate Activepieces JWT secret (64 hex chars)
    ap_jwt_secret = generate_hex_key(64)
    print(f"  \033[90mGenerated Activepieces JWT secret ({len(ap_jwt_secret)} hex chars)\033[0m")

    deploy_config.update({
        "GRAFANA_ADMIN_USER": "admin",
        "GRAFANA_ADMIN_PASSWORD": grafana_password,
        "NETBOX_DB_PASSWORD": netbox_db_password,
        "POSTGRES_DB_NAME": "netbox",
        "POSTGRES_USER": "netbox",
        "REDIS_PASSWORD": redis_password,
        "NETBOX_SECRET_KEY": netbox_secret_key,
        "NETBOX_SUPERUSER_EMAIL": "admin@yourdomain.com",
        "NETBOX_SUPERUSER_NAME": "netboxadmin",
        "NETBOX_SUPERUSER_PASSWORD": netbox_superuser_password,
        "AP_POSTGRES_DATABASE": "activepieces",
        "AP_POSTGRES_USERNAME": "activepieces",
        "AP_POSTGRES_PASSWORD": ap_db_password,
        "AP_REDIS_PASSWORD": redis_password,
        "AP_ENCRYPTION_KEY": ap_encryption_key,
        "AP_JWT_SECRET": ap_jwt_secret,
        "AP_DATA_DB": "activepieces_data",
        "AP_DATA_USER": "activepieces_data",
        "AP_DATA_PASSWORD": ap_db_password,
        "TELEGRAF_PG_DB": "telegraf_data",
        "TELEGRAF_PG_USER": "telegraf",
        "TELEGRAF_PG_PASSWORD": ap_db_password,
    })

    # ── Validate required secrets are present and valid ───────────────
    # Prevents silently writing empty/malformed values to .env, which causes
    # cryptic container startup errors (redis/postgres auth failure,
    # AP_ENCRYPTION_KEY invalid abort).
    required_secrets = [
        "GRAFANA_ADMIN_PASSWORD", "NETBOX_DB_PASSWORD", "REDIS_PASSWORD",
        "NETBOX_SUPERUSER_PASSWORD", "AP_POSTGRES_PASSWORD", "AP_REDIS_PASSWORD",
        "AP_DATA_PASSWORD", "TELEGRAF_PG_PASSWORD",
        "NETBOX_SECRET_KEY", "AP_ENCRYPTION_KEY", "AP_JWT_SECRET",
    ]
    missing = [k for k in required_secrets if not deploy_config.get(k)]
    if missing:
        print(f"\n  \033[91m✖ ERROR: Required secret(s) are empty: {', '.join(missing)}\033[0m")
        print("  \033[91m  This usually means a value was not generated or a prompt was missed.\033[0m")
        print("  \033[91m  Aborting before writing .env to avoid a broken deployment.\033[0m")
        sys.exit(1)

    # AP_ENCRYPTION_KEY must be a valid 32-hex-char string or Activepieces won't start.
    encryption_key = deploy_config.get("AP_ENCRYPTION_KEY", "")
    if not re.fullmatch(r"[0-9a-fA-F]{32}", encryption_key):
        print("\n  \033[91m✖ ERROR: AP_ENCRYPTION_KEY must be a 32-char hexadecimal string.\033[0m")
        print(f"  \033[91m  Got: {encryption_key!r}\033[0m")
        print("  \033[91m  Activepieces will fail to start without a valid key.\033[0m")
        print("  \033[91m  Aborting. Re-run deployment or fix .env manually.\033[0m")
        sys.exit(1)

    # ── SNMP credentials ──────────────────────────────────────────────
    print("\n  \033[96m── SNMP Credentials ───────────────────────────────\033[0m\n")

    print("  \033[90mSNMPv3 is used for modern devices (Cisco, Arista, FortiGate, etc.)\033[0m")
    print("  \033[90mSNMPv2 is used for older devices that don't support v3.\033[0m\n")

    snmp_v3_username = prompt_input("SNMPv3 username")
    snmp_v3_auth_password = prompt_password(f"SNMPv3 auth password (SHA256) for user '{snmp_v3_username}'")
    snmp_v3_priv_password = prompt_password(f"SNMPv3 priv/encryption password (AES256) for user '{snmp_v3_username}'")
    snmp_v2_community = prompt_input("SNMPv2 community string")

    deploy_config.update({
        "SNMP_V3_USERNAME": snmp_v3_username,
        "SNMP_V3_AUTH_PASSWORD": snmp_v3_auth_password,
        "SNMP_V3_PRIV_PASSWORD": snmp_v3_priv_password,
        "SNMP_V2_COMMUNITY": snmp_v2_community,
    })

    # ── Alertmanager webhook ──────────────────────────────────────────
    print("\n  \033[96m── Alertmanager Webhook ───────────────────────────\033[0m\n")

    print("  \033[90mAlertmanager routes alerts to an external Insights Engine webhook over HTTPS.\033[0m")
    print("  \033[90mProvide the full URL and Bearer token for your Insights Engine instance.\033[0m\n")

    webhook_url = prompt_input("Insights Engine webhook URL (e.g. https://<insights-engine-core>.<domain>/iecore/post/prometheus_alerts_<CLIENT>)")
    while not webhook_url:
        print("  \033[91mWebhook URL is required.\033[0m")
        webhook_url = prompt_input("Insights Engine webhook URL")

    webhook_token = prompt_password("Insights Engine webhook Bearer token", confirm=False)

    # ── Write .env file ───────────────────────────────────────────────
    print("\n  \033[96m── Writing configuration files ────────────────────\033[0m\n")

    os.makedirs(COMPOSE_DIR, exist_ok=True)
    env_path = os.path.join(COMPOSE_DIR, ".env")
    if os.path.exists(env_path):
        print(f"  \033[93m⚠ .env already exists — backing up to .env.bak\033[0m")
        shutil.copy(env_path, env_path + ".bak")

    # Write .env
    env_lines = [
        "# ============================================",
        "# NETWORK & HOST CONFIGURATION",
        "# ============================================",
        f"HOST_IP={deploy_config['HOST_IP']}",
        f"HOST_USER={deploy_config['HOST_USER']}",
        f"HOST_UID={deploy_config['HOST_UID']}",
        f"HOST_GID={deploy_config['HOST_GID']}",
        "",
        "# ============================================",
        "# GRAFANA CONFIGURATION",
        "# ============================================",
        f"GRAFANA_ADMIN_USER={deploy_config['GRAFANA_ADMIN_USER']}",
        f"GRAFANA_ADMIN_PASSWORD={deploy_config['GRAFANA_ADMIN_PASSWORD']}",
        "",
        "# ============================================",
        "# NETBOX DATABASE CONFIGURATION - POSTGRESQL",
        "# ============================================",
        f"NETBOX_DB_PASSWORD={deploy_config['NETBOX_DB_PASSWORD']}",
        f"POSTGRES_DB_NAME={deploy_config['POSTGRES_DB_NAME']}",
        f"POSTGRES_USER={deploy_config['POSTGRES_USER']}",
        "",
        "# ============================================",
        "# REDIS CONFIGURATION",
        "# ============================================",
        f"REDIS_PASSWORD={deploy_config['REDIS_PASSWORD']}",
        "",
        "# ============================================",
        "# NETBOX APPLICATION CONFIGURATION",
        "# ============================================",
        f"NETBOX_SECRET_KEY={deploy_config['NETBOX_SECRET_KEY']}",
        f"NETBOX_SUPERUSER_EMAIL={deploy_config['NETBOX_SUPERUSER_EMAIL']}",
        f"NETBOX_SUPERUSER_NAME={deploy_config['NETBOX_SUPERUSER_NAME']}",
        f"NETBOX_SUPERUSER_PASSWORD={deploy_config['NETBOX_SUPERUSER_PASSWORD']}",
        "",
        "# ============================================",
        "# ACTIVEPIECES CONFIGURATION",
        "# ============================================",
        f"AP_ENCRYPTION_KEY={deploy_config['AP_ENCRYPTION_KEY']}",
        f"AP_JWT_SECRET={deploy_config['AP_JWT_SECRET']}",
        f"AP_POSTGRES_DATABASE={deploy_config['AP_POSTGRES_DATABASE']}",
        f"AP_POSTGRES_USERNAME={deploy_config['AP_POSTGRES_USERNAME']}",
        f"AP_POSTGRES_PASSWORD={deploy_config['AP_POSTGRES_PASSWORD']}",
        f"AP_REDIS_PASSWORD={deploy_config['AP_REDIS_PASSWORD']}",
        "",
        "# ============================================",
        "# ANALYTICAL DATA DATABASES (on shared-postgres)",
        "# ============================================",
        f"AP_DATA_DB={deploy_config['AP_DATA_DB']}",
        f"AP_DATA_USER={deploy_config['AP_DATA_USER']}",
        f"AP_DATA_PASSWORD={deploy_config['AP_DATA_PASSWORD']}",
        f"TELEGRAF_PG_DB={deploy_config['TELEGRAF_PG_DB']}",
        f"TELEGRAF_PG_USER={deploy_config['TELEGRAF_PG_USER']}",
        f"TELEGRAF_PG_PASSWORD={deploy_config['TELEGRAF_PG_PASSWORD']}",
        "",
        "# ============================================",
        "# SNMP CREDENTIAL CONFIGURATION",
        "# ============================================",
        f"SNMP_V3_USERNAME={deploy_config['SNMP_V3_USERNAME']}",
        f"SNMP_V3_AUTH_PASSWORD={deploy_config['SNMP_V3_AUTH_PASSWORD']}",
        f"SNMP_V3_PRIV_PASSWORD={deploy_config['SNMP_V3_PRIV_PASSWORD']}",
        f"SNMP_V2_COMMUNITY={deploy_config['SNMP_V2_COMMUNITY']}",
        "",
    ]
    with open(env_path, "w") as f:
        f.write("\n".join(env_lines))
    os.chmod(env_path, 0o600)
    print(f"  \033[92m✓ .env written ({env_path})\033[0m")

    # ── Write alertmanager.yml ─────────────────────────────────────────
    am_dir = os.path.join(CLONE_DIR, "alertmanager")
    am_path = os.path.join(am_dir, "alertmanager.yml")
    os.makedirs(am_dir, exist_ok=True)

    if os.path.exists(am_path):
        print(f"  \033[93m⚠ alertmanager.yml already exists — backing up\033[0m")
        shutil.copy(am_path, am_path + ".bak")

    am_content = f"""global:
  resolve_timeout: 5m

route:
  receiver: 'ie-prometheus-webhook'
  group_wait: 10s
  group_interval: 1m
  repeat_interval: 15m

receivers:
  - name: 'ie-prometheus-webhook'
    webhook_configs:
      - url: '{webhook_url}'
        send_resolved: false
        http_config:
          authorization:
            type: Bearer
            credentials_file: /etc/alertmanager/api_token.txt
"""
    with open(am_path, "w") as f:
        f.write(am_content)
    print(f"  \033[92m✓ alertmanager.yml written ({am_path})\033[0m")

    # ── Write api_token.txt ────────────────────────────────────────────
    token_path = os.path.join(am_dir, "api_token.txt")
    with open(token_path, "w") as f:
        f.write(webhook_token)
    print(f"  \033[92m✓ api_token.txt written ({token_path})\033[0m")

    # ── Fix credential file ownership so containers (run as nobody/65534)
    #    can read them via group permission. Prevents the recurring
    #    'permission denied' on alertmanager config reload.
    for _f in (am_path, token_path):
        run_cmd(["sudo", "chown", f"{user}:65534", _f])
        run_cmd(["sudo", "chmod", "640", _f])
    print("  \033[92m✓ alertmanager credentials chowned to <user>:65534 (640)\033[0m")

    # ── Write dummy netbox.token ───────────────────────────────────────
    prom_dir = os.path.join(CLONE_DIR, "prometheus")
    os.makedirs(prom_dir, exist_ok=True)
    nb_token_path = os.path.join(prom_dir, "netbox.token")
    with open(nb_token_path, "w") as f:
        f.write("REPLACE_WITH_REAL_NETBOX_API_TOKEN")
    run_cmd(["sudo", "chown", f"{user}:65534", nb_token_path])
    run_cmd(["sudo", "chmod", "640", nb_token_path])
    print(f"  \033[92m✓ netbox.token written (dummy — replace after NetBox is running)\033[0m")

    # ── Generate TLS self-signed certificate ───────────────────────────
    certs_dir = os.path.join(CLONE_DIR, "caddy", "certs")
    os.makedirs(certs_dir, exist_ok=True)
    crt_path = os.path.join(certs_dir, "server.crt")
    key_path = os.path.join(certs_dir, "server.key")

    print(f"\n  \033[90mGenerating self-signed TLS certificate for {host_ip}...\033[0m")
    ssl_cmd = [
        "openssl", "req", "-x509", "-newkey", "rsa:4096", "-nodes",
        "-keyout", key_path,
        "-out", crt_path,
        "-days", "365",
        "-subj", f"/CN={host_ip}",
        "-addext", f"subjectAltName=IP:{host_ip},DNS:{user},DNS:localhost,IP:127.0.0.1",
    ]
    run_cmd(ssl_cmd)
    print(f"  \033[92m✓ TLS certificate generated ({crt_path})\033[0m")
    print(f"  \033[92m✓ TLS key generated ({key_path})\033[0m")

    print("\n  \033[92m✓ All configuration files created.\033[0m")
    print("  \033[93m⚠ Note: NetBox API token (prometheus/netbox.token) contains a dummy value.\033[0m")
    print("  \033[93m  Replace it with a real token after NetBox is running:\033[0m")
    print("  \033[93m  1. Log in to NetBox at https://<server-ip>:8080\033[0m")
    print("  \033[93m  2. Admin → API Tokens → Add new token\033[0m")
    print("  \033[93m  3. Write the token to /opt/ie/prometheus/netbox.token\033[0m")
    print("  \033[93m  4. Reload Prometheus: curl -k -X POST https://localhost:9090/-/reload\033[0m")


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 1 — System preparation & Git clone
# ═══════════════════════════════════════════════════════════════════════════════

def phase_system_update():
    """Phase 1a: apt update && install git."""
    print_banner("PHASE 1 — System Update & Git Installation")

    run_cmd(["sudo", "apt", "update"])
    run_cmd(["sudo", "apt", "install", "-y", "git", "apache2-utils"])

    # Configure Git
    run_cmd(["git", "config", "--global", "user.email", GIT_USER_EMAIL])
    run_cmd(["git", "config", "--global", "user.name", GIT_USER_NAME])

    result = run_cmd(["git", "config", "--global", "--list"], capture=True)
    print(f"\n  Git configuration:\n{result.stdout}")
    print("  \033[92m✓ System updated & Git configured\033[0m")


def phase_clone_repo():
    """Phase 1b: Clone the repository."""
    print_banner("PHASE 1b — Clone Repository")

    # Create /opt/ie if needed
    if not os.path.exists(CLONE_DIR):
        os.makedirs(CLONE_DIR, exist_ok=True)
        print(f"  Created {CLONE_DIR}")

    # Fix ownership
    run_cmd(["sudo", "chown", "-R", f"{get_effective_user()}:{get_effective_user()}", CLONE_DIR])
    run_cmd(["git", "config", "--global", "--add", "safe.directory", CLONE_DIR])

    os.chdir(CLONE_DIR)
    print(f"  Changed to {CLONE_DIR}")

    if os.path.exists(os.path.join(CLONE_DIR, ".git")):
        print("  \033[93m⚠ Repository already cloned — pulling latest instead.\033[0m")
        run_cmd(["git", "pull"])
    else:
        run_cmd(["git", "clone", GIT_REPO_URL, "."])

    # Fix ownership again after clone
    run_cmd(["sudo", "chown", "-R", f"{get_effective_user()}:{get_effective_user()}", CLONE_DIR])

    print("  \033[92m✓ Repository cloned successfully\033[0m")


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 2 — Docker installation
# ═══════════════════════════════════════════════════════════════════════════════

def phase_install_docker():
    """Phase 2: Install Docker Engine, Compose, and related tools."""
    print_banner("PHASE 2 — Docker Engine & Compose Installation")

    run_cmd(["sudo", "apt", "update"])
    run_cmd(["sudo", "apt", "install", "-y", "ca-certificates", "curl", "gnupg"])

    # Create keyrings directory
    run_cmd(["sudo", "install", "-m", "0755", "-d", "/etc/apt/keyrings"])

    # Download Docker GPG key
    keyring_path = "/etc/apt/keyrings/docker.asc"
    if not os.path.exists(keyring_path):
        run_cmd([
            "sudo", "curl", "-fsSL",
            "https://download.docker.com/linux/ubuntu/gpg",
            "-o", keyring_path,
        ])
        run_cmd(["sudo", "chmod", "a+r", keyring_path])
        print("  \033[92m✓ Docker GPG key installed\033[0m")
    else:
        print("  \033[93m⚠ Docker GPG key already present, skipping.\033[0m")

    # Add Docker apt repository (skip if Docker's own .sources file already exists)
    sources_path = "/etc/apt/sources.list.d/docker.sources"
    if os.path.exists(sources_path):
        print("  \033[93m⚠ docker.sources already present — skipping docker.list.\033[0m")
    else:
        repo_cmd = (
            'echo "deb [arch=$(dpkg --print-architecture) '
            'signed-by=/etc/apt/keyrings/docker.asc] '
            'https://download.docker.com/linux/ubuntu '
            '$(. /etc/os-release && echo "$UBUNTU_CODENAME") stable" | '
            'sudo tee /etc/apt/sources.list.d/docker.list > /dev/null'
        )
        run_cmd(["bash", "-c", repo_cmd])

    run_cmd(["sudo", "apt", "update"])

    # Remove Ubuntu's docker-compose-v2 if present. It installs the same file
    # as Docker's docker-compose-plugin and blocks the install.
    check = subprocess.run(
        ["dpkg", "-s", "docker-compose-v2"],
        capture_output=True, text=True,
    )
    if check.returncode == 0 and "Status: install ok installed" in check.stdout:
        print("  \033[93m⚠ Removing Ubuntu's docker-compose-v2 (conflicts with docker-compose-plugin).\033[0m")
        run_cmd(["sudo", "apt", "remove", "-y", "docker-compose-v2"])
    else:
        print("  \033[90mdocker-compose-v2 not installed, skipping removal.\033[0m")

    run_cmd([
        "sudo", "apt", "install", "-y",
        "docker-ce", "docker-ce-cli", "containerd.io",
        "docker-buildx-plugin", "docker-compose-plugin",
    ])

    # Verify versions
    result = run_cmd(["docker", "--version"], capture=True)
    print(f"  Docker: {result.stdout.strip()}")
    result = run_cmd(["docker", "compose", "version"], capture=True)
    print(f"  Compose: {result.stdout.strip()}")

    # Add user to docker group
    run_cmd(["sudo", "usermod", "-aG", "docker", get_effective_user()])
    print("  \033[93m⚠ User added to 'docker' group.\033[0m")
    print("  \033[93m⚠ The new group will take effect after logout/login.\033[0m")
    print("  \033[93m⚠ Attempting 'newgrp docker' to activate in current session...\033[0m")

    # newgrp in a subprocess doesn't work well, so we'll just continue.
    # The compose commands later will use sudo if needed, or we try without.
    print("  \033[92m✓ Docker installed successfully\033[0m")


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 3 — Docker Compose Pull (with progress)
# ═══════════════════════════════════════════════════════════════════════════════

def phase_pull_images():
    """Phase 3: Pull all container images — Docker's native progress shown live."""
    print_banner("PHASE 3 — Pulling Container Images")

    if not os.path.isdir(COMPOSE_DIR):
        print(f"  \033[91m✖ Compose directory not found: {COMPOSE_DIR}\033[0m")
        raise FileNotFoundError(f"Compose directory missing: {COMPOSE_DIR}")

    os.chdir(COMPOSE_DIR)
    print(f"  Changed to {COMPOSE_DIR}")

    # Ensure correct permissions on /opt/ie
    run_cmd(["sudo", "chown", "-R", f"{get_effective_user()}:{get_effective_user()}", CLONE_DIR])

    print("  Pulling images (this may take several minutes)...\n")

    try:
        subprocess.run(
            ["docker", "compose", "pull"],
            check=True,
            timeout=PULL_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        print(f"\n  \033[91m✖ Pull timed out after {PULL_TIMEOUT}s\033[0m")
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        print(f"\n  \033[91m✖ Pull failed with exit code {e.returncode}\033[0m")
        sys.exit(1)

    print("\n  \033[92m✓ All images pulled successfully\033[0m")


# ═══════════════════════════════════════════════════════════════════════════════
# Retro 90s animation — runs while Docker works, output shown after
# ═══════════════════════════════════════════════════════════════════════════════

# Retro color palette (ANSI 256-color)
RETRO_CYAN    = "\033[38;5;51m"
RETRO_MAGENTA = "\033[38;5;201m"
RETRO_YELLOW  = "\033[38;5;227m"
RETRO_GREEN   = "\033[38;5;46m"
RETRO_ORANGE  = "\033[38;5;208m"
RETRO_DIM     = "\033[38;5;240m"
RETRO_RESET   = "\033[0m"

# Spinner frames
SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

# Retro status messages that cycle
RETRO_MESSAGES = [
    ("●  BOOTING INSIGHTS ENGINE", RETRO_CYAN),
    ("○  NETBOX IS DOING DJANGO MIGRATIONS", RETRO_MAGENTA),
    ("●  PROMETHEUS IS WARMING UP", RETRO_YELLOW),
    ("○  GRAFANA IS LOADING DASHBOARDS", RETRO_GREEN),
    ("●  CADDY IS GENERATING TLS CERTS", RETRO_ORANGE),
    ("○  REDIS IS CACHING ALL THE THINGS", RETRO_CYAN),
    ("●  ACTIVEPIECES IS BUILDING WORKFLOWS", RETRO_MAGENTA),
    ("○  BREWING COFFEE... PLEASE WAIT", RETRO_YELLOW),
]

# ASCII art logo (small, retro)
IE_LOGO = r"""
    ╔══════════════════════════════════════╗
    ║  I N S I G H T S    E N G I N E      ║
    ╚══════════════════════════════════════╝
"""


def _retro_progress_bar(percent: float, width: int = 40) -> str:
    """Generate a retro-style progress bar with block characters."""
    filled = int(width * percent / 100)
    bar = "█" * filled + "░" * (width - filled)
    return bar


def _draw_retro_line(frame_idx: int, msg_idx: int, elapsed_s: float,
                     progress_max: float = 95.0, duration_s: float = 300.0,
                     show_remaining: bool = False, remaining_s: float = 0.0):
    """Draw one frame of the retro animation on a single line (overwrites with \\r)."""
    spinner = SPINNER_FRAMES[frame_idx % len(SPINNER_FRAMES)]
    msg_text, msg_color = RETRO_MESSAGES[msg_idx % len(RETRO_MESSAGES)]

    progress = min(progress_max, (elapsed_s / duration_s) * 100.0)
    bar = _retro_progress_bar(progress)

    if show_remaining:
        mins = int(remaining_s) // 60
        secs = int(remaining_s) % 60
        time_str = f"{mins}:{secs:02d} remaining"
    else:
        time_str = f"{elapsed_s:.0f}s"

    # Single line — cleared and redrawn each frame, no scrolling
    line = (
        f"\r\033[K"
        f"{msg_color}{spinner} {msg_text}{RETRO_RESET}  "
        f"{RETRO_DIM}[{RETRO_RESET}{RETRO_CYAN}{bar}{RETRO_RESET}{RETRO_DIM}]"
        f" {progress:5.1f}%{RETRO_RESET}  "
        f"{RETRO_DIM}{time_str}{RETRO_RESET}"
    )
    sys.stdout.write(line)
    sys.stdout.flush()


def _run_docker_compose_with_animation(cmd: list[str]) -> tuple[int, str]:
    """
    Run 'docker compose up -d' with output captured (not streamed).
    A retro animation plays on the bottom line while Docker works.
    When Docker finishes, the animation is cleared and the captured
    output is returned for clean printing.

    Returns (exit_code, output_text).
    """
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
    )

    # Read output in a thread to prevent pipe buffer deadlock
    # (if Docker produces >64KB output, the pipe fills and proc.poll() hangs)
    output_chunks: list[bytes] = []

    def _read_output():
        try:
            while True:
                chunk = proc.stdout.read(4096)
                if not chunk:
                    break
                output_chunks.append(chunk)
        except Exception:
            pass

    reader = threading.Thread(target=_read_output, daemon=True)
    reader.start()

    frame_idx = 0
    msg_idx = 0
    start_time = time.time()

    # Animation loop — runs while Docker process is alive
    while True:
        elapsed = time.time() - start_time
        _draw_retro_line(frame_idx, msg_idx, elapsed)

        frame_idx += 1
        if frame_idx % 20 == 0:
            msg_idx += 1

        if proc.poll() is not None:
            break

        time.sleep(0.1)

    # Wait for reader thread to finish draining output
    reader.join(timeout=10)

    # Collect output
    output_text = b"".join(output_chunks).decode("utf-8", errors="replace")

    # Clear the animation (single line)
    sys.stdout.write("\r\033[K\r")
    sys.stdout.flush()

    return proc.returncode, output_text


def _retro_wait_animation(duration_sec: int, message: str = "Containers settling"):
    """Show a retro animation during a fixed wait period (e.g., the 2-minute settle)."""
    start_time = time.time()
    frame_idx = 0
    msg_idx = 0

    while True:
        elapsed = time.time() - start_time
        if elapsed >= duration_sec:
            break

        remaining = duration_sec - elapsed
        _draw_retro_line(frame_idx, msg_idx, elapsed,
                         progress_max=100.0, duration_s=duration_sec,
                         show_remaining=True, remaining_s=remaining)

        frame_idx += 1
        if frame_idx % 20 == 0:
            msg_idx += 1

        time.sleep(0.1)

    # Clear (single line)
    sys.stdout.write("\r\033[K\r")
    sys.stdout.flush()
    print(f"  {RETRO_GREEN}✓ {message} complete{RETRO_RESET}")


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 4 — Docker Compose Up (animated, 2-minute settle, then status)
# ═══════════════════════════════════════════════════════════════════════════════

def phase_start_containers():
    """Phase 4: Start containers with retro animation, wait, then display status."""
    print_banner("PHASE 4 — Starting Containers - grab a coffee!")

    os.chdir(COMPOSE_DIR)
    print(f"  Changed to {COMPOSE_DIR}")

    # Print retro logo
    print(f"{RETRO_CYAN}{IE_LOGO}{RETRO_RESET}")
    print(f"  {RETRO_DIM}Docker Compose is bringing up the stack...{RETRO_RESET}\n")

    # Start containers with animation (output captured, not streamed)
    print("  Running 'docker compose up -d' ...\n")
    try:
        exit_code, docker_output = _run_docker_compose_with_animation(
            ["docker", "compose", "up", "-d"]
        )
        # Print Docker's captured output cleanly (no scrolling)
        if docker_output.strip():
            print(docker_output)
        if exit_code != 0:
            print(f"\n  {RETRO_ORANGE}✖ docker compose up exited with code {exit_code}{RETRO_RESET}")
            # Don't sys.exit — containers may still come up, let the health check report
    except Exception as e:
        print(f"\n  \033[91m✖ docker compose up failed: {e}\033[0m")
        sys.exit(1)
    print("")

    # Wait 2 minutes with retro animation
    print(f"  {RETRO_DIM}Waiting 2 minutes for containers to settle...{RETRO_RESET}")
    _retro_wait_animation(120, "Container settle")
    print("")

    # Single status snapshot — informational only
    print("\n  \033[90m--- docker compose ps -a @ +2min ---\033[0m")
    result = subprocess.run(
        ["docker", "compose", "ps", "-a", "--format", "table {{.Name}}\t{{.Status}}\t{{.Ports}}"],
        capture_output=True, text=True, timeout=15,
    )
    for line in result.stdout.strip().split("\n"):
        print(f"  {line}")

    # ── Check container health ──────────────────────────────────────
    print("\n  \033[90m--- Checking container health ---\033[0m")

    # Parse the status output to find unhealthy/not-started containers
    ps_result = subprocess.run(
        ["docker", "compose", "ps", "-a", "--format", "{{.Name}}\t{{.Status}}"],
        capture_output=True, text=True, timeout=15,
    )

    unhealthy = []
    not_started = []
    all_healthy = True

    for line in ps_result.stdout.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split("\t")
        name = parts[0].strip()
        status = parts[1].strip() if len(parts) > 1 else ""
        if "unhealthy" in status.lower():
            unhealthy.append(name)
            all_healthy = False
        elif "created" in status.lower() and "up" not in status.lower():
            not_started.append(name)
            all_healthy = False
        elif "restarting" in status.lower():
            unhealthy.append(name)
            all_healthy = False

    # Deployment summary
    print(f"\n  {'=' * 56}")
    if all_healthy:
        print(f"  \033[92m✅  DEPLOYMENT SUCCESSFUL - All containers healthy\033[0m")
    else:
        print(f"  \033[93m⚠  DEPLOYMENT PARTIAL - Some containers need attention\033[0m")
        if unhealthy:
            print(f"  \033[91m  Unhealthy/restarting: {', '.join(unhealthy)}\033[0m")
        if not_started:
            print(f"  \033[93m  Not started: {', '.join(not_started)}\033[0m")
        print(f"  \033[93m  These may recover with more time. Check 'docker ps' in a few minutes.\033[0m")
        if not_started:
            print(f"  \033[93m  Start them manually: docker start {' '.join(not_started)}\033[0m")
    print(f"  {'=' * 56}")
    print(f"  \033[96m  Working directory:\033[0m {COMPOSE_DIR}")
    print(f"  {'=' * 56}")
    print(f"  \033[92m  You may now start populating NetBox. Check docker ps until all healthy.\033[0m")
    print(f"  {'=' * 56}\n")


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 5 — Final steps
# ═══════════════════════════════════════════════════════════════════════════════

def phase_finalize():
    """Phase 5: Final ownership fix, file permissions, and troubleshooting hints."""
    print_banner("PHASE 5 — Finalization")

    user = get_effective_user()

    # Final ownership fix — everything owned by the deployment user
    run_cmd(["sudo", "chown", "-R", f"{user}:{user}", "/opt/ie"])

    # ── Set file permissions for credential files that containers read ──
    # Containers running as nobody (uid 65534) need group-read access.
    # We chown these files to <user>:nogroup and chmod 640 so:
    #   - owner (user) can read/write
    #   - group (nogroup = 65534 = container's nobody) can read
    #   - others get nothing
    #
    # Files that need this treatment:
    #   - alertmanager/alertmanager.yml  (read by Alertmanager, runs as nobody)
    #   - alertmanager/api_token.txt    (read by Alertmanager, runs as nobody)
    #   - prometheus/netbox.token        (read by Prometheus, runs as nobody)

    print("\n  \033[90mSetting credential file permissions for container access...\033[0m")

    cred_files = [
        os.path.join(CLONE_DIR, "alertmanager", "alertmanager.yml"),
        os.path.join(CLONE_DIR, "alertmanager", "api_token.txt"),
        os.path.join(CLONE_DIR, "prometheus", "netbox.token"),
    ]

    for cred_file in cred_files:
        if os.path.exists(cred_file):
            run_cmd(["sudo", "chown", f"{user}:65534", cred_file])
            run_cmd(["sudo", "chmod", "640", cred_file])

    # ── Set TLS cert permissions ──
    certs_dir = os.path.join(CLONE_DIR, "caddy", "certs")
    if os.path.isdir(certs_dir):
        run_cmd(["sudo", "chown", "-R", f"{user}:{user}", certs_dir])
        crt = os.path.join(certs_dir, "server.crt")
        key = os.path.join(certs_dir, "server.key")
        if os.path.exists(crt):
            run_cmd(["sudo", "chmod", "644", crt])
        if os.path.exists(key):
            run_cmd(["sudo", "chmod", "640", key])

    # ── Set .env permissions ──
    env_path = os.path.join(COMPOSE_DIR, ".env")
    if os.path.exists(env_path):
        run_cmd(["sudo", "chown", f"{user}:{user}", env_path])
        run_cmd(["sudo", "chmod", "600", env_path])

    # ── Set snmp.yml permissions (world-readable, snmp-exporter runs as root with cap_drop) ──
    snmp_path = os.path.join(CLONE_DIR, "snmp-exporter", "snmp.yml")
    if os.path.exists(snmp_path):
        run_cmd(["sudo", "chown", f"{user}:{user}", snmp_path])
        run_cmd(["sudo", "chmod", "644", snmp_path])

    print(f"\n  \033[92m✓ File ownership and permissions set.\033[0m")

    # ── SSH hardening: SKIPPED on purpose. See the notes at the end of the script. ──
    print("\n  \033[93m⚠ SSH hardening skipped — see the manual steps printed at the end.\033[0m")

    # ── Troubleshooting hints ──
    print("\n  \033[90mTroubleshooting:\033[0m")
    print("  \033[90m  Check container status:  docker ps\033[0m")
    print("  \033[90m  View Activepieces logs: docker logs activepieces-ntt --tail 20\033[0m")
    print("  \033[90m  View NetBox logs:       docker logs netbox-ntt --tail 20\033[0m")
    print("  \033[90m  Reload Prometheus:      curl -k -X POST https://localhost:9090/-/reload\033[0m")
    print()
    print("  \033[93m⚠ Post-deploy steps:\033[0m")
    print("  \033[93m  1. Replace prometheus/netbox.token with a real NetBox API token\033[0m")
    print("  \033[93m  2. Reload Prometheus after updating the token\033[0m")
    print("  \033[93m  3. Start netbox-worker and netbox-housekeeping if not auto-started:\033[0m")
    print("  \033[93m     docker start netbox-worker-ntt netbox-housekeeping-ntt\033[0m")


# ═══════════════════════════════════════════════════════════════════════════════
# Pre-flight checks
# ═══════════════════════════════════════════════════════════════════════════════

def preflight_checks():
    """Verify the environment before starting the deployment."""
    print_banner("Pre-flight Checks")

    errors: list[str] = []

    # Must be root or have sudo
    if os.geteuid() != 0:
        try:
            subprocess.run(["sudo", "-n", "true"], check=True, capture_output=True)
            print("  \033[92m✓ sudo access available\033[0m")
        except (subprocess.CalledProcessError, FileNotFoundError):
            errors.append("This script requires sudo (either run as root or have passwordless sudo).")

    # Check OS (simple check)
    if not os.path.exists("/etc/os-release"):
        print("  \033[93m⚠ Cannot determine OS — proceeding anyway.\033[0m")
    else:
        with open("/etc/os-release") as f:
            content = f.read()
        if "ubuntu" not in content.lower() and "debian" not in content.lower():
            print("  \033[93m⚠ OS may not be Ubuntu/Debian — proceeding anyway.\033[0m")
        else:
            print("  \033[92m✓ Ubuntu/Debian detected\033[0m")

    # Check internet connectivity
    try:
        subprocess.run(
            ["ping", "-c", "1", "-W", "3", "8.8.8.8"],
            check=True, capture_output=True, timeout=5,
        )
        print("  \033[92m✓ Internet connectivity OK\033[0m")
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        errors.append("No internet connectivity — cannot download packages or images.")

    # Check disk space (at least 20 GB free)
    try:
        stat = shutil.disk_usage("/")
        free_gb = stat.free / (1024 ** 3)
        if free_gb < 20:
            errors.append(f"Low disk space: only {free_gb:.1f} GB free on /. At least 20 GB recommended.")
        else:
            print(f"  \033[92m✓ Disk space: {free_gb:.1f} GB free\033[0m")
    except Exception:
        print("  \033[93m⚠ Could not check disk space.\033[0m")

    # Check memory (at least 4 GB)
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    mem_kb = int(line.split()[1])
                    mem_gb = mem_kb / (1024 ** 2)
                    if mem_gb < 4:
                        errors.append(f"Low memory: only {mem_gb:.1f} GB. At least 4 GB recommended.")
                    else:
                        print(f"  \033[92m✓ Memory: {mem_gb:.1f} GB\033[0m")
                    break
    except Exception:
        print("  \033[93m⚠ Could not check memory.\033[0m")

    # Check if docker is already installed (conflict warning)
    if shutil.which("docker"):
        print("  \033[93m⚠ Docker already installed — will upgrade if needed.\033[0m")
    else:
        print("  \033[92m✓ Docker not yet installed — will install.\033[0m")

    if errors:
        print("\n  \033[91mPre-flight checks FAILED:\033[0m")
        for err in errors:
            print(f"    • {err}")
        if not confirm_step("Some checks failed. Continue anyway?"):
            sys.exit(1)
    else:
        print("\n  \033[92m✔ All pre-flight checks passed!\033[0m")





# ═══════════════════════════════════════════════════════════════════════════════
# End-of-script notes — manual steps that the script does not perform
# ═══════════════════════════════════════════════════════════════════════════════

def print_deferred_notes() -> None:
    """Print requirements the operator must handle manually."""
    print_banner("MANUAL STEPS REQUIRED — SSH Hardening (not applied by script)")

    print("  \033[93mThe script did NOT change SSH settings. To harden SSH yourself:\033[0m\n")
    print("  \033[93m1. Before anything else, confirm key-based login works from a SECOND\033[0m")
    print("  \033[93m   terminal session. Otherwise you can lock yourself out.\033[0m\n")
    print("  \033[93m2. Create /etc/ssh/sshd_config.d/ie-hardening.conf with this content")
    print("     (replace <your-user> with your Linux username):\033[0m\n")
    print("     PasswordAuthentication no")
    print("     PermitRootLogin no")
    print("     AllowUsers <your-user>")
    print("     MaxAuthTries 3")
    print("     LoginGraceTime 30")
    print("     PubkeyAcceptedKeyTypes ssh-ed25519,rsa-sha2-512,rsa-sha2-256")
    print("     HostKeyAlgorithms ssh-ed25519,rsa-sha2-512,rsa-sha2-256")
    print("     X11Forwarding no\n")
    print("  \033[93m3. Validate the config, then restart SSH:\033[0m")
    print("     sudo sshd -t && sudo systemctl restart ssh\n")
    print("  \033[93m4. Keep your current session open and test a new login before closing it.\033[0m\n")


# ═══════════════════════════════════════════════════════════════════════════════
# Main entry point
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    print("")
    print("  ╔══════════════════════════════════════════════════════════════╗")
    print("  ║          Insights Engine NTT — Monitoring Stack Deployer       ║")
    print("  ╚══════════════════════════════════════════════════════════════╝")
    print()

    # Pre-flight
    preflight_checks()
    if not confirm_step("Proceed with full deployment?"):
        print("  Deployment cancelled by user.")
        sys.exit(0)

    # ── Phase 1 ──────────────────────────────────────────────────────────
    phase_system_update()

    # ── Phase 1b ──────────────────────────────────────────────────────────
    # Prompt for Git clone URL before cloning
    prompt_git_url()
    if not confirm_step("Ready to clone the repository?"):
        print("  Skipping clone. Ensure repo is already cloned.")
    else:
        phase_clone_repo()

    # ── Phase 1c ──────────────────────────────────────────────────────────
    if not confirm_step("Ready to configure environment variables, SNMP credentials, and Alertmanager webhook?"):
        print("  Skipping configuration. Ensure .env and alertmanager.yml exist.")
    else:
        phase_configure_environment()

    # ── Phase 2 ──────────────────────────────────────────────────────────
    if not confirm_step("Ready to install Docker?"):
        print("  Skipping Docker install. Ensure Docker is already installed.")
    else:
        phase_install_docker()

    # ── Phase 3 ──────────────────────────────────────────────────────────
    if not confirm_step("Ready to pull container images? (This may take 5-10 minutes)"):
        print("  Skipping pull.")
    else:
        phase_pull_images()

    # ── Phase 4 ──────────────────────────────────────────────────────────
    if not confirm_step("Ready to start containers? (This takes about 15 minutes - select Y and grab a coffee)"):
        print("  Skipping container startup.")
    else:
        phase_start_containers()

    # ── Phase 5 ──────────────────────────────────────────────────────────
    if not confirm_step("Ready to finalize (ownership fix, troubleshooting hint)?"):
        print("  Skipping finalization.")
    else:
        phase_finalize()

    print("\n  \033[94mDeployment complete.\033[0m\n")

    print_deferred_notes()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n  \033[93mDeployment cancelled by user (Ctrl+C).\033[0m")
        sys.exit(1)
    except Exception as e:
        print(f"\n  \033[91mDeployment failed: {e}\033[0m")
        sys.exit(1)