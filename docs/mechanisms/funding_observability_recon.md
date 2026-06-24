# Dossier — Phase 1.5 : observabilité ex ante / ex post (funding cash-and-carry, ETHUSDT)

> **Reconnaissance documentaire RÉALISÉE (docs officielles Binance uniquement). Date d'accès :
> 2026-06-24 UTC.** AUCUN endpoint de données appelé, AUCUN code, AUCUNE collecte. Aucune statistique
> économique, annualisation, calibration, règle d'entrée ni PnL.
>
> **Question :** Binance fournit-il *historiquement* (a) un funding **prédit/courant observé AVANT
> règlement** (information **ex ante**) et (b) des **quotes spot/perp historiques synchronisables** pour
> reconstruire un cycle réel ? Le rapport sépare STRICTEMENT le **taux réglé ex post** de
> l'**information disponible ex ante**.
>
> **Verdict (corrigé 2026-06-24) : `RECONSTRUCTION_CANDIDATE` / `NON_CONCLUANT`** (§5). La formule **et**
> la primitive historique (`premiumIndexKlines`) existent — donc *non* `FORWARD_ONLY` — **mais leur
> fidélité n'est pas encore démontrée**, donc *non* `RECONSTRUCTIBLE`. La démonstration de fidélité est
> l'objet du **plan Phase 2A** (`funding_model_validation_plan.md`).
>
> **MAJ 2026-06-24 — gate §2 bis levée → `GATE_2BIS_NON_FRANCHIE` :** la correspondance OHLC
> `premiumIndexKlines` ↔ TWAP interne (5 s/5760) **n'est pas démontrée par une source officielle** (ni
> réfutée). ⇒ **reconstruction historique ex ante NON PROUVÉE** ; `MODELE_VALIDE` **inatteignable avec les
> sources actuelles** ; **aucune collecte `premiumIndexKlines` pour une simple `FIDELITE_MESUREE`**. Détail :
> `funding_gate2bis_recon.md`. Réouverture : source officielle prouvant la correspondance OHLC ↔
> échantillonnage TWAP, **ou** accès aux observations historiques **5 s** réellement utilisées par Binance.

## 1. Pourquoi la distinction ex ante / ex post est décisive

La décision d'entrée d'un cycle cash-and-carry (long spot + short perp) se prend **ex ante** : avant un
règlement, on décide sur la base du funding **anticipé** et de la base courante. Le taux **réglé** n'est
connu qu'**ex post** (au règlement). **Utiliser le taux réglé comme s'il était le signal d'entrée = biais
de look-ahead** : on injecterait une information du futur dans une décision passée. La faisabilité d'un
backtest honnête dépend donc de la **reconstructibilité de l'information ex ante**, pas seulement de la
disponibilité du taux réglé (déjà acquis en Phase 1).

Issues possibles :
- **`RECONSTRUCTIBLE`** : l'ex ante des règlements passés est reconstructible **et la fidélité est
  démontrée**.
- **`RECONSTRUCTION_CANDIDATE` / `NON_CONCLUANT`** : la primitive historique **et** la formule existent,
  **mais la fidélité reste à prouver** (état actuel — voir Phase 2A).
- **`FORWARD_ONLY`** : aucune primitive historique ; l'ex ante n'est observable que vers l'avant (live),
  impossible à reconstituer pour le passé.

**État retenu : `RECONSTRUCTION_CANDIDATE` / `NON_CONCLUANT`.**

## 2. Signaux d'un cycle réel et leur temporalité

| Étape du cycle | Signal nécessaire | Temporalité de la décision |
|---|---|---|
| Entrée | funding **anticipé** du prochain règlement + base courante (perp − spot) | **ex ante** |
| Règlement | funding **réglé** appliqué (00/08/16 UTC) | **ex post** (encaissé) |
| Sortie | base courante (perp − spot) au moment de déboucler | **ex ante** |

## 3. Grille d'observabilité (sources officielles, §7)

| Signal | Source officielle | Historique ? | Nature |
|---|---|---|---|
| Funding **réglé** (ex post) | `GET /fapi/v1/fundingRate` (`startTime/endTime`, croissant) | ✅ **HISTORIQUE** | **Enregistré** — Phase 1 certifiée (1095 règlements) |
| Funding **prédit/courant** (ex ante) | `GET /fapi/v1/premiumIndex` → `lastFundingRate`, `interestRate`, `nextFundingTime` | ❌ **LIVE seulement** (aucun `startTime/endTime`) | **NON enregistré** historiquement |
| **Indice de prime** P (entrée cœur du funding) | `GET /fapi/v1/premiumIndexKlines` (`startTime/endTime`, max 1500) | ✅ **HISTORIQUE** | **Primitive de reconstruction** (fidélité à prouver) |
| **Mark price** | `GET /fapi/v1/markPriceKlines` (`startTime/endTime`, max 1500) | ✅ **HISTORIQUE** | Primitive (valorisation perp) |
| **Index price** | `GET /fapi/v1/indexPriceKlines` (famille klines) | ⚠️ **à confirmer** (page exacte non lue) | Primitive |
| **Formule funding** (P → taux) | FAQ funding (formule, TWAP, interest, clamp) | ✅ documentée | Modèle de reconstruction |
| Quotes **spot** (échangées) | `GET /api/v3/klines` (`startTime/endTime`, 1m, max 1000) | ✅ **HISTORIQUE** | OHLC = **prix échangés**, **jamais bid/ask exécutable** |
| Quotes **perp** (échangées) | `GET /fapi/v1/klines` (klines futures) | ✅ **HISTORIQUE** | OHLC = prix échangés (proxy) |
| Bulk historique | `data.binance.vision` : `aggTrades`, `klines`, `trades` (spot+futures) | ✅ documenté | Téléchargement de masse |
| **bid/ask exécutable** (`bookTicker`) | `data.binance.vision` bulk | ⚠️ **NON documenté** dans le README lu → **à vérifier** | Manquant pour l'instant |

## 4. Séparation stricte — réglé ex post vs disponible ex ante

- **Ex post (enregistré, faisant foi).** Le **seul** chiffre de funding stocké par règlement passé est le
  taux **réglé** (`fundingRate`). C'est ce que la Phase 1 a certifié. Il n'est connu **qu'au** règlement.
- **Ex ante (NON enregistré directement).** Le taux **prédit/courant** affiché avant règlement
  (`premiumIndex.lastFundingRate`) est un **instantané live** : Binance **n'expose aucun historique** de
  cette valeur. Le récupérer pour un règlement passé est **impossible en lecture directe**.
- **Candidat à reconstruction (fidélité non prouvée).** L'**indice de prime** P — entrée cœur du funding —
  est **historiquement disponible** (`premiumIndexKlines`), et la **formule est documentée** :
  > « Funding Rate (F) = [Average Premium Index (P) + clamp(interest rate − Premium Index (P), 0.05%,
  > −0.05%)] / (8 / N) » ; interest rate **0,01 %/intervalle** par défaut ; P = TWAP sur l'intervalle
  > (5 s, 5760 points, poids croissants) ; clamp/cap ETHUSDT **±0,30 %** (Phase 0B).
  Le taux **prédit** affiché est lui-même « *an estimation of the last 8 hours of the premium index* »
  (TWAP glissant 8 h) ; le taux **réglé** est le TWAP de l'**intervalle** de règlement. Les deux
  **pourraient** se reconstruire depuis la même série P historique, avec des fenêtres différentes —
  **sous réserve que la fidélité soit démontrée** (Phase 2A).

## 5. Verdict : `RECONSTRUCTION_CANDIDATE` / `NON_CONCLUANT`

**Ni `FORWARD_ONLY`, ni (encore) `RECONSTRUCTIBLE`.** `FORWARD_ONLY` s'appliquerait si le seul accès au
signal ex ante était l'instantané live (`premiumIndex`), sans primitive historique — **ce n'est pas le
cas** : la **primitive historique existe** (`premiumIndexKlines`, complétée par `markPriceKlines`) et la
**formule est documentée**. Mais `RECONSTRUCTIBLE` exigerait que la **fidélité** de la reconstruction soit
**démontrée** — elle ne l'est pas. La formule et la primitive sont des **conditions nécessaires, non
suffisantes** ; la concordance reconstruit↔réglé reste à prouver. → **`RECONSTRUCTION_CANDIDATE`
(NON_CONCLUANT)**, en attente de la validation **Phase 2A**.

**Pourquoi la fidélité n'est pas démontrée — 2 raisons de fond (objet de la Phase 2A) :**

1. **Risque de modèle (non quantifié).** Le taux reconstruit (TWAP de `premiumIndexKlines` — au pas kline,
   p.ex. 1 m — qui **approxime** le vrai TWAP à 5 s / 5760 points, plus `interest rate` et `clamp`)
   **n'a pas été comparé** au `fundingRate` réglé certifié (Phase 1). Tant que l'écart reconstruit↔réglé
   n'est pas mesuré et borné par une tolérance préenregistrée, la fidélité est **inconnue**.
2. **Quotes exécutables absentes.** Les sources confirmées donnent des **prix échangés** (klines OHLC) et
   l'indice de prime (qui embarque l'impact bid/ask **côté funding**), mais **aucun bid/ask exécutable
   vérifié** pour les **jambes** spot/perp (`bookTicker` bulk = **à vérifier**). **Les klines restent des
   proxys de prix, jamais des quotes exécutables.**

## 6. Recette de reconstruction (cartographie documentaire — AUCUN code, AUCUNE collecte)

Pour mémoire, sans l'exécuter : le funding ex ante d'un règlement passé se reconstruirait depuis
`premiumIndexKlines` (série P) en appliquant la formule documentée (TWAP fenêtre d'intervalle pour le
réglé ; TWAP glissant 8 h pour l'affiché), avec `interest rate` documenté et le `clamp` ±0,05 %, **puis
validation** contre `fundingRate` (Phase 1). La base se reconstruirait depuis perp `klines` − spot
`klines` (proxys de prix) aux horodatages de règlement. **Rien de ceci n'est autorisé ni démontré** tant
que la Phase 2A n'a pas établi la fidélité.

## 7. Sources (accès 2026-06-24 UTC, docs officielles uniquement)

1. **Binance — Get Funding Rate History** — https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Get-Funding-Rate-History — `fundingRate` historique (`startTime/endTime`, croissant). *Taux **réglé** ex post.*
2. **Binance — Mark Price** (`premiumIndex`) — https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Mark-Price — renvoie `markPrice, indexPrice, estimatedSettlePrice, lastFundingRate, interestRate, nextFundingTime, time` ; **aucun** `startTime/endTime` → **instantané live**.
3. **Binance — Premium Index Kline Data** — https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Premium-Index-Kline-Data — `GET /fapi/v1/premiumIndexKlines` ; params `symbol, interval, startTime, endTime, limit` (déf. 500 / **max 1500**) ; « *If startTime and endTime are not sent, the most recent klines are returned* » → **historique**.
4. **Binance — Mark Price Kline Candlestick Data** — https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Mark-Price-Kline-Candlestick-Data — `GET /fapi/v1/markPriceKlines` ; mêmes params (max 1500) → **historique**.
5. **Binance — Introduction to Futures Funding Rates** (FAQ) — https://www.binance.com/en/support/faq/introduction-to-binance-futures-funding-rates-360033525031 — formule `F = [avg P + clamp(interest − P, ±0,05%)] / (8/N)` ; interest **0,01 %/intervalle** (déf. ; 0 % p.ex. ETHBTC) ; P = TWAP 8 h (5 s, 5760 pts, poids croissants) ; affiché = « *estimation of the last 8 hours of the premium index* » ; réglé = fenêtre complète d'intervalle ; cap `±0,75 × MMR`.
6. **Binance — Spot Kline/Candlestick** — https://developers.binance.com/docs/binance-spot-api-docs/rest-api/market-data-endpoints — `GET /api/v3/klines` ; `symbol, interval, startTime, endTime, timeZone, limit` (déf. 500 / **max 1000**) → **historique** ; OHLCV (prix **échangés**). `uiKlines` analogue.
7. **Binance — Public Data** — https://github.com/binance/binance-public-data — `data.binance.vision/data/{spot|futures}/{daily|monthly}/{dataType}/{symbol}/{interval}/` ; types **documentés** : `aggTrades`, `klines`, `trades` (spot + futures). `bookTicker`/`markPriceKlines`/`premiumIndexKlines`/`fundingRate`/`metrics` **non documentés** dans le README lu → **à vérifier**.

## 8. Reste à vérifier (gates ouvertes — documentaire)

- **`bookTicker` bulk** (bid/ask exécutable historique) sur `data.binance.vision` : existence + colonnes.
- **`indexPriceKlines`** : page officielle exacte (famille klines, présumée historique).
- **Interest rate ETHUSDT sur la fenêtre** : confirmer le régime par défaut (0,01 %/intervalle) et l'absence
  d'épisode spécial ; idem cap/floor dynamiques (Phase 0B : ±0,30 %).
- **Fidélité TWAP** : granularité kline (1 m) vs TWAP réel 5 s — borne d'erreur à établir lors de la
  validation (Phase 2A).

> **Phase économique INTERDITE sans nouvelle validation humaine.** Ce dossier ne produit aucune
> statistique, annualisation, calibration, règle d'entrée ni PnL : il établit seulement que l'ex ante est
> un **`RECONSTRUCTION_CANDIDATE` (NON_CONCLUANT)** — primitive + formule présentes, **fidélité non
> démontrée** —, distinct du taux réglé ex post. La démonstration de fidélité est l'objet du **plan
> Phase 2A** (`funding_model_validation_plan.md`), à exécuter seulement sur autorisation.
