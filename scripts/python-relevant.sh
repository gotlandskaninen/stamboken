#!/usr/bin/env bash
# Läser ändrade sökvägar på stdin och skriver true om någon av dem kan påverka
# python_tests.yml, annars false. Next.js, docs/ och Markdown utanför app/ når
# aldrig API-imagen eller skripttesterna; app/tests läser sina egna .md-filer.
# En okänd sökväg räknas som relevant. Används av python_tests.yml.
set -euo pipefail
while IFS= read -r path; do
	case "$path" in
	"" | next-app/* | docs/*) ;;
	app/*) echo true && exit 0 ;;
	*.md) ;;
	*) echo true && exit 0 ;;
	esac
done
echo false
