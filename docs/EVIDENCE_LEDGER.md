# EVIDENCE LEDGER — registre de preuve faisant foi (MISSION RESET §0/§2)

> Registre **unique et vérifiable** des claims **économiques** du laboratoire. Chaque claim a un
> **statut tranché**, un **niveau de preuve (0→6)**, un **artefact source référencé** avec l'**état explicite de son reçu** (archivé+hashé, ou non — plusieurs claims sont précisément `NON_CONCLUANT` faute de hash), ce qu'elle
> **établit / n'établit pas**, et sa **réouverture**. `docs/STATE.md` reste la photo historique
> (immuable) ; **ce fichier fait foi** pour le statut courant.
>
> **Validé humainement le 2026-06-23** (revue claim par claim ; cf `docs/DECISIONS.md`).
> **PnL net positif défendable à ce jour : AUCUN.** Plusieurs faux positifs ont été correctement
> rejetés — c'est l'actif réel du projet.

## Taxonomie (seuls statuts autorisés — §0)
`INVALIDÉ` · `REJETÉ` (souvent `REJETÉ_SCOPÉ`) · `NON_CONCLUANT` · `LEAD` · `MÉCANISME_CONFIRMÉ` ·
`QUOTE_POSITIVE` · `PAPER_ELIGIBLE`. **`VALIDÉ` est interdit.**

## Niveaux de preuve (§8)
`0` prix affiché · `1` quote exécutable isolée · `2` quote-pair net positif à taille · `3` série
historique de quote-pairs · `4` test hors échantillon préenregistré · `5` shadow ledger · `6` pilote
capital. Aucun passage sans artefacts **et** décision humaine.

## Principes de classement (doctrine affinée — 2026-06-23)
1. **Négatif non hashé ⇒ NON_CONCLUANT, jamais REJETE.** Une observation négative (live ou non
   manifestée) ne porte un REJETE que si elle a un reçu **archivé ET hashé**. Les gates
   inventory/paper restent fermées **indépendamment** du statut de claim.
2. **Un LEAD exige identité économique + route de rebalancing PROUVÉES.** `CONTRACT_SAME` (même
   adresse) + screen brut = **NON_CONCLUANT**, jamais LEAD. **Une quote positive seule ne donne pas un
   LEAD** si identité et rebalancing ne sont pas déjà prouvés.
3. **Phrasé non-existentiel** : « aucune QuotePair nette positive observée aux blocs/échantillons sur
   les routes couvertes » — jamais « il n'existe pas ».
4. **Reverts & abstentions = hors couverture**, jamais comptés comme des négatifs.
5. **Identité = mapping économique canonique** (actif + réseau + contrat/decimals si applicable +
   **transférabilité effective entre venues**), jamais « par adresse » seule.
6. **Réouverture cumulative et ordonnée** (cf chaque claim) : identité+route **archivées** → QuotePair
   fraîche **archivée** → PnL **7-termes** + capacité/stress.

---

## 1. Ledger économique (7 claims)

| # | Claim (périmètre) | Statut | Artefact · hash (preuve) | Établit réellement | N'établit PAS | Réouverture |
|---|---|---|---|---|---|---|
| 1 | **CEX↔CEX « $20M »** — carnet, 91 coins `/USDT` vol24h≥1M, 2026-06-15→22, taker 10bps×2 | **INVALIDÉ** | `runs/20260622T213549Z_cex-cex-20m-rejection/` · git `84fa641` · `cex_monitor.csv` sha256 `1083814f…` ; `data/logs/QUARANTINE.md` ; garde `sim/identity.py` (niv. 1, falsifié) | Artefact d'**identité par ticker** (HYPE profitable 2 sens, 3352/3363 lignes ≥$1M) ; `extract_usd` explosait sur identité fausse | Rien sur un vrai arb CEX↔CEX **bien identifié** ; aucun coût réel (transfert/retrait/latence) | Nouveau run via `cex_extractable_guarded`, **identité = mapping économique canonique** (actif+réseau+contrat/decimals+transférabilité), QuotePair nette à taille, coûts réels |
| 2 | **Atomique Base** — 5 paires ancrées, types v2/v3, grille 1k–250k, 14j v3 / 7j v2, **solo lent** | **REJETÉ_SCOPÉ** | `runs/20260623T091435Z_backfill-v3-fenetre-longue/` · git `7fed31c` · sortie sha256 `db951ffc…` ; corrobore `…backfill-intrachain-base-calibration/` (NON_CONCLUANT) (niv. 3) | « **Aucune QuotePair nette positive observée aux blocs échantillonnés sur les routes couvertes** » : **42 161 tentatives de route → 31 075 QuotePairs couvertes, 0 net-positive**. **Borne supérieure historique à 3 termes** (`gross−frais−gas`) | Pas d'inexistence globale ; cbETH/AERO-ancre (17 435) **hors couverture** ; reverts (11 086) **hors couverture, jamais des négatifs** ; intra-bloc/MEV non vus | Seul négatif **archivé ET hashé**. Les 4 coûts canoniques absents **non modélisés** (non mis à 0) ; **non-négatifs**, donc le rejet directionnel tient. **Un défaut démontré de données/méthode pourrait l'invalider** |
| 3 | **DEX↔CEX majors (ETH/BTC)** — solo lent, 7j | **NON_CONCLUANT** | `data/historical/settle_dex_cex.csv` ; `data/logs/backtest_gap.csv` (net médian −11,9 bps, ~2% actionnable) (niv. 1) | Un basis **même actif** ETH/BTC vs Binance, médian négatif sur la fenêtre | **Négatif NON manifesté/hashé** (aucun run ne référence ces CSV) → ne porte pas un REJETE | Exige **provenance complète + méthode économique reproductible**. Un simple hash+manifeste a posteriori **ne suffit PAS** |
| 4 | **CBBTC** — `base↔eth`, même adresse | **NON_CONCLUANT** | `runs/20260623T090624Z_crosschain-triage/` (screen **153,6 bps**) · git `4e91247` · `crosschain_obs.csv` sha256 `c44ce204…` ; live `verify_crosschain.py` ~7 bps **NON archivé** ; registre `CONTRACT_SAME` (niv. 0→1) | Identité de **contrat** (même adresse) ; un screen agrégé à 153,6 bps (**signal brut**) | Le 153,6 = signal brut ; le **7 bps live n'est pas hashé** → pas de REJETE ; aucun PnL ; redemption/wrap non documentée | **Deux reçus séparés** : ① quote exécutable archivée à taille → confirme/rejette le gap ; ② identité économique + route de rebalancing documentées — **nécessaires avant tout LEAD** |
| 5 | **CTM** — `bsc↔eth`, même adresse — *tag : signal brut cross-chain à mécanisme inconnu* | **NON_CONCLUANT** | `runs/20260623T090624Z_crosschain-triage/` (screen **498,6 bps**) · git `4e91247` ; on-chain OFT revert (bsc+eth) **NON archivé** ; `data/collected/QUARANTINE.md` (CTM = VERIFIED même contrat `0xc8fb…88888888`) (niv. 0) | Identité de **contrat** (même adresse) ; screen agrégé 498,6 bps (brut). Liq/vol GeckoTerminal = **agrégés affichés**, **pas** une capacité exécutable | Signal brut non exécutable ; identité **économique** non prouvée ; transférabilité inconnue (**no-OFT ≠ no-bridge**, contrôle non archivé) ; aucun test exécutable | **GELÉ.** Cumulatif : ① identité économique **+ route redemption/bridge archivées** → ② quotes exécutables **synchronisées** à taille → ③ PnL net complet. **Sans ①, gelé.** Aucune recherche ne chasse un bridge CTM |
| 6 | **VELVET inventaire** — `base↔bsc`, adresses ≠, $1k LI.FI | **NON_CONCLUANT** | `docs/STATE.md §1` (test LI.FI **non hashé**) ; `data/historical/settle_crosschain_velvet.csv` (mid, identité UNVERIFIED, non manifesté) ; registre **`IDENTITY_PRELIMINARY`** (niv. 1, non archivé) | Une série de **basis mid** mean-reverting ; **une** observation live négative (aller-retour). **Magnitudes non vérifiées** (−160 / ~50 / ~3 bps viennent d'un test non archivé) | Le négatif **n'est pas hashé** → pas de REJETE ; identité économique non prouvée ; un seul point $1k ; aucune capacité | **Gates inventory/paper fermées** (`IDENTITY_PRELIMINARY`). Cumulatif : ① identité économique + route officielle archivées → ② QuotePair fraîche archivée (req/resp, timestamp, tailles, coûts, gas) → ③ PnL 7-termes + capacité/stress. **Quote positive seule ≠ LEAD** |
| 7 | **Funding / cash-and-carry** — perp, 21 actifs, 1 an quotidien | **NON_CONCLUANT** | `data/logs/funding_regime.csv` — **série non certifiée** (`breadth=0`, plafond suspect ~10,9 %) (niv. 0→1) | Un **flux de funding** annualisé **rapporté** (~4 %/an, selon une **série non certifiée**) | **Ni rendement net ni stratégie** ; aucun basis exécutable ; 6 coûts de la formule 7-termes non mesurés ; qualité de série non validée | **Orientation documentaire** (jamais LEAD). Ordre : ① mémo de mécanisme écrit+validé → ② contrat/provenance funding **certifiés+hashés** → ③ QuotePair spot/perp → ④ PnL 7-termes + capacité + stress |

**Bilan : 1 INVALIDÉ · 1 REJETÉ_SCOPÉ · 5 NON_CONCLUANT · 0 LEAD · 0 validé.**

---

## 2. Audit des reçus (reproductibilité)

| Claim | Reçu archivé & hashé ? | Conséquence |
|---|---|---|
| CEX↔CEX $20M | ✅ run + QUARANTINE + garde codée | INVALIDÉ tenable |
| Atomique Base | ✅ run v3 (sortie sha256) | **REJETÉ_SCOPÉ tenable** (seul négatif hashé) |
| DEX↔CEX majors | ❌ CSV présents, **non manifestés/hashés** | NON_CONCLUANT |
| CBBTC | ❌ live 7 bps **non manifesté** (153,6 = screen agrégé) | NON_CONCLUANT |
| CTM | ❌ OFT-revert **non manifesté** (498,6 = screen agrégé) | NON_CONCLUANT (gelé) |
| VELVET | ❌ réponse LI.FI brute **non archivée/hashée** | NON_CONCLUANT, gates fermées |
| Funding | ⚠️ série **non certifiée** (breadth=0, plafond suspect) | NON_CONCLUANT (orientation) |

**Règle :** un négatif n'est un REJETE que s'il est **archivé ET hashé** ; sinon NON_CONCLUANT (gates fermées indépendamment).

---

## Annexe A — Outils / infrastructure validés *(hors ledger économique)*

Ce ne sont **pas** des claims économiques (aucun PnL) ; validés **techniquement**, ils servent les tests.

| Outil | Rôle | Artefact |
|---|---|---|
| **Quoteur v3 (QuoterV2)** | Quote exacte au bloc (calibration technique OK) | `runs/20260623T071136Z_backfill-v3-calibration-technique/` |
| **Triage cross-chain** | **Screening non décisionnel** (liq/vol agrégés, identité par adresse) ; ses sorties **sont** les claims CBBTC / CTM / VELVET | `runs/20260623T090624Z_crosschain-triage/` · git `4e91247` |

## Annexe B — Hypothèses / cadres théoriques *(sans statut économique)*

| Cadre | Nature | Artefact |
|---|---|---|
| **MAV ∝ liquidité × gap²** (R3) | Modèle théorique AMM↔CEX — **borne/intuition, jamais une preuve de trading** | `docs/formulas.md §3` ; `docs/research/` (R3 Gogol 2024) |

---

## 3. Statut global

Aucune claim n'atteint `MÉCANISME_CONFIRMÉ`, `QUOTE_POSITIVE` ni `PAPER_ELIGIBLE`. **0 LEAD.**
**Aucun mécanisme de PnL positif n'est défendable à ce jour** : seul **CEX↔CEX est invalidé** et
**l'atomique Base est rejeté dans son périmètre** ; les **cinq autres tracks restent non conclusifs**.
Prochain mouvement (hors moteur, §13) : **écrire et valider le mémo de mécanisme du track funding**
(`docs/MECHANISM_MAP.md`) avant tout code.
