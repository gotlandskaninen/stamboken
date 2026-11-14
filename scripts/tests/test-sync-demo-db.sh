#!/usr/bin/env bash
#
# Tests that the demo sync copies production without the data of the queue
# tables: the demo API keeps running through the load, and its mail sender must
# never see production's queue. Runs the pg_dump flags from sync-demo-db.sh
# against a throwaway Postgres container.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="$HERE/../sync-demo-db.sh"

pass=0
fail=0
check() { # desc expected actual
  if [ "$2" = "$3" ]; then echo "ok   - $1"; pass=$((pass + 1))
  else echo "FAIL - $1 (expected '$2', got '$3')"; fail=$((fail + 1)); fi
}

SKIP_QUEUE_DATA=""
eval "$(grep -E '^SKIP_QUEUE_DATA=' "$SCRIPT")"

name="herdbook-sync-demo-test-$$"
trap 'docker rm -f "$name" >/dev/null 2>&1' EXIT
docker run -d --name "$name" -e POSTGRES_HOST_AUTH_METHOD=trust postgres:18 >/dev/null || exit 2
# Over TCP: the image's init server listens only on the socket, so this waits for the real one.
for _ in $(seq 60); do
  docker exec "$name" pg_isready -h 127.0.0.1 -U postgres -q && break
  sleep 1
done
sql() { docker exec -i "$name" psql -U postgres -v ON_ERROR_STOP=1 -qtA "$@"; }

sql -c "CREATE DATABASE src" -c "CREATE DATABASE dst" || exit 2
sql -d src <<'SQL' || exit 2
CREATE TABLE mail_message (id int PRIMARY KEY);
CREATE TABLE mail_attempt (id int PRIMARY KEY, message_id int REFERENCES mail_message ON DELETE CASCADE);
CREATE TABLE notice_setting (id int PRIMARY KEY);
CREATE TABLE hbuser (id int PRIMARY KEY);
INSERT INTO mail_message VALUES (1);
INSERT INTO mail_attempt VALUES (1, 1);
INSERT INTO notice_setting VALUES (1);
INSERT INTO hbuser VALUES (1);
SQL

# The dump-and-load step of sync-demo-db.sh. No inbox_*, notice or gmail_*
# table exists here: a pattern that matches nothing must not fail the dump.
docker exec "$name" bash -c "
	set -o pipefail
	pg_dump -U postgres --no-owner --no-privileges $SKIP_QUEUE_DATA src \
	| psql -U postgres -d dst -q -v ON_ERROR_STOP=1
" >/dev/null
check "the dump and load succeed" 0 "$?"
check "mail_message comes over without rows" 0 "$(sql -d dst -c 'SELECT count(*) FROM mail_message')"
check "mail_attempt comes over without rows" 0 "$(sql -d dst -c 'SELECT count(*) FROM mail_attempt')"
check "notice_setting (a user preference) keeps its rows" 1 "$(sql -d dst -c 'SELECT count(*) FROM notice_setting')"
check "an ordinary table keeps its rows" 1 "$(sql -d dst -c 'SELECT count(*) FROM hbuser')"

echo ""
echo "passed: $pass, failed: $fail"
[ "$fail" -eq 0 ]
