#!/usr/bin/env bash
# Varje användarvänd route i Next.js-appen måste ha ett avsnitt i användar-
# manualen. Avsnittet märks med en HTML-kommentar direkt under rubriken:
#   <!-- route: /stamboken/min-besattning -->
# Routen är page.tsx-sökvägen utan route-grupper "(…)", med [param] bevarat.
# Körs i CI (lint.yml) och av scripts/ci-local.sh; avslutar med 1 och listar
# routes som saknar avsnitt.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MANUAL="$ROOT/docs/USER_MANUAL.md"
APP="$ROOT/next-app/src/app/(app)"

missing=0
total=0
while IFS= read -r page; do
	route="${page#"$APP"}"
	route="${route%/page.tsx}"
	route="$(sed -E 's#/\([^/]*\)##g' <<<"$route")"
	total=$((total + 1))
	if ! grep -qF -- "<!-- route: $route -->" "$MANUAL"; then
		echo "SAKNAS: $route (${page#"$ROOT"/})"
		missing=$((missing + 1))
	fi
done < <(find "$APP/stamboken" "$APP/(auth)/auth/sign-in" -name page.tsx | sort)

echo "Manual-täckning: $((total - missing))/$total routes har avsnitt i docs/USER_MANUAL.md"
if [ "$missing" -gt 0 ]; then
	echo "Lägg till ett avsnitt med '<!-- route: … -->' under rubriken för varje route ovan." >&2
	exit 1
fi
