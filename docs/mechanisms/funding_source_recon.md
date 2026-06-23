# Dossier — reconnaissance des sources officielles (funding cash-and-carry, ETH)

> **Reconnaissance documentaire RÉALISÉE (docs officielles uniquement, aucun appel aux endpoints de
> données). Date d'accès : 2026-06-23 UTC.** Périmètre : **ETH spot + ETH perp sur UNE SEULE venue**
> (pas de multi-venue ; `funding_acquisition_spec.md §11`).
>
> **Décision humaine (2026-06-23) : OKX** (couple `ETH-USDT` spot + `ETH-USDT-SWAP` perp linéaire USDT),
> **Binance conservée comme alternative NON retenue**. Le choix repose **uniquement** sur la **rétention
> d'historique funding documentée** — **pas** sur une promesse de rentabilité ni de liquidité (exclue,
> §6). Le périmètre + la fenêtre sont figés dans `funding_acquisition_spec.md` **Annexe A**.
>
> Les valeurs **par instrument** (`ctVal`, `ctMult`, cap/floor, intervalle effectif) sont **dynamiques**
> et **non lues ici** : à capturer/archiver/hasher au début de l'acquisition (Annexe A.3). **Les exemples
> numériques de documentation ne sont PAS des paramètres certifiés d'`ETH-USDT-SWAP`.**

## 1. Périmètre retenu

- **OKX**, single-venue : spot `ETH-USDT` + perp `ETH-USDT-SWAP` (linéaire, marge/règlement USDT).
- **Pas de sélection ni bascule multi-venue** (mécanisme futur séparé). **Aucune collecte** tant que
  l'Annexe A n'est pas validée+commitée et la première collecte explicitement autorisée.

## 2. Candidats

- **OKX — RETENU.** | **Binance — alternative NON retenue** (conservée pour mémoire, §5).

## 3. Grille de reconnaissance (remplie, sources officielles)

| Point | **OKX** `ETH-USDT-SWAP` *(retenu)* | **Binance** `ETHUSDT` USDⓈ-M *(alternative)* | Réf. |
|---|---|---|---|
| Spot ETH (id) | `ETH-USDT` | `ETHUSDT` | [2] / [8] |
| Perp (`perp_market_id`) | `ETH-USDT-SWAP` | `ETHUSDT` (USDⓈ-M perp) | [2] / [5][9] |
| Type de contrat | linéaire (`ctType=linear`) | linéaire (USDⓈ-M) | [2] / [5] |
| Devise marge/règlement | USDT (`settleCcy`) | USDT (`marginAsset`) | [2] / [5] |
| Multiplicateur/unité | `ctVal × ctMult` — **DYNAMIQUE → capturer à t0 (Annexe A.3)** | **quantité en ETH, aucun multiplicateur** | [2] / [5] |
| Intervalle + calendrier | 8 h déf. 00:00/08:00/16:00 UTC (1/2/4 h possible) ; **effectif = dynamique** | 8 h, 00:00/08:00/16:00 UTC | [1] / [4] |
| Convention de signe | funding > 0 ⇒ **longs paient shorts** | funding > 0 ⇒ **longs paient shorts** | [1] / [4] |
| Fixation / settlement | settlement 00/08/16 UTC ; premium moyenné (n=480/min) | settlement 00/08/16 UTC ; premium moyenné | [1] / [4] |
| Cap funding (formule) | `clamp[(avgP+clamp(int−avgP,±0,05%))/(8/N), cap, floor]` ; **cap/floor par instrument = dynamique** | `[avgP+clamp(int−P,±0,05%)]/(8/N)` ; cap/floor = **±0,75 × Maintenance Margin Ratio** ; `adjustedFundingRateCap/Floor` par symbole | [1] / [4][6] |
| Endpoint funding documenté | `GET /api/v5/public/funding-rate-history` | `GET /fapi/v1/fundingInfo` + `GET /fapi/v1/fundingRate` | [2] / [6b][7] |
| Historique — pagination/limites | `before/after/limit` (**max à confirmer**) + téléchargement *Historical Market Data* | `limit` déf. 100 / **max 1000**, `startTime/endTime`, ordre croissant, 500/5min | [2][3] / [7] |
| **Rétention ≥ 1 an** | ✅ **DOCUMENTÉE** : « *Historical perpetual funding rates from March 2022 onwards* » | ❌ **NON documentée** dans la doc API (rétention non précisée) | **[3] / [7]** |

> **Restent dynamiques / non documentaires** (à obtenir et archiver+hasher à t0, jamais figés en dur) :
> `ctVal`, `ctMult`, cap/floor par instrument, intervalle effectif. **`limit` max OKX** et **couverture
> par instrument / granularité du téléchargement OKX** : à confirmer au démarrage.

## 4. Différenciateur décisif

Mécanismes équivalents (8 h, 00/08/16 UTC, longs paient shorts, clamp cap/floor). Le **seul critère
documentaire décisif** pour une **série d'un an certifiée** = la **rétention d'historique funding** :
**OKX la documente** (mars 2022→) ; **Binance ne la documente pas**.

## 5. Décision & alternative

- **RETENU : OKX** — `ETH-USDT` spot + `ETH-USDT-SWAP` perp (linéaire USDT). **Motif unique : rétention
  funding documentée** (≥ 1 an). Pas de promesse de rentabilité/liquidité.
- **NON retenu : Binance** (conservé). **Avantages documentés** : contrat dénommé en ETH **sans
  multiplicateur** ; `fundingInfo` par symbole explicite (cap/floor/intervalle) ; docs par endpoint
  (limit max 1000). **Réserve qui l'écarte** : **rétention funding non documentée** (doc API).
- **Réversibilité** : si une vérification documentaire ultérieure établit une rétention funding Binance
  ≥ 1 an, ses avantages (contrat simple, `fundingInfo` explicite) pourraient justifier un réexamen —
  **décision humaine**.

## 6. Protocole de reconnaissance documentaire (appliqué)

Pour chaque point de la grille §3 : **source officielle uniquement** ; **URL exacte** ; **date d'accès
(UTC)** ; **version/date de la doc** si dispo ; **extrait** verbatim (cf §7). Règles : **aucun appel aux
endpoints de données** (on lit la doc, pas les données) ; **la liquidité n'est pas une donnée
documentaire** (hors critères) ; un point non sourçable reste « à vérifier ».

## 7. Sources (accès 2026-06-23 UTC)

1. **OKX — Funding fee mechanism** (help, MAJ 2026-06-03) — https://www.okx.com/en-us/help/iv-introduction-to-perpetual-swap-funding-fee — « *every 8 hours (00:00, 08:00, and 16:00 UTC) by default…* » ; « *When the funding rate is positive, traders with long positions pay a funding fee to traders with short positions.* » ; formule clamp cap/floor.
2. **OKX — API guide docs-v5** (Get instruments ; Get funding rate history) — https://www.okx.com/docs-v5/en/ — `ctVal`, `ctMult`, `ctType:"linear"`, `settleCcy` ; instId `ETH-USDT-SWAP` / `ETH-USDT` ; params `instId, before, after, limit`.
3. **OKX — Historical Market Data** — https://www.okx.com/en-us/historical-data — « *Historical perpetual funding rates from March 2022 onwards.* » (couverture par instrument & granularité **non précisées** sur la page → à confirmer).
4. **Binance — Introduction to Futures Funding Rates** (FAQ, MAJ 2026-03-06) — https://www.binance.com/en/support/faq/introduction-to-binance-futures-funding-rates-360033525031 — « *default funding interval is every 8 hours at 00:00, 08:00, and 16:00 (UTC)* » ; « *traders long… will pay a funding fee to traders on the opposing side* » ; « *Cap = 0.75 \* Maintenance Margin Ratio* ».
5. **Binance — USDⓈ-M Exchange Information** — https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Exchange-Information — `contractType:"PERPETUAL"`, `marginAsset:"USDT"`, quantité en actif de base, **pas de multiplicateur** (schéma ; valeurs ETHUSDT via endpoint).
6. **Binance — Get Funding Info** — https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Get-Funding-Rate-Info — `"adjustedFundingRateCap":"0.025"`, `"adjustedFundingRateFloor":"-0.025"`, `"fundingIntervalHours":8` (**exemples**, non certifiés pour ETHUSDT). 6b. *Funding endpoint* `GET /fapi/v1/fundingInfo`.
7. **Binance — Get Funding Rate History** — https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Get-Funding-Rate-History — « *Default 100; max 1000* » ; `startTime/endTime` inclusifs ; « *In ascending order.* » ; **rétention non précisée** (« does not specify how far back »).
8. **Binance — Spot, General endpoints / Exchange Information** — https://developers.binance.com/docs/binance-spot-api-docs/rest-api/general-endpoints — `symbol` / `baseAsset:"ETH"` / `quoteAsset:"USDT"` (schéma).
9. **Binance — ETHUSDT USDⓈ-Margined Perpetual** (produit) — https://www.binance.com/en/futures/ethusdt.

## 8. Prochaine étape (hors de ce dossier)

Après **validation + commit** de cette décision (Annexe A figée) : sur **autorisation explicite** de la
première collecte, **capturer les métadonnées dynamiques** (Annexe A.3) — archivées + hashées +
horodatées — **puis** collecter l'historique funding `ETH-USDT-SWAP` sur la fenêtre figée. **Aucune
collecte ni réseau** avant cette autorisation.
