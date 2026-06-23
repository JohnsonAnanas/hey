# Rapport PHASE 0 — OKX / ETH-USDT-SWAP  *(RECLASSÉ — NON CANONIQUE)*

> **Run NON CANONIQUE** : provenance non figée (runner non versionné au moment du run). Conservé comme
> observation `PHASE0_PARTIEL` **hors chaîne de certification** ; **bruts hors Git, non commités**.
> Source OKX arrêtée à ce stade (REST_NON_CONCLUANT + dataset NON_CONCLUANT).

- **Verdict : `PHASE0_PARTIEL`** — A.3 observé ; A.4 REST **non concluant** ; dataset **non sondé**.
- Fenêtre : 2025-06-23T00:00:00Z → 2026-06-23T00:00:00Z ; créé 2026-06-23T20:15:39Z
- **Provenance (corrigée)** : au moment du run, le runner `phase0_okx_funding.py` **n'était pas suivi**
  par Git → le `git_dirty=false` initial **était FAUX** (corrigé à `true`, `code_versioned=false`). Run
  **conservé comme observation non concluante**, à **reproduire avec le runner versionné** (référençant
  son commit / `runner_sha256`).

## A.3 — paramètres réellement reçus *(observés live, hashés)*
- `instruments` : `ctType=linear`, `ctVal=0.1` (ETH), `ctMult=1`, `settleCcy=USDT`, `lever=100`, `state=live`.
- `funding-rate` : `maxFundingRate=0.0075` / `minFundingRate=-0.0075` ; `fundingTime`→`nextFundingTime` = 8 h ; `formulaType=withRate`, `method=current_period`.
- *(Valeurs OBSERVÉES live ; les exemples de doc ne font pas foi. À figer en Phase 0 versionnée.)*

## A.4 — sonde REST *(NON interprétée)*
- `funding-rate-history?instId=ETH-USDT-SWAP&after=1750723200000&limit=10` → **0 enregistrement**.
- **NON interprété** : la sémantique exacte de `before`/`after` (docs-v5) **n'est pas établie**. Un lot
  vide n'est **ni** « couvre » **ni** « rétention insuffisante ». Sonde correcte à définir **après**
  confirmation de la sémantique.

## Reçus (bruts hors Git, hashés)
- `instruments_A3` — HTTP 200 — 1012 o — sha256 `d06d741d9ddad181…` — `data/raw/funding/okx/phase0/instruments_A3_20260623T201538Z.json`
- `funding_rate_A3` — HTTP 200 — 523 o — sha256 `e480e218b5553329…` — `data/raw/funding/okx/phase0/funding_rate_A3_20260623T201538Z.json`
- `funding_history_probe_A4_REST` — HTTP 200 — 31 o — sha256 `fc24d69479edbb84…` — `data/raw/funding/okx/phase0/funding_history_probe_A4_REST_20260623T201538Z.json`

## Abstentions / motifs
- A.4 REST : sémantique `before`/`after` non établie → sonde **non concluante** (ni couverture ni rejet).
- Dataset *Historical Market Data* : **non sondé** (aucune sonde dataset autorisée pour l'instant).

> Reçus de validation paramètres/capacité **uniquement** — pas une série certifiée, non agrégés, ni
> calibration ni test. **Run et bruts conservés (jamais supprimés). Phase 1 INTERDITE sans nouvelle
> validation humaine.**
