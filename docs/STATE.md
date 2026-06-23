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
| « CTM 322 bps cross-chain récoltable » | **NON-BRIDGEABLE** : même code déterministe (même adresse bsc/eth) mais **aucune fonction OFT** → déploiements séparés, marchés **segmentés**, gap **non arbitrable** (on ne peut pas déplacer le token). | on-chain : `oftVersion()`/`endpoint()` revert sur bsc ET eth |
| « Inventaire cross-chain (mean-reversion) net-positif — meilleur candidat VELVET base↔bsc » | **Test exact $1k (LI.FI, 2026-06-23)** : acheter bsc / vendre base = **−$16 (−160 bps)** aller-retour. Frais agrégateur ~50 bps + écart exécutable réel ≫ le gap **mid** de 29 bps. Le bridge ne coûtait que 3 bps (**pas** le tueur) — c'est l'**exécution**. Le basis mean-reverting (std 71 bps) est réel comme série de prix mais **intradeable**. | quotes **LI.FI exactes** (identité VELVET officielle confirmée) |
| « DEX↔CEX VIRTUAL capturable par un solo » | Edge au mid (+40 bps), nul au plancher (−4 bps), fenêtres **2 min** (course MEV). Pas le jeu lent d'un solo. | `data/logs/backtest_gap.csv` |

## 2. Hypothèses seulement NON CONCLUES (pas mesurées rigoureusement)

| Hypothèse | Pourquoi non conclue | Inconnue pivot |
|---|---|---|
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

Le test cross-chain (VELVET, le meilleur candidat) est **FAIT → rejeté à $1k exécutable** (LI.FI, −160 bps). Avec l'**atomique-majors** ET l'**inventaire cross-chain** rejetés au net exécutable, **il n'y a plus de prochain test « deux venues / quote $1k » évident sur l'univers actuel.** Le pattern *est* le résultat : partout, mesuré au **net exécutable**, c'est négatif — le gap affiché est la **prime de risque**, jamais un profit.

La suite est une **décision stratégique, à prendre ensemble** (pas un calcul évident) :
- **(a)** Tester le **funding carry** net de risque (liquidation/plateforme) — la dernière thèse non conclue, mais modeste (~4 %/an) et c'est un *benchmark*, pas un arb.
- **(b)** Acter que l'arb/inventaire DeFi accessible pour un solo patient est une **prime de risque non récoltable**, et **changer de jeu** (ex. être le **LP / market-maker** — encaisser les frais au lieu de les payer).
- **(c)** Élargir à la **longue traîne** (gelé) — gros gaps mais gros coûts d'exécution/risque ; même pattern attendu.

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
