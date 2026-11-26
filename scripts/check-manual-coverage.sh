#!/usr/bin/env bash
# Varje användarvänd route i Next.js-appen måste ha ett avsnitt i användar-
# manualen, och varje sida i medlemsregistret (/medlem) ett avsnitt i guiden
# för matrikeln. Avsnittet märks med en HTML-kommentar direkt under rubriken:
#   <!-- route: /stamboken/min-besattning -->
# Routen är page.tsx-sökvägen utan route-grupper "(…)", med [param] bevarat.
# Körs i CI (lint.yml) och av scripts/ci-local.sh; avslutar med 1 och listar
# routes som saknar avsnitt.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MANUAL="$ROOT/next-app/public/stamboken/manual/USER_MANUAL.md"
GUIDE="$ROOT/next-app/content/matrikel-guide/GUIDE.md"
APP="$ROOT/next-app/src/app/(app)"

missing=0

# check <dokument> <page.tsx-filer…>
check() {
	local doc="$1" total=0 page route
	shift
	for page in "$@"; do
		route="${page#"$APP"}"
		route="${route%/page.tsx}"
		route="$(sed -E 's#/\([^/]*\)##g' <<<"$route")"
		total=$((total + 1))
		if ! grep -qF -- "<!-- route: $route -->" "$doc"; then
			echo "SAKNAS: $route (${page#"$ROOT"/})"
			missing=$((missing + 1))
		fi
	done
	echo "Täckning: $total routes kontrollerade mot ${doc#"$ROOT"/}"
}

mapfile -t manual_pages < <(find "$APP/stamboken" "$APP/(auth)/auth" -name page.tsx | sort)
check "$MANUAL" "${manual_pages[@]}"
# The guide page itself needs no section.
mapfile -t guide_pages < <(find "$APP/medlem" -name page.tsx -not -path "*/medlem/guide/*" | sort)
check "$GUIDE" "${guide_pages[@]}"

if [ "$missing" -gt 0 ]; then
	echo "$missing routes saknar avsnitt. Lägg till '<!-- route: … -->' under rubriken för varje route ovan." >&2
	exit 1
fi
