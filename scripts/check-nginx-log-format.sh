#!/usr/bin/env bash
# Provar nginx/nginx.main mot en riktig nginx: konfigen ska vara giltig, och en
# frågesträng (HEMLIG) ska inte synas i åtkomstloggen, varken över http eller
# för okänt värdnamn. Kräver docker. Användning: scripts/check-nginx-log-format.sh
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
tmp=$(mktemp -d)
name=nginx-logformat-$$
trap 'docker rm -f "$name" >/dev/null 2>&1 || true; rm -rf "$tmp"' EXIT
cat >"$tmp/test.conf" <<'CONF'
server {
    listen 80 default_server;
    location / { return 200 "ok\n"; }
}
CONF
docker run -d --name "$name" \
	-v "$root/nginx/nginx.main:/etc/nginx/nginx.conf:ro" \
	-v "$tmp/test.conf:/etc/nginx/conf.d/test.conf:ro" \
	nginx:1.27-alpine >/dev/null
for _ in $(seq 20); do docker exec "$name" nginx -t >/dev/null 2>&1 && break; sleep 0.5; done
docker exec "$name" nginx -t
docker exec "$name" nginx -T 2>/dev/null | grep -q 'log_format access_json' || { echo "formatet saknas i nginx -T"; exit 1; }
docker exec "$name" sh -c 'wget -qO- "http://127.0.0.1/a/b?code=HEMLIG" >/dev/null; wget -qO- --header "Host: okant.example" "http://127.0.0.1/c?code=HEMLIG" >/dev/null'
sleep 1
logs=$(docker logs "$name" 2>&1)
if grep -q HEMLIG <<<"$logs"; then echo "HEMLIG syns i loggen:"; echo "$logs"; exit 1; fi
grep -q '"path":"/a/b"' <<<"$logs" || { echo "sökvägen saknas i loggen:"; echo "$logs"; exit 1; }
grep -q '"host":"okant.example"' <<<"$logs" || { echo "okänt värdnamn saknas:"; echo "$logs"; exit 1; }
grep '^{' <<<"$logs" | python3 -c 'import sys,json; [json.loads(l) for l in sys.stdin]'
echo "ok: åtkomstloggen är giltig JSON utan frågesträng"
