# Dev- och testnyckel för PDF-signering

`key.pem` och `ca.pem` är ett självsignerat engångscert (`O=Stamboken dev`,
`CN=… NOT FOR PRODUCTION`) som används av tester, dev-stacken och de
vattenstämplade demoinstanserna. Nyckeln är offentlig, den ligger i repot.

`app/utils/settings.py` faller tillbaka på `certs/key.pem` och `certs/ca.pem`
när `PDF_SIGNING_KEY` respektive `PDF_SIGNING_CA` saknas. En produktionsinstans
(`FLASK_ENV=production`, utan `CERT_DEMO_WATERMARK` och med signering på) vägrar
starta med den här nyckeln, oavsett sökväg: `refuse_committed_signing_key` i
settings.py jämför innehållet. Produktionen sätter sin egen nyckel och CA i
`.docker/api-variables.env` (`/config/pdf_signing_key.pem`,
`/config/pdf_signing_ca.pem`); tidigare CA:er listas i `PDF_SIGNING_TRUST_CAS`
så äldre intyg fortsätter verifiera efter en rotation.

Ny engångsnyckel vid behov:

```bash
openssl req -x509 -newkey rsa:4096 -nodes -sha256 -days 7300 \
  -keyout app/certs/key.pem -out app/certs/ca.pem \
  -subj "/C=SE/O=Stamboken dev/CN=Stamboken dev and test signing key, NOT FOR PRODUCTION" \
  -addext "basicConstraints=critical,CA:TRUE"
```
