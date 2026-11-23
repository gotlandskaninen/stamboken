#!/usr/bin/env bash
#
# Tests that the demo sync copies production without the data of the queue
# tables: the demo API keeps running through the load, and its mail sender must
# never see production's queue. Nor does the demo keep production's buyers
# outside the association: they are deleted after the load. Runs the pg_dump
# flags and the buyer step from sync-demo-db.sh against a throwaway Postgres
# container.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="$HERE/../sync-demo-db.sh"

pass=0
fail=0
check() { # desc expected actual
  if [ "$2" = "$3" ]; then echo "ok   - $1"; pass=$((pass + 1))
  else echo "FAIL - $1 (expected '$2', got '$3')"; fail=$((fail + 1)); fi
}

SKIP_QUEUE_DATA="" DROP_BUYERS_SQL="" MAIL_SEQ_SQL="" SET_MAIL_SEQ_SQL="" STAGING_DB="" DROP_STAGING_SQL=""
# shellcheck disable=SC2034  # read by the STAGING_DB line taken from the script
TARGET_DB=dst
eval "$(grep -E '^(SKIP_QUEUE_DATA|DROP_BUYERS_SQL|MAIL_SEQ_SQL|SET_MAIL_SEQ_SQL|STAGING_DB|DROP_STAGING_SQL)=' "$SCRIPT")"

# A run that stops before the rename drops the staging database on exit: the EXIT trap names drop_staging, it is
# set before the staging database is made, and the rename marks it done.
# shellcheck disable=SC2016
trap_line=$(grep -n "^trap 'drop_staging" "$SCRIPT" | cut -d: -f1)
# shellcheck disable=SC2016
create_line=$(grep -n 'CREATE DATABASE $STAGING_DB' "$SCRIPT" | cut -d: -f1)
check "the exit trap drops the staging database, set before it is made" 1 "$((trap_line > 0 && trap_line < create_line))"
check "the rename turns the trap off" 1 "$(grep -c '^STAGING_RENAMED=1$' "$SCRIPT")"

# The load goes into a staging database, its buyers go as the next command, and only then is it
# renamed to the demo database: the demo API never reads production's buyers. The patterns name
# the script's own variables, so they stay in single quotes (SC2016 on each line).
load_end=$(grep -n 'DUMP_LOG:-/dev/null' "$SCRIPT" | cut -d: -f1)
next_exec=$(awk -v from="$load_end" 'NR > from && /^docker exec/ { print; exit }' "$SCRIPT")
# shellcheck disable=SC2016
check "the load goes into the staging database" 1 "$(grep -c 'psql -U $DB_USER -d $STAGING_DB' "$SCRIPT")"
check "the next command after the load deletes the buyers there" 1 \
  "$(grep -c 'STAGING_DB.*DROP_BUYERS_SQL' <<<"$next_exec")"
# shellcheck disable=SC2016
drop_line=$(grep -n '"$DROP_BUYERS_SQL"' "$SCRIPT" | cut -d: -f1)
# shellcheck disable=SC2016
rename_line=$(grep -n 'ALTER DATABASE $STAGING_DB RENAME TO $TARGET_DB' "$SCRIPT" | cut -d: -f1)
check "the cleaned copy is renamed to the demo database afterwards" 1 "$((rename_line > drop_line))"
check "nothing but the sequence read touches the demo database before the rename" 0 \
  "$(awk -v to="$rename_line" 'NR < to && /-d "\$TARGET_DB"/ && !/MAIL_SEQ_SQL/' "$SCRIPT" | wc -l)"

# Two runs never overlap: with the lock held, the script stops before it touches anything.
lock=$(mktemp)
held=$(flock -n "$lock" bash -c "SYNC_DEMO_LOCK='$lock' bash '$SCRIPT' 2>&1; echo \"exit \$?\"")
rm -f "$lock"
check "a second run stops at once while the first holds the lock" 1 "$(grep -c 'Another demo sync is running' <<<"$held")"
check "and exits 1" 1 "$(grep -c '^exit 1$' <<<"$held")"

name="herdbook-sync-demo-test-$$"
trap 'docker rm -f "$name" >/dev/null 2>&1' EXIT
docker run -d --name "$name" -e POSTGRES_HOST_AUTH_METHOD=trust postgres:18 >/dev/null || exit 2
# Over TCP: the image's init server listens only on the socket, so this waits for the real one.
for _ in $(seq 60); do
  docker exec "$name" pg_isready -h 127.0.0.1 -U postgres -q && break
  sleep 1
done
sql() { docker exec -i "$name" psql -U postgres -v ON_ERROR_STOP=1 -qtA "$@"; }

sql -c "CREATE DATABASE src" -c "CREATE DATABASE dst" -c "CREATE DATABASE dst_staging" || exit 2
# The old demo's own sequence value, as the script reads it before the swap.
sql -d dst -c "CREATE TABLE mail_message (id serial PRIMARY KEY)" -c "SELECT setval('mail_message_id_seq', 41)" >/dev/null || exit 2
seq=$(sql -d dst -c "$MAIL_SEQ_SQL")
check "the demo's sequence value is read before the swap" 41 "$seq"
sql -d src <<'SQL' || exit 2
CREATE TABLE mail_message (id serial PRIMARY KEY);
CREATE TABLE mail_attempt (id int PRIMARY KEY, message_id int REFERENCES mail_message ON DELETE CASCADE);
CREATE TABLE notice_setting (id int PRIMARY KEY);
CREATE TABLE hbuser (id int PRIMARY KEY);
CREATE TABLE login_code (id int PRIMARY KEY);
CREATE TABLE member_previous_address (id int PRIMARY KEY);
INSERT INTO login_code VALUES (1);
INSERT INTO member_previous_address VALUES (1);
INSERT INTO mail_message DEFAULT VALUES;
INSERT INTO mail_attempt VALUES (1, 1);
INSERT INTO notice_setting VALUES (1);
INSERT INTO hbuser VALUES (1);
CREATE TABLE buyer_contact (id int PRIMARY KEY);
CREATE TABLE herd_tracking (id int PRIMARY KEY, holder_contact_id int REFERENCES buyer_contact ON DELETE SET NULL, buyer_removed boolean NOT NULL DEFAULT false);
INSERT INTO buyer_contact VALUES (1);
INSERT INTO herd_tracking VALUES (1, 1);
SQL

# The dump-and-load step of sync-demo-db.sh. No inbox_*, notice or gmail_*
# table exists here: a pattern that matches nothing must not fail the dump.
docker exec "$name" bash -c "
	set -o pipefail
	pg_dump -U postgres --no-owner --no-privileges $SKIP_QUEUE_DATA src \
	| psql -U postgres -d dst_staging -q -v ON_ERROR_STOP=1
" >/dev/null
check "the dump and load succeed" 0 "$?"
sql -d dst_staging -c "$DROP_BUYERS_SQL" >/dev/null
check "the buyer step succeeds" 0 "$?"
check "the dump carries no sequence value: the new database counts from 1" 1 "$(sql -d dst_staging -c "SELECT nextval('mail_message_id_seq')")"
sql -d dst_staging -c "${SET_MAIL_SEQ_SQL//%s/$seq}" >/dev/null
sql -c "DROP DATABASE dst" -c "ALTER DATABASE dst_staging RENAME TO dst"
check "the rename succeeds" 0 "$?"
check "mail_message comes over without rows" 0 "$(sql -d dst -c 'SELECT count(*) FROM mail_message')"
check "mail_attempt comes over without rows" 0 "$(sql -d dst -c 'SELECT count(*) FROM mail_attempt')"
check "the demo's sequence value survives, so Message-IDs do not repeat" 42 "$(sql -d dst -c "SELECT nextval('mail_message_id_seq')")"
check "login_code (codes and unconfirmed addresses) comes over without rows" 0 "$(sql -d dst -c 'SELECT count(*) FROM login_code')"
check "member_previous_address (addresses left) comes over without rows" 0 "$(sql -d dst -c 'SELECT count(*) FROM member_previous_address')"
check "notice_setting (a user preference) keeps its rows" 1 "$(sql -d dst -c 'SELECT count(*) FROM notice_setting')"
check "an ordinary table keeps its rows" 1 "$(sql -d dst -c 'SELECT count(*) FROM hbuser')"

check "the demo has no buyers" 0 "$(sql -d dst -c 'SELECT count(*) FROM buyer_contact')"
check "the sale stays, without its buyer, marked as removed" "1||t" "$(sql -d dst -c 'SELECT id, holder_contact_id, buyer_removed FROM herd_tracking')"
sql -d dst -c "DROP TABLE herd_tracking, buyer_contact" -c "$DROP_BUYERS_SQL" >/dev/null
check "an older schema without buyers is skipped" 0 "$?"

# A run stopped between the load and the rename: the trap's statement removes the copy it left.
sql -c "CREATE DATABASE $STAGING_DB" >/dev/null || exit 2
sql -c "$DROP_STAGING_SQL" >/dev/null
check "the exit trap's statement drops a leftover staging database" 0 \
  "$(sql -c "SELECT count(*) FROM pg_database WHERE datname = '$STAGING_DB'")"

echo ""
echo "passed: $pass, failed: $fail"
[ "$fail" -eq 0 ]
