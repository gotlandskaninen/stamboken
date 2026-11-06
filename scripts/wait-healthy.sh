#!/bin/bash
# Väntar tills varje angiven compose-tjänst kör och (om den har healthcheck)
# är healthy. Exit 1 vid timeout — även för containrar som startar om eller
# har avslutats, som en grep efter "unhealthy" missar.
#
# Användning: wait-healthy.sh <timeout-sekunder> <tjänst>...
# Compose-filen tas från COMPOSE_FILE (miljövariabel) som vanligt.

set -u
timeout="$1"
shift
deadline=$((SECONDS + timeout))

while :; do
	bad=""
	for svc in "$@"; do
		line=$(docker compose ps --all --format '{{.State}} {{.Health}}' "$svc" 2>/dev/null | head -1)
		state="${line%% *}"
		health="${line#* }"
		if [ "$state" != running ] || { [ -n "$health" ] && [ "$health" != healthy ]; }; then
			bad="$bad $svc(${line:-saknas})"
		fi
	done
	if [ -z "$bad" ]; then
		echo "  All services healthy: $*"
		exit 0
	fi
	if [ "$SECONDS" -ge "$deadline" ]; then
		echo "ERROR: not healthy after ${timeout}s:$bad"
		exit 1
	fi
	echo "  Waiting:$bad"
	sleep 5
done
