#!/usr/bin/env bash
# Shared NetBox 4.6 auth header. Source from bash scripts. Never prints the token.
# v2 (NetBox 4.5+): Authorization: Bearer nbt_<12 char key>.<40 char secret>
# v1 (deprecated in 4.6, removed in 5.0): Authorization: Token <40 hex chars>
# shellcheck shell=bash

netbox_env_value() {
  local line
  [ -f .env ] || return 0
  line="$(grep -E "^$1=" .env | tail -n1 || true)"
  line="${line#*=}"
  line="${line#\'}"
  line="${line%\'}"
  printf '%s' "$line"
}

# netbox_write_auth_header <header-file>
# The secret file is the source of truth when it exists. .env is the fallback
# for a machine that has not written secrets/prometheus/netbox.token yet.
netbox_write_auth_header() {
  local dest=$1 tok="" key="" secret=""
  if [ -n "${NETBOX_TOKEN_FILE:-}" ] && [ -s "${NETBOX_TOKEN_FILE}" ]; then
    tok="$(tr -d '\r\n' < "$NETBOX_TOKEN_FILE")"
  elif [ -s secrets/prometheus/netbox.token ] && [ "$(tr -d '\r\n' < secrets/prometheus/netbox.token)" != "unset-placeholder" ]; then
    tok="$(tr -d '\r\n' < secrets/prometheus/netbox.token)"
  else
    key="$(netbox_env_value NETBOX_SUPERUSER_API_KEY)"
    secret="$(netbox_env_value NETBOX_SUPERUSER_API_TOKEN)"
    if [ -n "$key" ] && [ -n "$secret" ]; then
      tok="nbt_${key}.${secret}"
    else
      tok="$secret"
    fi
  fi
  [ -n "$tok" ] || return 1
  case "$tok" in
    nbt_*) printf 'Authorization: Bearer %s\n' "$tok" > "$dest" ;;
    *) printf 'Authorization: Token %s\n' "$tok" > "$dest" ;;
  esac
  unset tok key secret
  return 0
}
