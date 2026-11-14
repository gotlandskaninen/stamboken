#!/bin/bash
# Lokal CI-grind: kör samma kontroller som .github/workflows/ på den egna
# maskinen. När Actions är av (privat repo utan minuter) mergas ingen PR utan
# sammanfattningen från detta skript i PR-texten.

# step_*/down_* anropas indirekt via "step_$fn".
# shellcheck disable=SC2329

# Hela skriptet är ett block som bash läser in innan något körs: andra sessioner kör
# det här från samma sökväg, och en ändring av filen mitt i en körning får inte slå igenom.
{
set -uo pipefail

usage() {
	cat <<'EOF'
Användning: scripts/ci-local.sh [--quick] [--only <steg>[,<steg>...]]

Kör CI-kontrollerna lokalt mot arbetskatalogen du står i (spårade + ospårade,
ej ignorerade filer kopieras till en snapshot, som en ren checkout i CI).

  --quick         allt utom e2e-next, e2e-legacy och images
  --only <steg>   bara angivna steg (kommaseparerade)
  -h, --help      denna text

Steg (workflow → steg):
  lint.yml            lint          super-linter slim-v8 (ruff, bash, markdown;
                                    bara committade filer ändrade mot origin/main)
  security.yml        trivy         Trivy 0.75.0 fs, CRITICAL,HIGH, os+library
                      semgrep       semgrep/semgrep, --config auto + CI:s exclude-rules
  python_tests.yml    pytest        isolerad pytest-stack, eget projektnamn per worktree
  (next-app)          pnpm-install, tsc, eslint, vitest, next-build
  build-and-publish   images        api, next-app, cms-migrate — bygg utan push
  playwright.yml      e2e-next      Next.js-e2e (kräver lediga :3000 :9090 :5433)
                      e2e-legacy    legacy-e2e (kräver :80 :443 :3000 :9090 :5432);
                                    advisory i CI, men räknas här som alla andra steg

Hoppas över: legacy-tarballs och deployment-bundle i build-and-publish (körs
bara vid push till main/taggar).
deploy.yml finns inte här — deploy körs från stamboken-drift.

Ändrar grenen bara *.md eller docs/** mot origin/main körs, utan flaggor, bara
lint, trivy och semgrep (som paths-ignore); övriga steg blir SKIPPED.

Upptagen port avbryter e2e-steget med namnet på ägaren; skriptet stoppar aldrig
någon annans stack. Bara en körning åt gången (flock /tmp/stamboken-ci-local.lock);
en andra körning väntar. Exitkod = antal misslyckade steg.
EOF
}

STEPS=(lint trivy semgrep pytest pnpm-install tsc eslint vitest next-build images e2e-next e2e-legacy)
NODE_STEPS=" tsc eslint vitest next-build e2e-next e2e-legacy "
SELECTED=" ${STEPS[*]} "
ARGS="${*:-(inga)}"

while [ $# -gt 0 ]; do
	case "$1" in
	--quick) SELECTED=" ${STEPS[*]:0:9} " ;;
	--only)
		[ $# -ge 2 ] || { usage; exit 64; }
		SELECTED=" ${2//,/ } "
		for s in $SELECTED; do
			[[ " ${STEPS[*]} " == *" $s "* ]] || { echo "Okänt steg: $s" >&2; exit 64; }
			[[ "$NODE_STEPS" == *" $s "* ]] && SELECTED+="pnpm-install "
		done
		shift
		;;
	-h | --help) usage; exit 0 ;;
	*) usage; exit 64 ;;
	esac
	shift
done

die() { echo "ci-local: $*" >&2; exit 1; }
# CI sätter inga av dessa; ärvda värden kan peka legacy-e2e mot audit-stacken.
unset LEGACY_BASE_URL LEGACY_USERS_FILE LEGACY_OUTPUT_DIR LEGACY_TIMEOUT_MS AUDIT_E2E

ROOT=$(git rev-parse --show-toplevel) || exit 64
# Sökvägshash: två worktrees med lika basnamn får aldrig dela snapshot, stackar eller volymer.
HASH=$(printf %s "$ROOT" | sha1sum | cut -c1-6)
SLUG=$(basename "$ROOT" | tr '[:upper:]' '[:lower:]' | tr -c 'a-z0-9\n' '-')-$HASH
BASE="${XDG_CACHE_HOME:-$HOME/.cache}/stamboken-ci-local"
# Bara hash i snapshot-sökvägen: Playwright matchar testMatch mot hela sökvägen,
# så en worktree som heter t.ex. *-public-* skulle flytta specs mellan projekt.
WORK="$BASE/$HASH"
TREE="$WORK/tree"
LOGS="$WORK/logs"
SUMMARY="$WORK/summary.md"
NET="ci-local-$SLUG"
PYTEST_DC=(docker compose --project-directory "$TREE" -f "$TREE/docker-compose.yml" -f "$TREE/docker-compose.pytest.yml" -p "herdbook-pytest-$SLUG")
LEGACY_DC=(docker compose --project-directory "$TREE" -f "$TREE/docker-compose.local-production.yml" -f "$TREE/ci-local.override.yml" -p "ci-local-legacy-$SLUG")
API_ENV=(-e POSTGRES_HOST=postgres -e POSTGRES_PORT=5432 -e POSTGRES_USER=herdbook -e POSTGRES_PASSWORD=testpass
	-e POSTGRES_DB=herdbook_test -e FLASK_ENV=testing -e REDIS_URL=redis://redis:6379/1
	-e SECRET_KEY=dev-secret-do-not-use-in-prod -e SESSION_REDIS_URL=redis://redis:6379/2
	-e AUTHCONFIGFILE=/app/tests/auth.ini.test
	-e S3_ENDPOINT=http://s3backend:9000 -e S3_USESSL=false -e S3_VERIFY=false) # digitala intyg (e2e/manual) kräver S3

# --- Lås: en körning åt gången över alla worktrees/sessioner -----------------
LOCK=/tmp/stamboken-ci-local.lock
exec 9<>"$LOCK" || die "kan inte öppna låsfilen $LOCK"
if ! flock -n 9; then
	echo "ci-local: låset hålls av $(cat "$LOCK" 2>/dev/null || echo okänd) — väntar ($(date +%T))..."
	flock 9 || die "flock på $LOCK misslyckades"
	echo "ci-local: fick låset $(date +%T)"
fi
printf '%s (pid %s, start %s)\n' "$ROOT" "$$" "$(date +%T)" >"$LOCK"

# --- Snapshot: det CI skulle checka ut, utan ignorerade filer ----------------
SHA=$(git -C "$ROOT" rev-parse HEAD)
BRANCH=$(git -C "$ROOT" branch --show-current)
DIRTY=$(git -C "$ROOT" status --porcelain | wc -l)
# Bara *.md eller docs/** ändrat mot origin/main (committat, ändrat eller ospårat) och inga
# flaggor: hoppa över de tunga stegen, som paths-ignore. --only/--quick styr annars själva.
DOCS_ONLY=""
if [ "$ARGS" = "(inga)" ] && BASE_SHA=$(git -C "$ROOT" merge-base origin/main HEAD 2>/dev/null); then
	CHANGED=$({ git -C "$ROOT" diff --name-only "$BASE_SHA"; git -C "$ROOT" ls-files -o --exclude-standard; } | sort -u)
	if [ -n "$CHANGED" ] && ! grep -qvE '(\.md$|^docs/)' <<<"$CHANGED"; then
		DOCS_ONLY=$(wc -l <<<"$CHANGED")
		SELECTED=" lint trivy semgrep "
	fi
fi
mkdir -p "$WORK" "$LOGS"
rm -f "$LOGS"/*
# Containrar skriver som root i snapshoten (pycache, certs) — städa via docker vid behov.
rm -rf "$TREE" 2>/dev/null || docker run --rm -v "$WORK:/w" alpine rm -rf /w/tree || die "kunde inte rensa $TREE"
mkdir -p "$TREE"
# Spårade filer som raderats i arbetskatalogen hoppas över; alla andra måste gå att läsa.
git -C "$ROOT" ls-files -z -co --exclude-standard |
	while IFS= read -rd '' f; do
		if [ -e "$ROOT/$f" ] || [ -L "$ROOT/$f" ]; then printf '%s\0' "$f"; fi
	done | tar -C "$ROOT" --null -T - -cf - | tar -C "$TREE" -xf - || die "snapshot av $ROOT misslyckades"
for f in "$TREE"/.docker/*.env.default; do cp "$f" "${f%.default}"; done
mkdir -p "$TREE"/{config,logs,logs-test,cache,cache-test,uppladdningar,skyddat,skyddat-test,s3data,letsencrypt,local_ca}
cat >"$TREE/ci-local.override.yml" <<EOF
# Egna image-namn så att bygget inte skriver över next-app/s3backend som andra worktrees dev-stackar använder.
services:
  next-app: { image: "ci-local-next-app:$SLUG" }
  cms-migrate: { image: "ci-local-next-app-migrate:$SLUG" }
  s3backend: { image: "ci-local-s3backend:$SLUG" }
EOF

# Avbryt om någon annan äger porten; stoppa aldrig deras stack.
ports_free() {
	local p owner rc=0
	for p in "$@"; do
		owner=$(docker ps --filter "publish=$p" --format '{{.Names}} ({{.Label "com.docker.compose.project.working_dir"}})' | paste -sd, -)
		if [ -n "$owner" ]; then
			echo "FEL: port $p används av $owner. Stoppas inte av ci-local — vänta eller be ägaren stoppa sin stack." >&2
			rc=1
		elif ss -ltnH "sport = :$p" | grep -q .; then
			echo "FEL: port $p används av en process utanför docker (ss -ltnp 'sport = :$p')." >&2
			rc=1
		fi
	done
	return "$rc"
}

# Playwright 1.58 vägrar installera på Ubuntu 26.04; 24.04-bygget fungerar (no-op om redan installerad).
playwright_install() { PLAYWRIGHT_HOST_PLATFORM_OVERRIDE=ubuntu24.04-x64 pnpm exec playwright install chromium; }

wait_for() { # sekunder kommando...
	timeout "$1" bash -c "until ${*:2}; do sleep 2; done" >/dev/null 2>&1 || { echo "Timeout: ${*:2}" >&2; return 1; }
}

# --- Steg (körs i subshell med set -e; output till $LOGS/<steg>.log) --------
step_lint() {
	local common
	common=$(git -C "$ROOT" rev-parse --path-format=absolute --git-common-dir)
	docker run --rm -e RUN_LOCAL=true -e VALIDATE_ALL_CODEBASE=false -e DEFAULT_BRANCH=origin/main \
		-e VALIDATE_PYTHON_RUFF=true -e VALIDATE_BASH=true -e VALIDATE_MARKDOWN=true \
		-v "$ROOT:/tmp/lint" -v "$common:$common:ro" ghcr.io/super-linter/super-linter:slim-v8 &&
		"$TREE/scripts/check-ui-terms.sh" &&
		"$TREE/scripts/check-manual-coverage.sh" &&
		(cd "$ROOT" && python3 scripts/check-adr-refs.py) && # git ls-files: the snapshot is not a repo
		(cd "$ROOT" && scripts/check-no-symlinks.sh) &&
		"$TREE/scripts/tests/test-compose-isolation.sh" # samma steg som i lint.yml
}

step_trivy() {
	local trivy=(docker run --rm --user "$(id -u):$(id -g)" -v "$TREE:/src:ro" -w /src -v "$LOGS:/out"
		-v "$BASE/trivy-cache:/cache" ghcr.io/aquasecurity/trivy:0.75.0)
	mkdir -p "$BASE/trivy-cache"
	local rc=0
	"${trivy[@]}" fs --cache-dir /cache --severity CRITICAL,HIGH --pkg-types os,library --no-progress \
		--exit-code 1 --format json --output /out/trivy.json . || rc=$?
	"${trivy[@]}" convert --format table /out/trivy.json
	return "$rc"
}

step_semgrep() {
	docker run --rm --pull always -v "$TREE:/src:ro" -w /src semgrep/semgrep:latest \
		semgrep scan --config auto --text --error \
		--exclude-rule yaml.docker-compose.security.no-new-privileges.no-new-privileges \
		--exclude-rule yaml.docker-compose.security.writable-filesystem-service.writable-filesystem-service \
		--exclude-rule generic.secrets.security.detected-private-key.detected-private-key \
		--exclude-rule generic.nginx.security.header-redefinition.header-redefinition \
		--exclude-rule generic.nginx.security.possible-h2c-smuggling.possible-nginx-h2c-smuggling \
		--exclude-rule yaml.github-actions.security.github-actions-mutable-action-tag.github-actions-mutable-action-tag \
		--exclude-rule package_managers.npm.npm-missing-minimum-release-age.npm-missing-minimum-release-age
}

step_pytest() {
	"${PYTEST_DC[@]}" down -v
	export DOCKER_TARGET=test
	"${PYTEST_DC[@]}" up -d --build --wait database api
	# Ägarskapskoll (skill run-tests): containern måste mounta DENNA snapshot.
	docker inspect "herdbook-pytest-$SLUG-api-1" --format '{{range .Mounts}}{{.Source}}{{"\n"}}{{end}}' | grep -qx "$TREE/app"
	# CI sätter inga PDF_SIGNING_*; .default pekar på /config som är tom här.
	docker exec -e CI=true -e PDF_SIGNING_KEY=certs/key.pem -e PDF_SIGNING_CA=certs/ca.pem \
		"herdbook-pytest-$SLUG-api-1" pytest /app/tests/ -v --tb=short -n auto
}
down_pytest() { "${PYTEST_DC[@]}" down -v; }

# Samma pnpm som CI (corepack läser packageManager i package.json).
pnpm() { corepack pnpm "$@"; }
step_pnpm_install() {
	[[ "$(node -v)" == v24.* ]] || { echo "FEL: kräver Node 24 som CI och .docker/next-app, har $(node -v)" >&2; return 1; }
	cd "$TREE/next-app" && pnpm install --frozen-lockfile --store-dir "$HOME/.pnpm-store"
}
step_tsc() { cd "$TREE/next-app" && pnpm exec tsc --noEmit; }
step_eslint() { cd "$TREE/next-app" && pnpm exec eslint .; }
step_vitest() { cd "$TREE/next-app" && pnpm exec vitest run src; }
step_next_build() { cd "$TREE/next-app" && NEXT_TELEMETRY_DISABLED=1 PAYLOAD_BUILD=1 pnpm exec next build; }

step_images() {
	docker build -f "$TREE/.docker/api" --target prod --build-arg APP_VERSION=ci-local \
		-t "ci-local/herdbook_api:$SLUG" "$TREE"
	docker build -f "$TREE/.docker/next-app" --target runner --build-arg APP_VERSION=ci-local \
		--build-arg NEXT_PUBLIC_API_TEST_URL=/api-test -t "ci-local/herdbook_next-app:$SLUG" "$TREE"
	docker build -f "$TREE/.docker/next-app" --target migrate -t "ci-local/herdbook_cms-migrate:$SLUG" "$TREE"
}

# CI kör postgres/redis/API på --network host; här eget nät (5432 kan vara upptagen)
# och bara :9090/:5433 publicerade, så Next dev-servern ser samma URL:er som i CI.
step_e2e_next() {
	ports_free 3000 9090 5433
	docker build --target test -t "ci-local/herdbook-api-test:$SLUG" -f "$TREE/.docker/api" "$TREE"
	docker network create "$NET"
	docker run -d --name "$NET-pg" --network "$NET" --network-alias postgres -e POSTGRES_USER=herdbook \
		-e POSTGRES_PASSWORD=testpass -e POSTGRES_DB=herdbook_test postgres:18
	docker run -d --name "$NET-redis" --network "$NET" --network-alias redis redis:7-alpine
	docker build -t "ci-local/s3backend:$SLUG" -f "$TREE/.docker/rustfs" "$TREE"
	docker run -d --name "$NET-s3" --network "$NET" --network-alias s3backend -e RUSTFS_ACCESS_KEY=accesskeytest \
		-e RUSTFS_SECRET_KEY=secretkeytest -e RUSTFS_REGION=us-east-1 -e S3_BUCKET=test "ci-local/s3backend:$SLUG"
	docker run -d --name "$NET-cms" -p 127.0.0.1:5433:5432 -e POSTGRES_USER=herdbook_cms \
		-e POSTGRES_PASSWORD=herdbook_cms_insecure -e POSTGRES_DB=herdbook_cms postgres:18
	wait_for 60 docker exec "$NET-pg" pg_isready -h 127.0.0.1 -U herdbook -d herdbook_test
	wait_for 60 docker exec "$NET-cms" pg_isready -h 127.0.0.1 -U herdbook_cms -d herdbook_cms
	docker run --rm --network "$NET" "${API_ENV[@]}" "ci-local/herdbook-api-test:$SLUG" python3 -c \
		"from utils.database import init, DATABASE; DATABASE.connect() if DATABASE.is_closed() else None; init(); print('DB initialized')"
	docker run -d --name "$NET-api" --network "$NET" -p 127.0.0.1:9090:9090 "${API_ENV[@]}" -e RATELIMIT_ENABLED=false \
		"ci-local/herdbook-api-test:$SLUG" gunicorn -b 0.0.0.0:9090 -w 1 herdbook:APP
	wait_for 120 curl -sf http://localhost:9090/api/health
	docker exec "$NET-api" flask seed create --verbose
	docker exec "$NET-api" python3 -m cli.create_test_users
	cd "$TREE/next-app"
	rm -rf .next # CI:s e2e-jobb startar utan next-builds utdata
	playwright_install
	CI=true API_INTERNAL_URL=http://localhost:9090 \
		CMS_DATABASE_URL=postgres://herdbook_cms:herdbook_cms_insecure@localhost:5433/herdbook_cms \
		pnpm exec playwright test --config=playwright.config.ts --reporter=list
}
down_e2e_next() { # bara det som finns; ett riktigt fel ger rc≠0
	local c rc=0
	for c in "$NET-api" "$NET-pg" "$NET-redis" "$NET-cms" "$NET-s3"; do
		! docker container inspect "$c" >/dev/null 2>&1 || docker rm -fv "$c" || rc=1
	done
	! docker network inspect "$NET" >/dev/null 2>&1 || docker network rm "$NET" || rc=1
	return "$rc"
}

step_e2e_legacy() {
	ports_free 80 443 3000 9090 5432
	cd "$TREE"
	./scripts/build-legacy.sh --prod
	echo "RATELIMIT_ENABLED=false" >>.docker/api-variables.env
	echo "RATELIMIT_ENABLED=false" >>.docker/api-test-variables.env
	cp app/tests/auth.ini.test config/auth.ini
	# shellcheck source=/dev/null
	(set -a && . .docker/next-app-variables.env && set +a && "${LEGACY_DC[@]}" build)
	mkdir -p letsencrypt/dhparams letsencrypt/live/localhost
	openssl dhparam -out letsencrypt/dhparams/dhparam.pem 2048 2>/dev/null
	openssl req -x509 -nodes -newkey rsa:2048 -days 1 -keyout local_ca/localhost.key \
		-out local_ca/localhost.crt -subj "/CN=localhost"
	cp local_ca/localhost.crt letsencrypt/live/localhost/fullchain.pem
	cp local_ca/localhost.key letsencrypt/live/localhost/privkey.pem
	"${LEGACY_DC[@]}" up -d database redis cms-database
	wait_for 120 "${LEGACY_DC[*]} exec -T database pg_isready -U herdbook -d herdbook"
	local svc
	for svc in api api-test; do
		"${LEGACY_DC[@]}" run --rm -T "$svc" python3 -c \
			"from utils.database import init, DATABASE; DATABASE.connect() if DATABASE.is_closed() else None; init(); print('initialized')"
	done
	"${LEGACY_DC[@]}" up -d --no-deps api api-test next-app
	wait_for 180 curl -sf http://localhost:9090/api/health
	wait_for 180 curl -sf http://localhost:3000
	"${LEGACY_DC[@]}" up -d nginx
	wait_for 60 curl -ksf https://localhost
	"${LEGACY_DC[@]}" exec -T api flask seed create --verbose
	"${LEGACY_DC[@]}" exec -T api python3 -m cli.create_test_users
	cd next-app
	playwright_install
	CI=true pnpm exec playwright test --config=playwright.legacy.config.ts --reporter=list
}
down_e2e_legacy() { [ ! -f "$TREE/ci-local.override.yml" ] || "${LEGACY_DC[@]}" down -v; }

cleanup() {
	for d in down_pytest down_e2e_next down_e2e_legacy; do "$d" >/dev/null 2>&1; done
}
trap cleanup EXIT
trap 'exit 130' INT TERM

# --- Kör ---------------------------------------------------------------------
declare -A RESULT TIME DOWNFAIL
for s in "${STEPS[@]}"; do
	if [[ "$SELECTED" != *" $s "* ]]; then
		RESULT[$s]=SKIPPED
		continue
	fi
	fn=${s//-/_}
	echo "▶ $s ($(date +%T), logg: $LOGS/$s.log)"
	start=$SECONDS
	(set -e && "step_$fn") >"$LOGS/$s.log" 2>&1
	rc=$?
	if declare -F "down_$fn" >/dev/null && ! "down_$fn" >>"$LOGS/$s.log" 2>&1; then
		echo "  VARNING: städningen efter $s misslyckades — kolla docker ps och loggen"
		DOWNFAIL[$s]=1
		[ $rc -ne 0 ] || rc=1 # en kvarlämnad stack ska inte se ut som PASS
	fi
	TIME[$s]=$((SECONDS - start))
	if [ $rc -eq 0 ]; then
		RESULT[$s]=PASS
	else
		RESULT[$s]=FAIL
		tail -n 25 "$LOGS/$s.log" | sed 's/^/    /'
	fi
	echo "  ${RESULT[$s]} ($((TIME[$s] / 60))m$((TIME[$s] % 60))s)"
done

# --- Sammanfattning ----------------------------------------------------------
note() {
	local log="$LOGS/$1.log"
	[ -f "$log" ] || return 0
	case $1 in
	trivy)
		[ -f "$LOGS/trivy.json" ] || return 0
		jq -r '[.Results[]? | (.Vulnerabilities[]? | "\(.PkgName)@\(.InstalledVersion) \(.VulnerabilityID)"), (.Secrets[]? | "secret \(.RuleID)")] | unique
			| "\(length) fynd" + (if length > 0 then ": " + (.[:6] | join(", ")) + (if length > 6 then ", …" else "" end) else "" end)' "$LOGS/trivy.json"
		;;
	semgrep)
		local n ids
		n=$(grep -oE 'Ran [0-9]+ rules on [0-9]+ files: [0-9]+ findings?' "$log" | grep -oE '[0-9]+ findings?$' | grep -oE '^[0-9]+')
		ids=$(grep -oE '❱ [A-Za-z0-9_.-]+' "$log" | sed 's/❱ //; s/.*\.//' | sort -u | paste -sd, -)
		echo "${n:-?} fynd${ids:+: $ids}"
		;;
	pytest) grep -E '^=+ .*(passed|failed|error).* in [0-9.]+s' "$log" | tail -n1 | tr -d '=' | xargs ;;
	vitest) grep -E '^ +Tests +' "$log" | tail -n1 | sed 's/\x1b\[[0-9;]*m//g' | xargs ;;
	e2e-*) grep -E '^ +[0-9]+ (passed|failed|flaky|skipped|did not run)' "$log" | xargs ;;
	esac
}

FAILED=0
{
	echo "### ci-local: \`${SHA:0:10}\` (${BRANCH:-detached})"
	echo
	echo "- Commit: \`$SHA\` — $(git -C "$ROOT" log -1 --format=%s "$SHA")"
	if [ "$DIRTY" -eq 0 ]; then
		echo "- Arbetskatalog: ren"
	else
		echo "- Arbetskatalog: **ej ren** ($DIRTY ändrade/ospårade filer, med i snapshoten)"
	fi
	echo "- Körd: $(date '+%Y-%m-%d %H:%M'), flaggor: $ARGS"
	[ -z "$DOCS_ONLY" ] || echo "- Endast dokumentation ändrad mot origin/main ($DOCS_ONLY filer, \`*.md\`/\`docs/\`): bara lint, trivy och semgrep körs"
	echo
	echo "| Steg | Resultat | Tid | Detaljer |"
	echo "|------|----------|-----|----------|"
	for s in "${STEPS[@]}"; do
		t=""
		[ "${RESULT[$s]}" = SKIPPED ] || t="$((TIME[$s] / 60))m$((TIME[$s] % 60))s"
		d=$(note "$s")
		[ "$s" != e2e-legacy ] || d="advisory i CI${d:+; $d}"
		[ -z "${DOWNFAIL[$s]:-}" ] || d="städningen misslyckades${d:+; $d}"
		[ "${RESULT[$s]}" != FAIL ] || FAILED=$((FAILED + 1))
		echo "| $s | ${RESULT[$s]} | $t | ${d//|/\\|} |"
	done
	echo
	echo "**$FAILED steg misslyckades.** Loggar: \`$LOGS\`"
} >"$SUMMARY"
cat "$SUMMARY"
echo
echo "Sammanfattning (klistra in i PR:en): $SUMMARY"
exit "$FAILED"
}
