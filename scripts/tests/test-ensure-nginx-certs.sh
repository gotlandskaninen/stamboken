#!/usr/bin/env bash
#
# Tests for ensure-nginx-certs.sh. No real docker needed: a fake `docker` on
# PATH stubs `compose ps`, `inspect`, and `compose exec ... certbot`. Real
# (self-signed) certs are generated so the openssl expiry check is exercised.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="$HERE/../ensure-nginx-certs.sh"

pass=0
fail=0
check() { # desc expected actual
  if [ "$2" = "$3" ]; then echo "ok   - $1"; pass=$((pass + 1))
  else echo "FAIL - $1 (expected '$2', got '$3')"; fail=$((fail + 1)); fi
}

make_conf() { # path
  cat > "$1" <<'EOF'
server {
    server_name a.example;
    ssl_certificate /etc/letsencrypt/live/a.example/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/a.example/privkey.pem;
}
server {
    server_name b.example;
    ssl_certificate  /etc/letsencrypt/live/b.example/fullchain.pem;
}
server {
    server_name a-alias;
    ssl_certificate /etc/letsencrypt/live/a.example/fullchain.pem;
    # ssl_certificate /etc/letsencrypt/live/ghost.example/fullchain.pem;  commented out
}
EOF
}

# Valid self-signed cert pair in $LE/live/<host>/.
make_cert() { # le_dir host
  local d="$1/live/$2"; mkdir -p "$d"
  openssl req -x509 -newkey rsa:2048 -nodes -days 30 -subj "/CN=$2" \
    -keyout "$d/privkey.pem" -out "$d/fullchain.pem" >/dev/null 2>&1
}

# Fake docker: certbot exec returns $CERTBOT_RESULT (default 0). nginx is
# reported running unless NGINX_RUNNING=false.
make_fake_docker() { # bin_dir
  mkdir -p "$1"
  cat > "$1/docker" <<'EOF'
#!/usr/bin/env bash
if [ "$1" = "compose" ] && [ "$2" = "ps" ]; then
  [ "${NGINX_RUNNING:-true}" = "true" ] && echo "fakecid"; exit 0
fi
if [ "$1" = "inspect" ]; then echo "${NGINX_RUNNING:-true}"; exit 0; fi
if [ "$1" = "compose" ] && [ "$2" = "exec" ]; then exit "${CERTBOT_RESULT:-0}"; fi
exit 0
EOF
  chmod +x "$1/docker"
}

run() { # workdir le_dir conf  (extra env via caller) -> sets $rc
  ( cd "$1" && PATH="$bin:$PATH" LETSENCRYPT_DIR="$2" CERTBOT_EMAIL="${EMAIL:-t@x.example.com}" \
      bash "$SCRIPT" "$3" >/dev/null 2>&1 )
  rc=$?
}

# ── unit: referenced_hosts parses, strips comments, dedups ─────────────
work="$(mktemp -d)"; make_conf "$work/nginx.conf"
# shellcheck source=/dev/null
source "$SCRIPT"   # source guard prevents main from running
set +e             # the sourced script enabled `set -e`; we check exit codes by hand
got="$(referenced_hosts "$work/nginx.conf" | paste -sd, -)"
check "referenced_hosts extracts, dedups, ignores commented line" "a.example,b.example" "$got"

# ── unit: normalize_email strips quotes / CR / whitespace ──────────────
check "normalize_email strips double quotes"   "a@b.example.com" "$(normalize_email '"a@b.example.com"')"
check "normalize_email strips single quotes"   "a@b.example.com" "$(normalize_email "'a@b.example.com'")"
check "normalize_email strips trailing CR"     "a@b.example.com" "$(normalize_email "$(printf 'a@b.example.com\r')")"
check "normalize_email strips surrounding ws"  "a@b.example.com" "$(normalize_email '   a@b.example.com  ')"

# ── integration: all certs present + valid → exit 0 ────────────────────
work="$(mktemp -d)"; bin="$work/bin"; make_conf "$work/nginx.conf"; make_fake_docker "$bin"
make_cert "$work/le" a.example; make_cert "$work/le" b.example
run "$work" le "$work/nginx.conf"
check "all certs present + valid → exit 0" "0" "$rc"

# ── integration: one missing, issuance succeeds → exit 0 ───────────────
work="$(mktemp -d)"; bin="$work/bin"; make_conf "$work/nginx.conf"; make_fake_docker "$bin"
make_cert "$work/le" a.example
CERTBOT_RESULT=0 run "$work" le "$work/nginx.conf"
check "missing cert + issuance OK → exit 0" "0" "$rc"

# ── integration: one missing, issuance fails → abort (exit 1) ──────────
work="$(mktemp -d)"; bin="$work/bin"; make_conf "$work/nginx.conf"; make_fake_docker "$bin"
make_cert "$work/le" a.example
CERTBOT_RESULT=1 run "$work" le "$work/nginx.conf"
check "missing cert + issuance FAIL → abort exit 1" "1" "$rc"

# ── integration: fullchain present but privkey MISSING → unusable ──────
work="$(mktemp -d)"; bin="$work/bin"; make_conf "$work/nginx.conf"; make_fake_docker "$bin"
make_cert "$work/le" a.example
mkdir -p "$work/le/live/b.example"
cp "$work/le/live/a.example/fullchain.pem" "$work/le/live/b.example/fullchain.pem"  # no privkey
CERTBOT_RESULT=1 run "$work" le "$work/nginx.conf"
check "fullchain present, privkey missing → treated unusable → abort exit 1" "1" "$rc"

# ── integration: nginx down → cannot issue → abort (exit 1) ────────────
work="$(mktemp -d)"; bin="$work/bin"; make_conf "$work/nginx.conf"; make_fake_docker "$bin"
make_cert "$work/le" a.example
NGINX_RUNNING=false run "$work" le "$work/nginx.conf"
check "missing cert + nginx down → abort exit 1" "1" "$rc"

echo ""
echo "passed: $pass, failed: $fail"
[ "$fail" -eq 0 ]
