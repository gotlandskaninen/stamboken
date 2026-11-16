#!/usr/bin/env bash
#
# The report link's nginx rules (step 3, R6/R6b/FA6): every nginx config parses, and a synthetic link through
# the real proxy chain never reaches an access or error log, raw or percent-encoded, also when the upstream is down.
# Needs docker and openssl; the nginx image comes from NGINX_IMAGE.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$HERE/../.."
IMAGE="${NGINX_IMAGE:-nginx:1.27-alpine}"
MAC="ZZZZSyntheticMacZZZZZZ" # 22 characters, shaped like a link token's mac
TOKEN="4711.$MAC"
NAME="nginx-rapport-test-$$"
TMP="$(mktemp -d)"
cleanup() { docker rm -f "$NAME" >/dev/null 2>&1; rm -rf "$TMP"; }
trap cleanup EXIT

pass=0
fail=0
check() { # desc expected actual
  if [ "$2" = "$3" ]; then echo "ok   - $1"; pass=$((pass + 1))
  else echo "FAIL - $1 (expected '$2', got '$3')"; fail=$((fail + 1)); fi
}

# A directory with a throwaway certificate for every ssl_certificate path in the config, and a wrapper
# nginx.conf that includes it, as the nginx-certbot image does.
prepare() { # conf dir
  local dir="$2" live
  mkdir -p "$dir/le/dhparams"
  openssl dhparam -dsaparam -out "$dir/le/dhparams/dhparam.pem" 2048 >/dev/null 2>&1
  for live in $(grep -hoE '^[[:space:]]*ssl_certificate[[:space:]]+[^;]+' "$1" | awk '{print $2}' | xargs -n1 dirname | sort -u); do
    mkdir -p "$dir/le/${live#/etc/letsencrypt/}"
    openssl req -x509 -newkey rsa:2048 -nodes -days 2 -subj "/CN=localhost" \
      -keyout "$dir/le/${live#/etc/letsencrypt/}/privkey.pem" -out "$dir/le/${live#/etc/letsencrypt/}/fullchain.pem" >/dev/null 2>&1
  done
  printf 'events {}\nhttp {\n    include /conf/herdbook.conf;\n}\n' > "$dir/nginx.conf"
}

run_args() { # conf dir
  echo --add-host api:127.0.0.1 --add-host api-test:127.0.0.1 --add-host next-app:127.0.0.1 \
    -v "$1:/conf/herdbook.conf:ro" -v "$2/nginx.conf:/etc/nginx/nginx.conf:ro" -v "$2/le:/etc/letsencrypt:ro"
}

for conf in nginx/herdbook.conf nginx/herdbook-local-production.conf nginx/production/herdbook-production.conf; do
  dir="$TMP/$(echo "$conf" | tr / _)"
  prepare "$ROOT/$conf" "$dir"
  # shellcheck disable=SC2046
  out="$(docker run --rm $(run_args "$ROOT/$conf" "$dir") "$IMAGE" nginx -t 2>&1)"
  check "nginx -t: $conf" "0" "$([ $? -eq 0 ] && echo 0 || { echo "$out" | tail -3; echo 1; })"
done

# The proxy chain: no upstream listens, so every request that reaches one ends in a 502 and an error-log line.
conf=nginx/herdbook-local-production.conf
dir="$TMP/chain"
prepare "$ROOT/$conf" "$dir"
# shellcheck disable=SC2046
docker run -d --name "$NAME" $(run_args "$ROOT/$conf" "$dir") "$IMAGE" >/dev/null
for _ in $(seq 1 30); do
  [ "$(docker exec "$NAME" curl -sk -o /dev/null -w '%{http_code}' https://127.0.0.1/rapport/ogiltig)" != "000" ] && break
  sleep 1
done

status() { # host path -> status code, the path sent as is
  docker exec "$NAME" curl -sk --path-as-is -o /dev/null -w '%{http_code}' -H "Host: $1" "https://127.0.0.1$2"
}
check "link, upstream down: 502" "502" "$(status localhost "/rapport/$TOKEN")"
check "upper case link: 502" "502" "$(status localhost "/Rapport/$TOKEN")"
check "encoded prefix: 502" "502" "$(status localhost "/%72apport/$TOKEN")"
check "direct exchange: 404" "404" "$(status localhost "/api/v2/rapport/oppna/$TOKEN")"
check "direct exchange under api-test: 404" "404" "$(status localhost "/api-test/v2/rapport/oppna/$TOKEN")"
check "link/..%2Fogiltig does not reach the page with the token: 303" "303" "$(status localhost "/rapport/$TOKEN/..%2Fogiltig")"
check "legacy host refuses the link: 404" "404" "$(status stamboken.localhost "/rapport/$TOKEN")"
check "legacy host refuses the exchange: 404" "404" "$(status test.localhost "/api/v2/rapport/oppna/$TOKEN")"

logs="$(docker logs "$NAME" 2>&1)"
check "no mac in any nginx log" "0" "$(printf '%s\n' "$logs" | grep -c "$MAC")"
check "no encoded mac in any nginx log" "0" "$(printf '%s\n' "$logs" | grep -ci "%7[0-9a-f]apport\|4711\.")"
check "the masked path is logged" "yes" "$(printf '%s\n' "$logs" | grep -q '/rapport/\*\*\*' && echo yes || echo no)"

echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ]
