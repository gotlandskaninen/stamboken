#!/usr/bin/env bash
# nginx -t med nginx/nginx.main och en riktig vhost-fil, med påhittade
# certifikat på de sökvägar vhosten pekar ut. herdbook-deploy kör inte själv
# nginx -t före omstarten, så ett syntaxfel skulle annars synas först i drift.
# Användning: scripts/check-nginx-prod-config.sh [vhost]   (standard: produktionsvhosten)
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
vhost=$(realpath "${1:-$root/nginx/production/herdbook-production.conf}")
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
openssl req -x509 -newkey rsa:2048 -nodes -days 1 -subj /CN=test \
	-keyout "$tmp/key.pem" -out "$tmp/cert.pem" 2>/dev/null
openssl dhparam -dsaparam -out "$tmp/dhparam.pem" 2048 2>/dev/null
mounts=(-v "$tmp/dhparam.pem:/etc/letsencrypt/dhparams/dhparam.pem:ro")
# Aktiva (ej bortkommenterade) certifikatvägar i vhosten.
while read -r kind path; do
	src="$tmp/cert.pem"
	[ "$kind" = ssl_certificate_key ] && src="$tmp/key.pem"
	mounts+=(-v "$src:${path%;}:ro")
done < <(grep -E '^\s*ssl_certificate(_key)?\s' "$vhost" | sed -E 's/^\s+//' | sort -u)
docker run --rm --entrypoint nginx \
	--add-host api:127.0.0.1 --add-host api-test:127.0.0.1 --add-host next-app:127.0.0.1 \
	-v "$root/nginx/nginx.main:/etc/nginx/nginx.conf:ro" \
	-v "$vhost:/etc/nginx/conf.d/herdbook.conf:ro" \
	"${mounts[@]}" nginx:1.27-alpine -t
