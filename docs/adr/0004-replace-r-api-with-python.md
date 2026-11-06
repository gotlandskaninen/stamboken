---
status: "accepted"
date: 2026-11-06
decision-makers: Jonas
---

# ADR-0004: Python ersätter R-API:et för genetiska beräkningar

## Kontext och problem

Stamboken använde ett separat R-API (Plumber) för inavelskoefficienter,
kinship-matris (Identity-By-Descent) och mean kinship. R-imagen är ~1.5 GB,
kräver en egen container med supervisord och hot-reload, ger två språk i
samma system och är svår att integrera med Flask-logiken.

## Beslutsdrivare

* Resultaten måste vara identiska med R-implementationen.
* Prestandan måste vara likvärdig eller bättre.
* Koden ska vara lätt att underhålla.

## Alternativ

* Behåll R-API:et: avvisat, eftersom det ger stor image, två språk och
  komplex deployment
* Python med grafdatabas (Neo4j): avvisat, eftersom algoritmerna är
  matrisbaserade (Henderson), inte graf-traversering
* Python med NumPy (valt)
* Rust/C++: avvisat, eftersom det är överkill för problemets storlek

## Beslut

Valt alternativ: "Python med NumPy", eftersom det ger ett språk, en liten
footprint och beräkningar direkt i Flask-processen.

Det finns ingen R-container. Modul: `app/utils/genetics.py`.

* **Inbreeding:** Henderson's tabellmetod med iterativ kinship-beräkning.
* **Kinship matrix:** sparse beräkning för endast aktiva individer.
* **Mean kinship:** kolumnmedelvärde av kinship-matrisen.

Vid beslutet (15 852 individer, 861 aktiva) gav inbreeding ~1.6 s, mean
kinship ~7 s och kinship matrix ~6.5 s, alla med exakt match mot R (mean
kinship diff 1e-16). Jämförelsen kördes mot referensdata från produktionen
och ligger därför inte i det publika repot.

### Konsekvenser

* Bra, eftersom en container mindre behöver hanteras och ~1.5 GB R-image
  försvinner.
* Bra, eftersom all backend-kod är Python.
* Dåligt, eftersom vi nu äger beräkningskoden; nya features i optiSel måste
  portas.
* Dåligt, eftersom numerisk precision och edge cases kräver tester mot
  publicerade exempel, låsta referensvärden och verkliga stamtavlor.

### Bekräftelse

* `app/tests/test_genetics_unit.py`: kända stamtavlor ur litteraturen (bl.a.
  Lacy 1989).
* `app/tests/test_genetics_golden.py`: låsta värden för en syntetisk
  stamtavla.

## Mer information

* [ADR-0005: Genetiksida med bevarandemått](0005-genetic-dashboard-metrics.md)

## Ändringslogg

| Datum | Författare | Förändring |
|-------|------------|------------|
| 2026-01 | Jonas | Beslutat |
| 2026-10-27 | Jonas | Baslinje inför publik export |
| 2026-11-06 | Jonas | MADR-format, kortad |
