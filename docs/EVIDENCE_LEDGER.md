# EVIDENCE LEDGER — registre de preuve faisant foi (MISSION RESET §0/§2)

> Registre **unique et vérifiable** de toutes les claims du laboratoire. Il **remplace** la lecture
> par statut narratif : chaque affirmation a un **statut tranché**, un **niveau de preuve (0→6)**, un
> **artefact source**, un **périmètre** et une **prochaine mesure**. `docs/STATE.md` reste la photo
> historique (immuable) ; **ce fichier fait foi** pour le statut courant.
>
> **PnL net positif défendable à ce jour : AUCUN.** Plusieurs faux positifs ont été correctement
> rejetés — c'est l'actif réel du projet.

## Taxonomie de statut (seuls statuts autorisés — §0)
`INVALIDÉ` · `REJETÉ` (souvent `REJETÉ_SCOPÉ` / `REJETÉ_PRÉLIMINAIRE`) · `NON_CONCLUANT` · `LEAD`
(et variantes documentées) · `MÉCANISME_CONFIRMÉ` · `QUOTE_POSITIVE` · `PAPER_ELIGIBLE`.
**`VALIDÉ` est interdit** pour un triage, une médiane, une quote isolée ou une observation de marché.

## Niveaux de preuve (§8)
`0` prix affiché · `1` quote exécutable isolée · `2` quote-pair net positif à taille définie ·
`3` série historique de quote-pairs · `4` test hors échantillon préenregistré · `5` shadow ledger /
paper inventory · `6` pilote à capital limité (autorisation explicite). Aucun passage de niveau sans
artefacts **et** décision humaine.

---

## 1. Registre

| Claim | Statut | Preuve | Artefact source | hash / commit | Périmètre | Limite | Prochaine mesure |
|---|---|---|---|---|---|---|---|
| Le CEX↔CEX a un profit extractible (~$20M) | **INVALIDÉ** | 1 (falsifié) | `runs/…cex-cex-20m-rejection/` ; `data/logs/QUARANTINE.md` | `manifest.json` (git_hash du run) | CEX↔CEX par carnet, univers `/USDT` vol24h≥1M | Artefact d'**identité par ticker** (HYPE profitable 2 sens) | Aucune — invalidé (garde codée : `sim/identity.py`) |
| DEX↔CEX majors (ETH/BTC) capturable par un solo, net | **REJETÉ_SCOPÉ** | 3 | `data/historical/settle_dex_cex.csv` ; `data/logs/backtest_gap.csv` | cf manifests `runs/…` | ETH/BTC, solo lent, fenêtre 7 j | Net médian −11,9 bps ; 2 % actionnable | Aucune sur ce périmètre ; ne pas généraliser hors ETH/BTC |
| Arbitrage atomique lent net sur Base éligible (paires ancrées WETH/USDC) | **REJETÉ_SCOPÉ** | 3 | `runs/…backfill-v3-fenetre-longue/` ; `runs/…backfill-intrachain…/` | `manifest.json` (inputs sha256) | Base, paires ancrées, tailles [1k…250k], 14 j v3 / 7 j v2 | 42 161 routes éligibles, **0 net-positive** (borne sup.) | Aucune sur ce périmètre ; contrôle, pas priorité |
| CBBTC a un vrai gap cross-chain (154 bps) | **REJETÉ_SCOPÉ** | 1 (live) | `verify_crosschain.py` (live) ; `runs/…crosschain-triage/` | cf manifest triage | base↔eth, même adresse, profond | Live **7 bps** ; « 154 bps » = artefact de **médiane** du triage | Documenter la redemption/wrap officielle avant tout inventory |
| CTM 322/498 bps cross-chain récoltable | **LEAD_NON_RENOUVELABLE_POSSIBLE** (identité/rebalancing inconnus) | 0→1 | `runs/…crosschain-triage/` ; on-chain `oftVersion()`/`endpoint()` | cf manifest triage | bsc↔eth, même adresse `0xc8fb…88888888` | Même adresse ≠ identité économique ; **absence d'OFT ≠ absence de tout bridge** | Chercher un bridge/redemption tiers réel ; sinon rester lead |
| Inventaire cross-chain net-positif — meilleur candidat **VELVET** base↔bsc | **REJETÉ_PRÉLIMINAIRE** | 1 (non archivé) | `docs/STATE.md §1` (test LI.FI $1k) ; `data/historical/settle_crosschain_velvet.csv` | **reçu LI.FI NON archivé** (pas de hash) | base↔bsc, $1k, 2026-06-23 | Aller-retour −160 bps **mais reçu (réponse LI.FI, route, tailles, coûts) non hashé/archivé** | **Archiver le reçu LI.FI** (manifest + hash) → fige en `REJETÉ_SCOPÉ` ; sans cela, préliminaire |
| Funding carry = stratégie nette défendable | **NON_CONCLUANT** | 0→1 | `data/logs/funding_regime.csv` (1 an quotidien) | cf README data | funding annualisé, benchmark | ~4 %/an, **jamais** testé net de liquidation/plateforme/contrepartie | Mécanisme de convergence écrit + carry net de risque (track C) |
| Le moteur de quote v3 (QuoterV2) fonctionne (calibration technique) | **NON_CONCLUANT** (méthode OK, économie non conclue) | — | `runs/…backfill-v3-calibration-technique/` (était `VALIDE`) | `manifest.json` | calibration technique, 2 j | `VALIDÉ` interdit ici (pas un résultat **économique**) | — (outil validé ; sert les tests économiques) |
| Triage cross-chain (depth/identité par adresse) | **LEAD** | 0 | `runs/…crosschain-triage/` (était `VALIDE`) | `manifest.json` | screen liq/vol, identité par adresse | `VALIDÉ` interdit pour un **triage** ; sort 2 shortlist + watchlist | Promouvoir une piste vers `MÉCANISME_CONFIRMÉ` (identité + route) |
| MAV ∝ liquidité × gap² (cadre théorique R3) | **NON_CONCLUANT** (cadre, pas une stratégie) | — | `docs/formulas.md §3` ; `docs/research/` (R3 Gogol 2024) | — | modèle AMM↔CEX | Un modèle n'est pas un PnL ; oriente, ne conclut pas | Ne sert que de borne/intuition, jamais de preuve de trading |

> **Reclassements explicites vs `STATE.md`** : CEX↔CEX `REJECTED`→**INVALIDÉ** ; VELVET `REJECTED`→
> **REJETÉ_PRÉLIMINAIRE** (reçu non archivé) ; CTM « non-bridgeable »→**LEAD_NON_RENOUVELABLE_POSSIBLE**
> (OFT absent ≠ pas de bridge) ; les deux manifests `VALIDE` (triage, calibration)→**LEAD** /
> **NON_CONCLUANT** (la doctrine interdit `VALIDÉ` pour triage/technique). Décisions consignées dans
> `docs/DECISIONS.md`.

---

## 2. Audit des reçus (reproductibilité)

Un résultat n'est recevable que s'il a un **reçu reproductible** (CSV manifesté + hash, ou run avec
`inputs[].sha256`). État :

| Claim | Reçu archivé & hashé ? | Conséquence |
|---|---|---|
| CEX↔CEX $20M | ✅ run + QUARANTINE | INVALIDÉ tenable |
| Atomique Base v3/v2 | ✅ runs + inputs sha256 | REJETÉ_SCOPÉ tenable |
| DEX↔CEX majors | ✅ CSV `settle_dex_cex` / `backtest_gap` | REJETÉ_SCOPÉ tenable |
| CBBTC live 7 bps | ⚠️ live `verify_crosschain.py`, **pas** de manifest figé | REJETÉ_SCOPÉ mais **à figer** (rejouer + manifester) |
| **VELVET −160 bps** | ❌ **réponse LI.FI brute non archivée/hashée** | **REJETÉ_PRÉLIMINAIRE** — tête de liste à corriger |
| CTM non-bridgeable | ⚠️ on-chain reverts, pas de manifest dédié | rétrogradé en **LEAD** (rejet final non justifié) |

**Trou prioritaire :** le test VELVET LI.FI ($1k, −160 bps) est la conclusion la plus citée et n'a
**aucun reçu hashé**. Tant qu'il n'est pas archivé (requête + réponse LI.FI, route, tailles, coûts,
timestamp, hash) via un manifest, il reste **préliminaire** — pas un rejet final.

---

## 3. Statut global

Aucune claim n'atteint `MÉCANISME_CONFIRMÉ`, `QUOTE_POSITIVE` ni `PAPER_ELIGIBLE`. Le **mécanisme
économique** des résultats négatifs est constant : **mesuré au net exécutable, le gap affiché est une
prime de risque, jamais un profit**. Le prochain mouvement est une **décision de track** (cf
`docs/MECHANISM_MAP.md`, orientation **funding / cash-and-carry**), à valider après ce mémo.
