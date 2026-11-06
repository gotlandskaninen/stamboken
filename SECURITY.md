# Säkerhet

## Rapportera en sårbarhet

Skicka e-post till <security@gotlandskaninen.se>. Lägg inte sårbarheter som
publika issues eller pull requests.

Beskriv vad du hittade, hur det kan återskapas och vilken version eller commit
det gäller. Du får svar inom en vecka.

## Vad som räknas

Allt som låter någon läsa, ändra eller radera data de inte ska komma åt, ta
över ett konto, kringgå inloggning eller behörighet, eller förfalska ett
signerat intyg. Även läckta hemligheter i koden eller historiken räknas. Dev-
och testnyckeln i `app/certs/` är offentlig med avsikt och en
produktionsinstans vägrar starta med den (se
[app/certs/README.md](app/certs/README.md)).

## Personuppgifter

Stamboken hanterar personuppgifter för en förenings medlemmar och uppfödare:
namn, adresser, telefonnummer och e-post. Testa därför bara mot en egen lokal
installation, aldrig mot föreningens drift.

Vi uppskattar ansvarsfull publicering: ge oss tid att åtgärda felet innan du
berättar om det offentligt.
