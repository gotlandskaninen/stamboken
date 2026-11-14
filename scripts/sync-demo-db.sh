#!/usr/bin/env bash
# Synkroniserar produktionsdatabas till demo-databas
#
# Användning:
#   ./sync-demo-db.sh                    # Synkar herdbook -> herdbook_demo
#   ./sync-demo-db.sh help               # Visa hjälp

set -Eeuo pipefail  # -E: the ERR trap reaches functions (telemetry below)

scriptdir=$(dirname "$0")

ENV_FILE="$scriptdir/../.docker/database-variables.env"
SOURCE_DB="herdbook"
TARGET_DB="herdbook_demo"

# Auto-detect database container name (works with any project/worktree name)
if [ -n "${COMPOSE_FILE:-}" ]; then
	CONTAINER=$(docker compose -f "$COMPOSE_FILE" ps -q database 2>/dev/null)
else
	# Try compose files in order: local-production, then default
	for cf in "$scriptdir/../docker-compose.local-production.yml" "$scriptdir/../docker-compose.production.yml" "$scriptdir/../docker-compose.yml"; do
		if [ -f "$cf" ]; then
			CONTAINER=$(docker compose -f "$cf" ps -q database 2>/dev/null) && break
		fi
	done
fi

if [ -z "$CONTAINER" ]; then
	echo "ERROR: Could not find running database container. Is docker compose up?" >&2
	echo "Hint: set COMPOSE_FILE env var to specify the compose file" >&2
	exit 1
fi

usage() {
	cat <<-HELP
		USAGE: $0 [help]

		Synkroniserar produktionsdatabasen ($SOURCE_DB) till demo-databasen ($TARGET_DB).

		Metod: DROP DATABASE + CREATE DATABASE, sedan pg_dump | psql
		(non-disruptive för källan; demo-databasen återskapas från scratch —
		den är helt härledd data)

		Kräver:
		  - Docker compose-miljö med 'database' service igång
		  - Env-fil '$ENV_FILE' med POSTGRES_USER
		  - Valfritt: COMPOSE_FILE env var för att peka på rätt compose-fil
	HELP
}

case ${1:-} in
help | -h | --help)
	usage
	exit 0
	;;
esac

# Ladda databasvariabler
if [ ! -e "$ENV_FILE" ]; then
	printf 'Could not find env file "%s"\n' "$ENV_FILE" >&2
	exit 1
fi

# shellcheck source=/dev/null
source "$ENV_FILE"

if [ -z "${POSTGRES_USER:-}" ]; then
	echo 'Env file should contain variable POSTGRES_USER' >&2
	exit 1
fi

DB_USER="$POSTGRES_USER"

# --- demo_sync_status-telemetri ---------------------------------------------
# Start-, success- och failure-rader skrivs till PROD ($SOURCE_DB); nattens
# dump för med tabellen till demo så båda API:erna kan läsa den. Best-effort:
# saknas tabellen (migration 21 ej körd) blir SYNC_STATUS_ID tom och scriptet
# synkar precis som förut.
DUMP_LOG=$(mktemp /tmp/herdbook-sync-dump.XXXXXX 2>/dev/null || true)
trap 'rm -f "$DUMP_LOG"' EXIT

# -q is load-bearing: without it psql appends the "INSERT 0 1" command tag
# even under -t, the id capture becomes multi-line, and the integer guard
# below silently disables ALL telemetry (found on local-production 2026-08-03).
SYNC_STATUS_ID=$(docker exec "$CONTAINER" psql -U "$DB_USER" -d "$SOURCE_DB" -q -t -A -c \
	"INSERT INTO demo_sync_status (started_at) VALUES (now()) RETURNING id;" 2>/dev/null || true)
# Guard against non-integer output (missing table, connection blips, stray
# warnings) — a malformed id would corrupt the later UPDATE ... WHERE id =
# $SYNC_STATUS_ID and disable telemetry silently (Gemini G2). Empty on failure,
# so the best-effort telemetry no-ops and the sync proceeds as before.
if ! [[ "$SYNC_STATUS_ID" =~ ^[0-9]+$ ]]; then
	SYNC_STATUS_ID=""
fi

record_sync_failure() {
	local exit_code=$1 failed_cmd=$2
	[ -z "$SYNC_STATUS_ID" ] && return 0
	local detail
	detail="exit ${exit_code} vid: ${failed_cmd}
$(tail -n 20 "$DUMP_LOG" 2>/dev/null || true)"
	# Dollar-quoting skyddar mot citattecken i felutskriften. OBS: <<SQL
	# (utan bindestreck) — terminatorn står i kolumn 0 så att heredocen
	# inte är beroende av tab-indrag.
	docker exec -i "$CONTAINER" psql -U "$DB_USER" -d "$SOURCE_DB" >/dev/null 2>&1 <<SQL || true
        UPDATE demo_sync_status
        SET finished_at = now(),
            success = false,
            detail = \$sync_detail\$${detail}\$sync_detail\$
        WHERE id = ${SYNC_STATUS_ID};
SQL
}
trap 'record_sync_failure "$?" "$BASH_COMMAND"' ERR

echo "=== Database sync started at $(date) ==="
echo "Source: $SOURCE_DB -> Target: $TARGET_DB"

# Snapshot the source hbuser count BEFORE the dump so the post-load sanity
# check compares against (approximately) the same snapshot pg_dump sees —
# a registration committing during the load must not fail the check.
SOURCE_USERS=$(docker exec "$CONTAINER" psql -U "$DB_USER" -d "$SOURCE_DB" -tAc \
	"SELECT count(*) FROM hbuser;")

# Recreate the target DB from scratch. Loading a --clean dump stream into a
# non-empty database hits FK-ordering errors and silently drops rows (e.g.
# hbuser) — demo is fully derived data, so dropping is safe. WITH (FORCE)
# terminates any lingering backends (api-test) before the drop.
echo "Recreating $TARGET_DB from scratch..."
docker exec "$CONTAINER" psql -U "$DB_USER" -d postgres -v ON_ERROR_STOP=1 -c \
	"DROP DATABASE IF EXISTS $TARGET_DB WITH (FORCE);"
docker exec "$CONTAINER" psql -U "$DB_USER" -d postgres -v ON_ERROR_STOP=1 -c \
	"CREATE DATABASE $TARGET_DB OWNER $DB_USER;"

# Sync using pg_dump | psql (non-disruptive to source DB). The target is
# empty, so no --clean is needed. Abort on the first SQL error — a silently
# broken sync locks recently-registered users out of v2 (demo is the default).
echo "Syncing $SOURCE_DB -> $TARGET_DB via pg_dump..."
# ON_ERROR_STOP=1 aborts psql on the first SQL error; the
# outer set -Eeo pipefail then fires the ERR trap so the failure telemetry row
# is written before the script aborts. tee mirrors the stream to DUMP_LOG for
# record_sync_failure's detail.
docker exec "$CONTAINER" bash -c "
	set -o pipefail
	pg_dump -U $DB_USER --no-owner --no-privileges $SOURCE_DB \
	| psql -U $DB_USER -d $TARGET_DB -q -v ON_ERROR_STOP=1
" 2>&1 | tee "${DUMP_LOG:-/dev/null}" | { grep -v '^$' || true; } | tail -5

# The copy carries prod's genetics version counter, which can repeat a number
# api-test already memoized in Redis for the previous demo data: a new epoch
# retires those memos (audit R043). Same SQL function as `flask genetics
# rotate-epoch`; a prod database from before the epoch has none, and the
# migration that adds it on the api-test restart draws a random one.
HAS_EPOCH=$(docker exec "$CONTAINER" psql -U "$DB_USER" -d "$TARGET_DB" -tAc \
	"SELECT to_regprocedure('rotate_genetics_epoch()') IS NOT NULL;")
if [ "$HAS_EPOCH" = "t" ]; then
	echo "Rotating the genetics epoch of $TARGET_DB..."
	docker exec "$CONTAINER" psql -U "$DB_USER" -d "$TARGET_DB" -v ON_ERROR_STOP=1 -qtAc \
		"SELECT rotate_genetics_epoch();"
fi

echo "Granting permissions..."
docker exec "$CONTAINER" psql -U "$DB_USER" -d postgres -v ON_ERROR_STOP=1 -c \
	"GRANT ALL PRIVILEGES ON DATABASE $TARGET_DB TO $DB_USER;"

# Everyone may try the demo (api-test auto-validates new logins too).
# Safe only because production refuses sessions minted by api-test.
echo "Setting all users to validated in $TARGET_DB..."
docker exec "$CONTAINER" psql -U "$DB_USER" -d "$TARGET_DB" -v ON_ERROR_STOP=1 -c \
	"UPDATE hbuser SET validated = true WHERE validated = false;"

# The copy carries production's mail queue and intake items. The demo must not
# send or show them as its own, so they are emptied. Tables an older schema
# lacks are skipped; without CASCADE, so a table that points at them fails
# the sync loudly instead of being emptied too.
echo "Emptying the mail queue and the intake queue in $TARGET_DB..."
docker exec -i "$CONTAINER" psql -U "$DB_USER" -d "$TARGET_DB" -v ON_ERROR_STOP=1 -q <<'SQL'
DO $$
DECLARE
	names text;
BEGIN
	SELECT string_agg(quote_ident(t), ', ') INTO names
	FROM unnest(ARRAY[
		'mail_attempt', 'mail_message', 'mail_sender',
		'notice', 'inbox_operation', 'inbox_event', 'inbox_document', 'inbox_item',
		'gmail_processed', 'gmail_sync'
	]) AS t
	WHERE to_regclass(t) IS NOT NULL;
	IF names IS NOT NULL THEN
		EXECUTE 'TRUNCATE ' || names;
	END IF;
END
$$;
SQL

# Verifiera
TABLES=$(docker exec "$CONTAINER" psql -U "$DB_USER" -d "$TARGET_DB" -t -c \
	"SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public';")

# --- success-rad ------------------------------------------------------------
if [ -n "${SYNC_STATUS_ID:-}" ]; then
	ROWS_SYNCED=$(docker exec "$CONTAINER" psql -U "$DB_USER" -d "$TARGET_DB" -t -A -c \
		"SELECT count(*) FROM hbuser;" 2>/dev/null || echo 0)
	docker exec "$CONTAINER" psql -U "$DB_USER" -d "$SOURCE_DB" -c \
		"UPDATE demo_sync_status SET finished_at = now(), success = true, rows_synced = ${ROWS_SYNCED:-0} WHERE id = $SYNC_STATUS_ID;" 2>/dev/null || true
	trap - ERR
fi

# Restart api-test to get fresh database connections — DROP ... WITH (FORCE)
# killed its sessions and Peewee doesn't recover cleanly from terminated
# connections. Runs BEFORE the sanity check so a failed check (exit 1 for the
# cron log) can't leave a running api-test on dead connections. A stopped or
# absent api-test (e.g. during bootstrap) is skipped; a failed restart of a
# RUNNING api-test fails the sync loudly.
restart_api_test() {
	cf="$1"
	cid=$(docker compose -f "$cf" ps --status running -q api-test 2>/dev/null || true)
	if [ -z "$cid" ]; then
		echo "api-test is not running — skipping restart"
	else
		docker compose -f "$cf" restart api-test
	fi
}

echo "Restarting api-test service..."
if [ -n "${COMPOSE_FILE:-}" ]; then
	restart_api_test "$COMPOSE_FILE"
else
	for cf in "$scriptdir/../docker-compose.local-production.yml" "$scriptdir/../docker-compose.production.yml"; do
		if [ -f "$cf" ]; then
			restart_api_test "$cf"
			break
		fi
	done
fi

# Sanity check: every hbuser row from the pre-dump snapshot must have made it
# into demo. A mismatch means the load silently dropped data (the pre-2026-07
# failure mode) — fail loudly so cron logs show it.
TARGET_USERS=$(docker exec "$CONTAINER" psql -U "$DB_USER" -d "$TARGET_DB" -tAc \
	"SELECT count(*) FROM hbuser;")
if [ "$SOURCE_USERS" != "$TARGET_USERS" ]; then
	echo "ERROR: hbuser row count mismatch after sync:" \
		"$SOURCE_DB=$SOURCE_USERS $TARGET_DB=$TARGET_USERS" >&2
	exit 1
fi
echo "Sanity check OK: hbuser has $TARGET_USERS rows in both databases"

echo "=== Database sync completed at $(date) ==="
echo "Synced $SOURCE_DB -> $TARGET_DB (${TABLES## } tables)"
