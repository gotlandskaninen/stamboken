---
status: "accepted"
date: 2026-11-06
decision-makers: Jonas
---

# ADR-0005: Genetiksida med bevarandemått

## Kontext och problem

Genbankskaninerna (gotlandskanin och mellerudskanin) har genetisk mångfald
som måste bevaras. En population kan växa i antal men ändå minska i genetisk
mångfald. Vid beslutet visades bara inavelskoefficient och mean kinship per
individ: ingen populationsöversikt, inga trender, ingen prioritering av
genetiskt viktiga individer och ingen founder-analys.

## Alternativ

* Fortsätta med R-API och nprcgenekeepr: avvisat, eftersom det ger stor
  container, svår integration och långsamhet
* Python-implementation (valt)
* Extern tjänst (t.ex. PMx, Vortex): avvisat, eftersom den inte är
  integrerad och kräver manuell export/import

## Beslut

Valt alternativ: "Python-implementation", eftersom den är integrerad med
Flask, snabb och ett språk. Vi bygger en genetisk dashboard som visualiserar
bevarandemetrics, identifierar genetiskt viktiga individer och ger
avelsrekommendationer.

| Metric | Definition (lärobok) | Beräknas med |
|--------|----------------------|--------------|
| **Inbreeding (F)** | Sannolikheten att två alleler är identiska genom härstamning | Henderson ([ADR-0004](0004-replace-r-api-with-python.md)) |
| **Mean Kinship (MK)** | Genomsnittlig släktskap med den aktiva populationen | Kinship-matrisen |
| **Founder Contributions** | Andel av populationens gener från varje grundare | Stamtavlan |
| **Founder Equivalents (FE)** | FE = 1/Σ(p²) över grundarnas bidrag p | Stamtavlan |
| **Founder Genome Equivalents (FGE)** | Antal grundare som ger samma genetiska mångfald utan förlust genom drift | Gene drop (Monte Carlo) |
| **Effective Pop Size (Ne)** | Ne ≈ 1/(2ΔF) | Inavelsökningen per generation |
| **Genome Uniqueness (GU)** | Sannolikheten att individen bär minst en allel som inget annat djur i populationen bär | Gene drop (andel iterationer) |
| **Avelsrekommendationer** | Parningar som minimerar avkommans MK/F | Kinship-matrisen |

Regler:

* Beräkningarna finns i `app/utils/genetics.py` och
  `app/utils/genetics_service.py`; dashboarden ligger på `/stamboken/genetik`
  med komponenterna i `next-app/src/components/genetics/`.
* Aktiva individer flaggas automatiskt: KRITISK (enda aktiva bäraren av en
  grundare, eller mean kinship under 5:e percentilen), VIKTIG (minst ett av:
  mean kinship under 25:e percentilen, genome uniqueness över 75:e
  percentilen, bär en underrepresenterad grundare), annars NORMAL.
* Tunga beräkningar (gene drop) körs i bakgrunden och cachas. Cachen
  invalideras när stamtavlan ändras. Dashboarden visar cachade värden;
  historiken räknas om med `flask genetics recompute-history <genebank_id>`.
* Metrics är vägledande, inte absoluta sanningar.

### Konsekvenser

* Bra, eftersom avelsstrategin blir datadriven och problem upptäcks tidigt.
* Dåligt, eftersom gene drop är komplex och Monte Carlo kräver CPU-tid.
* Dåligt, eftersom en bugg i algoritmen kan ge fel prioritering och
  uppfödare måste förstå vad metrics betyder.

## Mer information

* [ADR-0004: Python ersätter R-API:et för genetiska beräkningar](0004-replace-r-api-with-python.md)
* [Lacy 1989 - Founder representation](https://onlinelibrary.wiley.com/doi/abs/10.1002/zoo.1430080203)

## Ändringslogg

| Datum | Författare | Förändring |
|-------|------------|------------|
| 2026-01 | Jonas | Beslutat |
| 2026-10-27 | Jonas | Baslinje inför publik export |
| 2026-11-06 | Jonas | MADR-format, kortad |
