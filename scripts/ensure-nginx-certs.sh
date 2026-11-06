#!/usr/bin/env bash
#
# Pre-flight: make sure every TLS host referenced by the nginx config has a
# certificate on disk BEFORE nginx is (re)created.
#
# Why: jonasal/nginx-certbot, on container (re)start, scans the mounted config
# for `ssl_certificate /etc/letsencrypt/live/<host>/...` directives. If ANY
# referenced cert is missing it renames the WHOLE config file to `*.nokey`
# (which the `*.conf` include then skips), so nginx loads NO vhosts at all — a
# single missing cert takes every host down (e.g. a newly added host without a
# pre-issued cert), and `nginx -t` still passes (it tests the .nokey-stripped
# config), so it fails silently.
#
# This script closes that gap before the recreate:
#   1. parse the hosts referenced by the config,
#   2. for each host whose cert is missing, try to issue it on its own
#      (single -d webroot challenge against the already-running nginx — this
#      validates fine even when OTHER hosts' DNS points elsewhere, unlike the
#      bundled all-hosts challenge nginx-certbot runs at startup),
#   3. if any referenced host STILL lacks a cert, exit non-zero so the caller
#      aborts BEFORE recreating nginx. The running site is left untouched —
#      a loud, safe failure instead of a silent full outage.
#
# Usage: ensure-nginx-certs.sh [path/to/nginx.conf]
# Env:
#   CERTBOT_EMAIL    contact email (falls back to CERTBOT_EMAIL= in ./.env)
#   LETSENCRYPT_DIR  host path of the /etc/letsencrypt mount (default: letsencrypt)
#   NGINX_SERVICE    compose service name (default: nginx)
#   ACME_WEBROOT     webroot the nginx-certbot redirector serves (default: /var/www/letsencrypt)
set -euo pipefail

LE_DIR="${LETSENCRYPT_DIR:-letsencrypt}"
NGINX_SERVICE="${NGINX_SERVICE:-nginx}"
ACME_WEBROOT="${ACME_WEBROOT:-/var/www/letsencrypt}"

log() { echo "ensure-nginx-certs: $*"; }

# Normalize a value read from .env: strip CR (CRLF files), surrounding quotes
# and surrounding whitespace, so certbot gets a clean -m argument.
normalize_email() {
  printf '%s' "${1:-}" | tr -d '\r' \
    | sed -E 's/^[[:space:]]*//; s/[[:space:]]*$//; s/^"(.*)"$/\1/; s/^'\''(.*)'\''$/\1/'
}

# Unique TLS hosts referenced as `ssl_certificate /etc/letsencrypt/live/<host>/`.
# Comments are stripped first so a commented-out `# ssl_certificate ...` line is
# not mistaken for a referenced host. Stable first-seen order, de-duplicated.
referenced_hosts() {
  local conf="$1"
  sed 's/#.*//' "$conf" \
    | grep -oE 'ssl_certificate[[:space:]]+/etc/letsencrypt/live/[^/]+/' \
    | sed -E 's#.*/live/([^/]+)/#\1#' \
    | awk '!seen[$0]++'
}

# A host's cert is usable only if BOTH files nginx references exist and are
# non-empty — nginx-certbot sidelines the WHOLE config if either the fullchain
# (ssl_certificate) or the private key (ssl_certificate_key) is missing, so
# checking fullchain.pem alone would let a half-written live/ dir pass green and
# still take every host down. When openssl is available we also reject an
# already-expired leaf cert (a present-but-expired cert serves invalid TLS).
# NOTE: assumes one single-host cert per host (live/<host>/ == server_name),
# which matches this deployment; SAN/wildcard consolidation would need rework.
cert_usable() {
  local fc="$LE_DIR/live/$1/fullchain.pem"
  local pk="$LE_DIR/live/$1/privkey.pem"
  [ -s "$fc" ] && [ -s "$pk" ] || return 1
  if command -v openssl >/dev/null 2>&1; then
    openssl x509 -checkend 0 -noout -in "$fc" >/dev/null 2>&1 || return 1
  fi
  return 0
}

# `docker compose ps --status running -q` lists only the RUNNING container ids
# for the service (empty if none). Checking it non-empty avoids the multi-id +
# `docker inspect` quoting trap: `ps -q` alone can return several ids (stale or
# stopped containers), and a newline-joined "$cid" makes `docker inspect` fail
# and falsely report nginx down — aborting a healthy deploy.
nginx_running() {
  [ -n "$(docker compose ps --status running -q "$NGINX_SERVICE" 2>/dev/null || true)" ]
}

issue_cert() {
  local host="$1"
  # --staging mirrors the nginx-certbot container's ACME env (STAGING=1 in .env),
  # so we never mint a prod cert a staging container would refuse, or vice versa.
  docker compose exec -T "$NGINX_SERVICE" certbot certonly --webroot \
    -w "$ACME_WEBROOT" -d "$host" \
    --non-interactive --agree-tos --no-eff-email -m "$CERTBOT_EMAIL" \
    ${CERTBOT_STAGING:+--staging}
}

main() {
  local conf="${1:-nginx/production/herdbook-production.conf}"

  if [ ! -f "$conf" ]; then
    log "config not found: $conf"; return 1
  fi

  # CERTBOT_EMAIL / STAGING: explicit env wins, else read from ./.env (the same
  # vars nginx-certbot itself uses), so the script needs no extra wiring. The
  # email is normalized — strip a trailing CR (CRLF .env files), surrounding
  # quotes and whitespace — otherwise certbot gets a malformed -m argument and
  # every issuance fails, which would spuriously abort a healthy deploy.
  if [ -z "${CERTBOT_EMAIL:-}" ] && [ -f .env ]; then
    CERTBOT_EMAIL="$(grep -E '^CERTBOT_EMAIL=' .env | head -1 | cut -d= -f2- || true)"
  fi
  CERTBOT_EMAIL="$(normalize_email "${CERTBOT_EMAIL:-}")"
  if [ -z "${CERTBOT_STAGING:-}" ] && [ -f .env ]; then
    local stg
    stg="$(grep -E '^STAGING=' .env | head -1 | cut -d= -f2- | tr -dc '0-9' || true)"
    [ "$stg" = "1" ] && CERTBOT_STAGING=1
  fi

  local hosts=() missing=()
  mapfile -t hosts < <(referenced_hosts "$conf")

  if [ "${#hosts[@]}" -eq 0 ]; then
    log "no TLS hosts referenced in $conf — nothing to do"; return 0
  fi
  log "TLS hosts referenced: ${hosts[*]}"

  for h in "${hosts[@]}"; do
    if cert_usable "$h"; then
      log "  OK  $h — cert present and valid"; continue
    fi
    log "  ..  $h — cert missing/unusable"
    if [ -z "${CERTBOT_EMAIL:-}" ]; then
      log "      ! CERTBOT_EMAIL unset — cannot issue"; missing+=("$h"); continue
    fi
    if ! nginx_running; then
      log "      ! nginx ($NGINX_SERVICE) not running — cannot run webroot challenge"
      missing+=("$h"); continue
    fi
    if issue_cert "$h"; then
      log "      OK  $h — issued"
    else
      log "      XX  $h — issuance FAILED (DNS not pointed here yet?)"; missing+=("$h")
    fi
  done

  if [ "${#missing[@]}" -gt 0 ]; then
    log ""
    log "ABORT: these hosts still lack a usable cert: ${missing[*]}"
    log "Recreating nginx now would rename the whole config to .nokey and take EVERY"
    log "host down. For each host either:"
    log "  - point its DNS at this server, or pre-issue its cert with"
    log "      docker compose exec $NGINX_SERVICE certbot certonly --webroot -w $ACME_WEBROOT -d <host>"
    log "  - or comment out its server block in the nginx config until DNS is ready"
    log "then re-run the deploy. The running site has not been touched."
    return 1
  fi

  log "all referenced hosts have certs — safe to recreate nginx"
  return 0
}

if [ "${BASH_SOURCE[0]}" = "${0}" ]; then
  main "$@"
fi
