# STATE — état honnête du projet `arb/` (audit, 2026-06-23)

> Photo de vérité, sans modifier la logique économique. À relire avant tout nouveau calcul.
> **PnL net réellement positif mesuré à ce jour : AUCUN.**

## 1. Hypothèses REJETÉES (mesurées, négatives net de coûts — scopées, jamais « pas d'alpha DeFi » en général)

| Hypothèse | Mesure | Source |
|---|---|---|
| « Le CEX↔CEX a un profit extractible » | Artefact d'**identité par ticker** : HYPE profitable dans les 2 sens, 3352/3363 lignes ≥ $1M. | `runs/…cex-cex-20m-rejection` (REJETE) ; `data/logs/QUARANTINE.md` |
| « DEX↔CEX majors (ETH/BTC) capturable par un solo, net de frais » | ETH : 263 obs, net médian **−11,9 bps**, 2 % actionnable. BTC/ETH backtest : net plancher ~0. | `data/historical/settle_dex_cex.csv`, `data/logs/backtest_gap.csv` |
| « Arbitrage atomique LENT, net, observable sur l'univers Base ÉLIGIBLE (paires ancrées WETH/USDC) » | Fenêtre 14 j v3 : **42 161 routes éligibles, 0 net-positive** (quotes v3 exactes, borne sup.). Backfill v2 7 j corrobore (0 net, 98 % sans dislocation brute). | `runs/…backfill-v3-fenetre-longue` (REJETE scopé) ; `runs/…backfill-intrachain` |
| « CBBTC a un vrai gap cross-chain » | Live **7 bps** (base↔eth, même adresse, profond). Le « 154 bps » du triage = **artefact de médiane** de la fenêtre obs. | `verify_crosschain.py` (live) vs `runs/…crosschain-triage` |

## 2. Hypothèses seulement NON CONCLUES (pas mesurées rigoureusement)

| Hypothèse | Pourquoi non conclue | Inconnue pivot |
|---|---|---|
| « Inventaire cross-chain (récolte de mean-reversion) net-positif sur un token bridgeable » | **Jamais mesuré.** VELVET base↔bsc montre un basis **mean-reverting** (std 71 bps, demi-vie ~3h) mais identité **non prouvée** (adresses ≠) + coût de bridge **non mesuré**. | **coût de bridge vs amplitude** |
| « CTM 322 bps est récoltable » | Gap **réel** (même adresse, 2 côtés profonds+actifs), mais **persistant** → quasi sûrement = **prime de friction de bridge** (le gap ≈ le coût). Coût de bridge non mesuré → penche REJETÉ. | coût de bridge (≈ 322 bps ?) |
| « DEX↔CEX VIRTUAL capturable par un solo » | Edge au mid (+40 bps), nul au plancher (−4 bps), fenêtres **2 min** (course MEV). Pas le jeu lent d'un solo → penche REJETÉ. | exécution réelle |
| « Le funding carry est une stratégie nette défendable » | ~4 %/an (1 an quotidien) — **modeste**, jamais testé net de liquidation/plateforme/retournement. C'est un **benchmark**, pas une stratégie testée. | drawdown / risque plateforme |

## 3. PnL net réellement positif mesuré

**AUCUN.** Aucun test, sur aucun univers, n'a produit un PnL net positif défendable (net de frais + gas + impact, et a fortiori net de coût de bridge/inventaire). Les résultats sont soit REJETÉS, soit NON CONCLUS.

## 4. Fiabilité des données

| Niveau | Données | Note |
|---|---|---|
| **FIABLE** (exact au bloc, archive, manifesté, reproductible) | `data/logs/backfill_intrachain_*.csv`, `data/logs/backfill_v3_*.csv` (+ `runs/…`), `data/historical/settle_*.csv` | vérité on-chain ; verdicts scopés |
| **FIABLE (avec réserve)** | `data/logs/funding_regime.csv` (1 an quotidien) | plafond suspect ~10,9 % à vérifier |
| **QUARANTAINE** (invalide, conservée pour re-test) | `data/logs/cex_monitor.csv` ($20M fantômes), `data/collected/crosschain_cand.csv` (ancien schéma, identité-aveugle) | voir les `QUARANTINE.md` |
| **INDICATIF SEULEMENT** (agrégé / court / mid-price) | `data/collected/crosschain_obs.csv` (GeckoTerminal agrégé, ~heures), `data/logs/dex_cex_*.csv`, `scan_*`, `mav_*` | **leçon CBBTC : la médiane obs trompe → exiger la confirmation live/exécutable** |

## 5. L'UNIQUE prochain calcul économique utile

**Un seul test, réduit à la formule de PnL ci-dessous** : un actif, **deux venues**, **quotes exactes à $1k / $5k / $10k**, une période → verdict (REJETÉ / NON_CONCLUANT / VALIDÉ). Rien de plus.
- Candidat en tête (à **choisir ensemble**) : **VELVET base↔bsc** (le seul basis mean-reverting), une fois l'identité certifiée et le coût de bridge intégré. Probable issue : « gap ≈ coût de bridge → non récoltable » — mais on **saura** au lieu d'assumer.

## 6. Formule de PnL — UNIQUE et canonique

> Tout futur test économique se résume EXACTEMENT à ceci, sur **une taille, un actif, deux venues, une période** :

```
PnL net =
    vente exécutable
  − achat exécutable
  − frais
  − gas
  − coût de rebalancing amorti (si applicable)
```

- **vente / achat exécutable** = `amountOut` réel par taille (quote on-chain ou math AMM exacte), **jamais un mid**.
- **frais** = frais de pool/venue (embarqués dans la quote v3 ; explicites en v2).
- **gas** = `gas_estime_conservateur` (exec + L1-data + marge), jamais « exact » sans executor.
- **coût de rebalancing amorti** = bridge + capital immobilisé, **uniquement** pour le jeu d'inventaire cross-chain (0 pour l'atomique mono-chaîne).
- Verdict scopé à l'actif + la fenêtre. **Borne supérieure** (ne voit ni intra-bloc ni MEV). Jamais une conclusion globale.
