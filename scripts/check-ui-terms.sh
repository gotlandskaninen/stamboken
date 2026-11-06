#!/usr/bin/env bash
# UI-termgrind. Kanoniska termer (beslut av projektägaren, legacy-appen är referens).
# Orden förklaras i docs/ORDLISTA.md; ett ord byts där först och sedan här:
#
#   Kaninens nummer (G1274-2312)   Individnummer — inte "Genbanksnummer" eller "Kaninnummer"
#   Besättningens nummer (G1274)   Besättningsnummer — inte "Genbanksnummer" eller "Besättningskod"
#   Dokumentet                     intyg, Intygsnummer, Digitalt intyg, Pappersintyg — aldrig "certifikat"
#   Byte av besättning             Sälj, Säljdatum, Såld, Försäljning — inte "Överlåtelse" eller "Flytta",
#                                  inte "Försäljningsdatum" eller "Köpdatum";
#                                  "flytt"/"Flyttad hit" bara i historiktext (lib/herdTracking.ts)
#   Rollen                         Genbanksansvarig — "manager" bara som kodvärde
#   Raserna i löptext              gotlandskanin, mellerudskanin — versal bara först i mening eller rubrik
#   Död kanin                      Död är egen status; en död kanin är inte inaktiv
#   Fliken med kullar              Kullar och parningar — aldrig "&", kullar först
#   Flik och meny                  Kaniner (fliken), Alla kaniner, Min besättning — gemen efter första
#                                  ordet, aldrig "Min Besättning"/"Alla Kaniner" eller "Lista över individer"
#   Personen                       Uppfödare i text och rubriker; Besättningsägare bara som rollnamn i admin
#   Dödsrapportering               Rapportera död — inte "Rapportera som död"
#   Var kaninen funnits            Besättningshistorik — inte "Besättningshistoria"
#   Föräldrarna                    Mor, Far — inte "Moder"/"Fader" (pappersintygets PDF-mall i app/ undantagen)
#   Fritext om döden               Dödsorsak — inte "Dödsnotering" eller "Dödsanteckning"
#   Okänt kön                      Okänt (kön är ett t-ord); Okänd bara om ett en-ord (okänd mor, okänd kanin)
#   Registrerad kanin              inskriven i stamboken med intyg (papper eller digitalt) och därmed individnummer
#
# Söker i next-app/messages/sv.json och next-app/src/**/*.{ts,tsx} (utom tester). Ord inne i
# kodidentifierare (camelCase, snake_case) räknas inte. FORBIDDEN skiljer inte på versal och
# gemen, CASED gör det. Legitima träffar listas i scripts/ui-terms-allow.txt som "sökväg:regex".
# Exit 1 med fil:rad-lista vid träff.
set -euo pipefail
export LC_ALL=C.UTF-8 # grep -i och [[:lower:]] känner bara igen åäö i en UTF-8-locale
cd "$(dirname "$0")/.."

FORBIDDEN='genbanksnummer|kaninnummer|certifikat|överlåt|byter hem|bekräfta flytt|sälj / flytta|genbanksmanager'
FORBIDDEN+='|kullar & parningar|besättningshistoria|rapportera som död|dödsnotering|dödsanteckning'
FORBIDDEN+='|försäljningsdatum|köpdatum|lista över individer'
# Versal mitt i menyvalet, och Moder/Fader som hel etikett: i en sträng eller JSX-text
# ("Moder", >Moder<) eller ensam på raden, så att moderId och "Moder Jord" inte träffas.
CASED="Min Besättning|Alla Kaniner|(^[[:space:]]*|[\"'>])(Moder|Fader)([\"'<]|[[:space:]]*$)"
# Ett gement ord följt av rasnamnet med versal, t.ex. "för Gotlandskanin".
BREED='(^|[^[:alpha:]])[[:lower:]]+ (Gotlands|Melleruds)kanin'
IDENT='[[:alnum:]_]*([[:lower:]][[:upper:]]|_)[[:alnum:]_]*'
ALLOW=scripts/ui-terms-allow.txt

files=(next-app/messages/sv.json)
while IFS= read -r -d '' f; do files+=("$f"); done < <(
	find next-app/src -type f \( -name '*.ts' -o -name '*.tsx' \) \
		-not -path '*/__tests__/*' -not -name '*.test.*' -print0
)
mapfile -t allow < <(grep -vE '^[[:space:]]*(#|$)' "$ALLOW")

# grep: 1 = ingen träff (OK), 2 = fel (fäller grinden via set -e).
hits=$(grep -nHiE "$FORBIDDEN" "${files[@]}" || [ $? -eq 1 ])
hits+=$'\n'$(grep -nHE "$BREED" "${files[@]}" || [ $? -eq 1 ])
hits+=$'\n'$(grep -nHE "$CASED" "${files[@]}" || [ $? -eq 1 ])

fail=0
while IFS= read -r hit; do
	[ -n "$hit" ] || continue
	file=${hit%%:*} rest=${hit#*:}
	line=${rest%%:*}
	read -r text <<<"${rest#*:}"
	code=$(sed -E "s/$IDENT//g" <<<"$text")
	[[ ${code,,} =~ $FORBIDDEN || $code =~ $BREED || $code =~ $CASED ]] || continue
	for entry in "${allow[@]}"; do
		[[ $file == "${entry%%:*}" && $text =~ ${entry#*:} ]] && continue 2
	done
	printf '%s:%s: %s\n' "$file" "$line" "${text:0:160}"
	fail=$((fail + 1))
done < <(sort -u <<<"$hits")

if [ "$fail" -gt 0 ]; then
	echo "UI-termer: $fail otillåtna träffar. Kanonisk lista: scripts/check-ui-terms.sh, undantag: $ALLOW" >&2
	exit 1
fi
echo "UI-termer: OK"
