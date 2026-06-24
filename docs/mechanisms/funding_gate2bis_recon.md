# Dossier — Gate §2 bis : correspondance OHLC ↔ TWAP interne (funding ETHUSDT)

> **Levée documentaire RÉALISÉE (sources officielles Binance uniquement). Date d'accès : 2026-06-24 UTC.**
> AUCUN endpoint de données, AUCUN code, AUCUNE collecte, AUCUN calcul.
>
> **Verdict : `GATE_2BIS_NON_FRANCHIE` (correspondance `NON_PROUVÉE`).** La correspondance entre l'OHLC de
> `premiumIndexKlines` et l'**échantillonnage TWAP interne** du funding (5 s / 5760 points, pondéré)
> **n'est pas démontrée** par une source officielle — **et n'est pas réfutée** (donc **jamais**
> `MODELE_REJETE`). Règle appliquée : *aucune correspondance déduite d'une similarité de nom ; sans source
> officielle l'affirmant explicitement, la gate échoue.*

## Points — source exacte · date · extrait · verdict

### 1. Granularité historique de `premiumIndexKlines` → **INDÉTERMINÉ**
- **Source** : *Premium Index Kline Data*, `GET /fapi/v1/premiumIndexKlines` (accès 2026-06-24) — `interval`
  est un `ENUM` **non énuméré sur la page** ; la page **ne précise pas** la profondeur d'historique (« *the
  page does not specify how far back historical premium index kline data is available* », rétention non
  déclarée).
- **Source** : *Common Definition* (accès 2026-06-24) — énumération partagée des intervalles :
  « *1s, 1m, 3m, 5m, 15m, 30m, 1h, 2h, 4h, 6h, 8h, 12h, 1d, 3d, 1w, 1M* » (1s = plus fin **possible**).
- **Verdict** : le pas le plus fin **théorique** est 1 s, mais l'endpoint **ne déclare ni rétention ni
  profondeur** ; la disponibilité réelle (et à quel pas) de `premiumIndexKlines` ETHUSDT sur
  2025-06-23 → 2026-06-23 **n'est pas établie** sans sonde (interdite). → **INDÉTERMINÉ**.

### 2. Définition du champ premium → **NON_PROUVÉE**
- **Source** : *Premium Index Kline Data* (accès 2026-06-24) — overview « *Premium index kline bars* », mais
  les champs `Open / High / Low / Close` **ne sont pas définis** comme valeurs de premium index ; **aucune
  définition** de la valeur n'est donnée.
- **Source** : *FAQ funding* (accès 2026-06-24) — définit le premium index du funding : « *Premium Index (P)
  = [Max(0, Impact Bid Price − Price Index) − Max(0, Price Index − Impact Ask Price)] / Price Index* ».
- **Verdict** : la **définition de P** (entrée du funding) est connue côté FAQ, mais **aucune source
  n'affirme** que les champs de `premiumIndexKlines` **sont** ce P. Le lien reposerait sur le seul **nom**
  « premium index » — l'inférence explicitement interdite. → **NON_PROUVÉE**.

### 3. Correspondance OHLC ↔ TWAP interne → **NON_PROUVÉE** *(décisif)*
- **Source** : *Premium Index Kline Data* (accès 2026-06-24) — « *the page makes no mention of funding
  rates, funding-rate calculations, time-weighted averages, or any correspondence between these premium
  index klines and funding rate mechanisms* ».
- **Source** : *FAQ funding* (accès 2026-06-24) — le TWAP interne est défini sur des **points discrets** :
  « *Binance calculates the premium index every 5 seconds (12 premium index data points in a minute) … 5,760
  premium index data points for the 8-hour funding interval* », pondération « *Average Premium Index (P) =
  (1×Premium_Index_1 + 2×Premium_Index_2 + … + n×Premium_Index_n) / (1+2+…+n)* » ; **la FAQ ne lie ce
  moyennage à aucun produit kline/candlestick**.
- **Verdict** : ni la page kline ni la FAQ n'affirment qu'une agrégation de `premiumIndexKlines` reproduit
  le TWAP interne (5 s/5760, pondéré). **Aucune source officielle ne l'affirme explicitement.**
  → **NON_PROUVÉE** (non démontrée **et** non réfutée).

### 4. Versions de formule sur 2025-06-23 → 2026-06-23 → **INDÉTERMINÉ**
- **Source** : *FAQ funding* (« *Updated on 2026-03-06 07:01* », accès 2026-06-24) — donne la formule
  **courante**, **sans** historique de versions ni date d'effet.
- **Source** : *Change Log* dérivés (accès 2026-06-24) — **aucune entrée** mentionnant funding rate /
  funding interval / premium index / interest rate / mark price / cap-floor entre 2025-06-01 et 2026-06-24.
- **Verdict** : la formule **courante** est documentée (MAJ 2026-03-06), mais **aucune source n'affirme** la
  (les) version(s) en vigueur **au début** de la fenêtre (2025-06-23) ni leur stabilité sur tout
  l'intervalle ; l'absence d'entrée au change-log n'est **pas** une preuve positive (il logge des
  changements d'API, pas nécessairement la formule). → **INDÉTERMINÉ**.

## Résultat & conséquence

| Point | Verdict |
|---|---|
| 1. Granularité historique | INDÉTERMINÉ |
| 2. Définition du champ premium | NON_PROUVÉE |
| 3. Correspondance OHLC ↔ TWAP interne *(décisif)* | **NON_PROUVÉE** |
| 4. Versions de formule sur la fenêtre | INDÉTERMINÉ |

**Gate §2 bis = `GATE_2BIS_NON_FRANCHIE`** (jamais `MODELE_REJETE` : la correspondance n'est **pas
démontrée**, elle n'est **pas réfutée**). Conséquences (per `funding_model_validation_plan.md` §2 bis/§6) :

- **Reconstruction historique ex ante NON PROUVÉE** ; `MODELE_VALIDE` **inatteignable avec les sources
  actuelles** ; `MODELE_REJETE` également exclu (absence de preuve ≠ réfutation).
- Phase 2A **plafonnée à `FIDELITE_MESUREE`** (distribution mesurée, sans réussite/échec).
- **Aucune collecte `premiumIndexKlines` ne sera lancée pour une simple `FIDELITE_MESUREE`.**
- La reconstructibilité **n'est pas acquise** ; **aucune** étude économique ne suit.

## Condition de réouverture (l'une OU l'autre)

1. Une **source officielle Binance** affirmant **explicitement** la correspondance entre l'OHLC de
   `premiumIndexKlines` (ou un champ précis) et l'**échantillonnage TWAP interne** du funding (5 s / 5760
   points, pondération) ; **OU**
2. Un **accès à des observations historiques à 5 s réellement utilisées par Binance** (les points de premium
   index effectivement échantillonnés pour le funding), permettant une reconstruction **sans hypothèse de
   correspondance**.

Sans l'un de ces deux éléments, la gate reste **NON_FRANCHIE** et `MODELE_VALIDE` **inatteignable**.

## Sources (accès 2026-06-24 UTC, docs officielles uniquement)

1. **Premium Index Kline Data** — https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Premium-Index-Kline-Data — `interval` ENUM non énuméré ; « premium index kline bars » ; **aucune** mention de funding/TWAP/correspondance ; rétention non déclarée.
2. **Introduction to Futures Funding Rates** (FAQ, « Updated on 2026-03-06 07:01 ») — https://www.binance.com/en/support/faq/introduction-to-binance-futures-funding-rates-360033525031 — premium index 5 s → 5760 points, pondération `(1×P₁+…+n×Pₙ)/(1+…+n)` ; **aucun** lien à un produit kline/candlestick ; pas d'historique de versions.
3. **Common Definition** (intervalles klines) — https://developers.binance.com/docs/derivatives/usds-margined-futures/common-definition — « 1s, 1m, 3m, 5m, 15m, 30m, 1h, 2h, 4h, 6h, 8h, 12h, 1d, 3d, 1w, 1M ».
4. **Change Log (dérivés)** — https://developers.binance.com/docs/derivatives/change-log — aucune entrée funding/premium/interest/mark/cap-floor entre 2025-06-01 et 2026-06-24.
5. **Mark Price** (`premiumIndex`, instantané live) — https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Mark-Price — `lastFundingRate`/`interestRate`/`nextFundingTime` **sans** `startTime/endTime` (rappel : le prédit live n'est pas historisé).

> **Aucune collecte ni exécution.** Ce dossier établit seulement que la correspondance OHLC ↔ TWAP interne
> est **non prouvée** (et non réfutée) avec les sources officielles actuelles.
