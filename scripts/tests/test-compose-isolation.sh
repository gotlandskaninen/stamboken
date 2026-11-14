#!/usr/bin/env bash
#
# Tests that the compose files keep local and demo stacks away from production
# data (R097). No container is started: `docker compose config` resolves each
# file (env_file included) and the checks read the resolved JSON.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$HERE/../.."

pass=0
fail=0
check() { # desc expected actual
  if [ "$2" = "$3" ]; then echo "ok   - $1"; pass=$((pass + 1))
  else echo "FAIL - $1 (expected '$2', got '$3')"; fail=$((fail + 1)); fi
}

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
export CERTBOT_EMAIL=ci@example.invalid # required by docker-compose.production.yml

# resolve <compose-file> <project-dir>: writes <project-dir>/resolved.json. Env
# files are not in git, so any the file references and the dir lacks are created
# empty.
resolve() {
  local file="$1" dir="$2" env
  mkdir -p "$dir/.docker"
  cp "$file" "$dir/"
  while read -r env; do
    [ -e "$dir/$env" ] || : > "$dir/$env"
  done < <(grep -ohE '(\./)?\.docker/[A-Za-z0-9_.-]+\.env' "$file" | sed 's|^\./||' | sort -u)
  if ! docker compose -f "$dir/$(basename "$file")" config --format json > "$dir/resolved.json" 2> "$dir/resolve.err"; then
    echo "ABORT: docker compose config failed for $file: $(cat "$dir/resolve.err")" >&2; exit 2
  fi
}

# q <project-dir> <python expression>: evaluates it over the resolved config `c`
# (`env(s)` = effective environment of service s).
q() {
  python3 -I -c '
import json, sys
c = json.load(open(sys.argv[1] + "/resolved.json"))
env = lambda s: c["services"][s].get("environment") or {}
up = sys.argv[1] + "/uppladdningar"  # the upload dir of this project
sk = sys.argv[1] + "/skyddat"  # the private dir of the intake queue
# a path that is the dir d, inside it, or a parent of it
reaches = lambda s, d: bool(s) and (s.rstrip("/") == d or s.startswith(d + "/") or d.startswith(s.rstrip("/") + "/"))
touches = lambda s: reaches(s, up)
print(eval(sys.argv[2]))' "$1" "$2"
}

# ── R097: local stacks must not reach the prod bucket, signing key or mailbox ─
# The local-production bootstrap (stamboken-drift) copies the prod api-variables.env
# (S3 and signing settings) into .docker/, a file every compose file reads.
cat > "$work/prod-api-variables.env" <<'EOF'
KEEP_ME=1
S3_ENDPOINT=https://prod-s3.invalid
S3_BUCKET=prodbucket
S3_ACCESSKEY=PRODKEY-SENTINEL
S3_SECRETKEY=PRODSECRET-SENTINEL
PDF_SIGNING_KEY=/config/pdf_signing_key.pem
PDF_SIGNING_CA=/config/pdf_signing_ca.pem
INLASNING_GMAIL=on
EOF

# 2. Defence in depth: even a hand-edited .docker/api-variables.env holding prod
# values must not reach api or api-test, since `environment` overrides `env_file`.
proj="$work/r097/dirty"
mkdir -p "$proj/.docker"
cp "$work/prod-api-variables.env" "$proj/.docker/api-variables.env"
resolve "$ROOT/docker-compose.local-production.yml" "$proj"
for svc in api api-test; do
  for kv in S3_ENDPOINT=http://s3backend:9000 S3_BUCKET=test S3_ACCESSKEY=accesskeytest S3_SECRETKEY=secretkeytest \
    PDF_SIGNING_KEY=certs/key.pem PDF_SIGNING_CA=certs/ca.pem CERT_DEMO_WATERMARK=true INLASNING_GMAIL=off; do
    check "R097 local-production $svc: ${kv%%=*} is pinned" "${kv#*=}" "$(q "$proj" "env('$svc').get('${kv%%=*}')")"
  done
done

# ── R071: the passwordless (trust) local-production Postgres holds the prod dump ─
# A port published without a host IP binds 0.0.0.0, so anyone who can reach the
# laptop could connect without a password. Only loopback publishes are allowed.
check "R071 local-production database publishes no port beyond loopback" "[]" \
  "$(q "$work/r097/dirty" '[p for p in c["services"]["database"].get("ports", []) if p.get("host_ip") not in ("127.0.0.1", "::1")]')"

# ── Dev and local-production stacks: nothing but nginx is reachable off-host ─
# The dev Postgres uses trust auth, and api/next-app bypass nginx (which itself
# stays on all interfaces, so the dev API is still reachable through it). A port
# published without a host IP binds 0.0.0.0, so only loopback publishes are allowed.
for f in docker-compose docker-compose.local-production; do
  resolve "$ROOT/$f.yml" "$work/ports-$f"
  check "$f publishes no port beyond loopback except nginx" "{}" \
    "$(q "$work/ports-$f" "{n: o for n, s in c['services'].items() if n != 'nginx' for o in [[p for p in s.get('ports', []) if p.get('host_ip') not in ('127.0.0.1', '::1')]] if o}")"
done

# ── R072: the demo API must not write into the production upload dir ───
# api (herdbook DB) and api-test (demo DB) bind the same host ./uppladdningar,
# and a photo upload writes the fixed path kaniner/<number>.jpg, which nginx
# serves. A demo upload would replace the production photo. api keeps its
# writable mount; only the demo's is read-only.
resolve "$ROOT/docker-compose.production.yml" "$work/r072"
writable_uploads() { # service -> its writable binds that reach the upload dir (as target, source, or parent of it)
  q "$work/r072" "[v['target'] for v in c['services']['$1']['volumes'] if not v.get('read_only') and (v['target'] == '/app/uppladdningar' or v['target'].startswith('/app/uppladdningar/') or touches(v.get('source', '')))]"
}
check "R072 production api-test has no writable uppladdningar mount" "[]" "$(writable_uploads api-test)"
check "R072 production api still mounts uppladdningar writable" "['/app/uppladdningar']" "$(writable_uploads api)"

# ── Demo sessions: production refuses logins made on api-test ───────────
# DEMO_INSTANCE=true marks api-test's logins; on `api` it would switch off the
# refusal, and without it on api-test its logins would be production sessions.
check "production api does not set DEMO_INSTANCE" "None" "$(q "$work/r072" "env('api').get('DEMO_INSTANCE')")"
check "production api-test sets DEMO_INSTANCE=true" "true" "$(q "$work/r072" "env('api-test').get('DEMO_INSTANCE')")"

# ── The intake queue's originals are never public ───────────────────────
# nginx serves all of uppladdningar without login, so the private dir must lie
# outside it, and only the api may mount it: never nginx.
for f in docker-compose docker-compose.local-production docker-compose.production; do
  proj="$work/private-$f"
  resolve "$ROOT/$f.yml" "$proj"
  check "$f: only api mounts skyddat" "['api']" \
    "$(q "$proj" "sorted(n for n, s in c['services'].items() if any(reaches(v.get('source', ''), sk) for v in s.get('volumes', [])))")"
  check "$f: api mounts skyddat at PRIVATE_UPLOAD_FOLDER" "True" \
    "$(q "$proj" "[v['target'] for v in c['services']['api']['volumes'] if reaches(v.get('source', ''), sk)] == [env('api').get('PRIVATE_UPLOAD_FOLDER', '/app/skyddat')]")"
  check "$f: PRIVATE_UPLOAD_FOLDER is not under UPLOAD_FOLDER" "False" \
    "$(q "$proj" "reaches(env('api').get('PRIVATE_UPLOAD_FOLDER', '/app/skyddat'), env('api').get('UPLOAD_FOLDER', '/app/uppladdningar'))")"
  check "$f: skyddat is not in the upload dir" "False" "$(q "$proj" "touches(sk)")"
done

# ── The image reading's model server: opt-in, internal, at most 6 CPUs ─────
# Ollama has no login, so it publishes no port; only the api reaches it. It starts
# only with the profile tolkning, so neither a plain `up` nor the e2e stack (named
# services, none depending on it) nor the pytest stack starts it.
check "docker-compose (the pytest stack's base) has no ollama" "False" \
  "$(q "$work/ports-docker-compose" "'ollama' in c['services']")"
for f in docker-compose.local-production docker-compose.production; do
  check "$f: ollama is not started without the tolkning profile" "False" \
    "$(q "$work/private-$f" "'ollama' in c['services']")"
  proj="$work/ollama-$f"
  COMPOSE_PROFILES=tolkning resolve "$ROOT/$f.yml" "$proj"
  check "$f: ollama publishes no port" "[]" "$(q "$proj" "c['services']['ollama'].get('ports', [])")"
  check "$f: ollama has at most 6 CPUs" "6.0" "$(q "$proj" "float(c['services']['ollama'].get('cpus', 0))")"
  check "$f: nothing depends on ollama" "[]" \
    "$(q "$proj" "[n for n, s in c['services'].items() if 'ollama' in (s.get('depends_on') or {})]")"
done

echo ""
echo "passed: $pass, failed: $fail"
[ "$fail" -eq 0 ]
