# Google-inloggning lokalt

Google avvisar OAuth-redirect-URI:er på `*.localhost`-subdomäner
(`Error 400: invalid_request`, ej publik TLD). Bara exakt `localhost` är
undantaget. Två sätt fungerar lokalt:

1. **`https://localhost`** utan subdomän (dev-stacken via nginx).
2. **Ett dev-alias** som är subdomän till en domän du redan äger och har
   auktoriserat i Google Cloud Console, pekat på `127.0.0.1` i `/etc/hosts`.
   `nginx/herdbook-local-production.conf` innehåller föreningens alias;
   byt till dina egna.

## Skapa en OAuth-klient (Cloud Console)

Använd en **egen klient för utveckling**, aldrig produktionens. Klient-id
bakas in i Next.js-imagen vid bygget, så en dev-klient i produktion eller
tvärtom ger `origin_mismatch` vid inloggning.

- Typ: Web application.
- Authorized redirect URI (Flask-flödet):
  `https://<ditt-dev-värdnamn>/api/login/google/back/google/authorized`
- Authorized JavaScript origin (Google Identity Services-knappen och One
  Tap): `https://<ditt-dev-värdnamn>`

## Konfigurera

- `config/auth.ini`, sektion `[google]`: `key=` (klient-id) och `secret=`.
  Se README-avsnittet "External authenticators".
- `.docker/next-app-variables.env`: `NEXT_PUBLIC_GOOGLE_CLIENT_ID` = samma
  klient-id som `key=`, annars delar inte GIS-knappen och Flask-flödet
  klient.
- Cert: nginx-certbots lokala CA utfärdar ett self-signed-cert vid start;
  acceptera varningen i webbläsaren en gång per värdnamn.
