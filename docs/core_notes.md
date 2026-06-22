# Bot d'arbitrage DeFi crypto — notes centrales

> **Phrase directrice (principe central du projet).**
> Le bot ne cherche pas des écarts de prix. Il cherche des **profits nets extractibles**,
> calculés avec la **liquidité réelle**, la **taille optimale du trade**, les frais, le gas
> et le risque d'exécution.

## 1. Vision

Cible unique : `profit_net_réel > 0`, soit

```
prix_vente_réel
 - prix_achat_réel
 - slippage
 - price_impact
 - frais_DEX
 - gas
 - flash_loan_fee (éventuel)
 - risque_MEV / exécution
> 0
```

La bonne question n'est **pas** « le token est-il moins cher sur un protocole que sur un
autre ? » mais :

> **« Quelle quantité puis-je réellement arbitrer sans détruire l'écart, et est-ce encore
> rentable après tous les coûts ? »**

## 2. Principe clé : liquidité ≠ prix affiché

Sur un AMM constant-product (`x·y = k`), le prix dépend des **réserves** du pool. Un gros
trade relatif à la profondeur du pool cause un fort *price impact*. Donc :

- écart de prix élevé + **faible** liquidité → souvent **petit** profit exploitable ;
- écart de prix faible + **grosse** liquidité → parfois **gros** profit exploitable.

> **Confirmé empiriquement (2026-06-22, registre `arb/data/logs/`).** Sur Base WETH/USDC, les
> deux pools **profonds** (Uniswap-v3 5 bps vs Pancake-v3 5 bps) étaient collés à **0,06 bps**.
> Le « gap » de 14,7 bps venait **uniquement** des pools fins au mid *stale*, non exécutables
> à la taille. La borne de non-arbitrage (R1) fait que les écarts qui **persistent** restent
> **< frais**. ⟹ il faut mesurer le **MAV net**, pas le prix mid.

## 3. MAV — le concept central

`MAV = Maximal Arbitrage Value` = profit max théorique extractible en tenant compte du prix,
de la **liquidité** et de la **taille optimale** du trade.

```
spread affiché   → seulement un signal
MAV brut         → potentiel réel avant coûts
MAV net          → opportunité réellement exploitable
```

**opportunité valide = MAV net > 0** (jamais « prix A < prix B »).

Loi structurelle (R3) : **MAV ∝ liquidité × (écart de prix)²** — linéaire en liquidité,
**quadratique** en écart. Formules exactes dans [`formulas.md`](formulas.md).

## 4. Pipeline logique (état annoté)

| # | Étape | État |
| --- | --- | --- |
| 1 | Scanner pools (réserves, fees, tokens, block) | **fait** (`scan_dex_gaps.py`, Multicall3) |
| 2 | Détecter écarts bruts (même paire / multi-hop) | **fait** (mid) → à passer en MAV |
| 3 | Calculer le trade optimal (Δx\*) | **à faire** (prochain) |
| 4 | Simuler l'exécution complète (amountOut, frais, gas, flash-loan, slippage, profit net) | **à faire** |
| 5 | Filtrer (profit net > seuil, liquidité, route, tokens sûrs) | **à faire** |
| 6 | Exécuter atomiquement (tout-ou-revert, `minProfit`) | **plus tard** (Solidity) |
| 7 | Logger / analyser (détecté, rejeté + raison, simulé vs réel) | **fait** (CSV) → enrichir |

## 5. Règle d'or d'exécution

Le smart contract ne fait **jamais** confiance au bot off-chain. Il vérifie lui-même :

```solidity
require(finalBalance >= initialBalance + minProfit, "NOT_PROFITABLE");
// avec flash loan :
require(finalBalance >= borrowedAmount + premium + minProfit, "NOT_PROFITABLE");
```

Si le marché bouge entre détection et exécution, si quelqu'un passe avant nous, si le profit
disparaît → **revert**. (Atomic : tout passe ou tout est annulé.)

## 6. MVP v1 — périmètre volontairement étroit

- **une seule chain** ;
- **deux DEX v2-like** (constant-product) ;
- paires **très liquides** ;
- **pas** de flash loan au début ;
- **simulation locale obligatoire** ;
- exécution **seulement** si profit net clair.

Contextes possibles : Polygon (QuickSwap / SushiSwap), BSC (PancakeSwap v2 + forks v2),
Base/Arbitrum (DEX v2-like disponibles).

> ⚠️ **Caveat math.** La formule fermée Δx\* (cf `formulas.md` §2) est valable pour les pools
> **v2 constant-product UNIQUEMENT**. Les pools qu'on a sondés sur Base étaient en **v3**
> (liquidité concentrée) → pour le MVP il faut **cibler explicitement des pools v2**
> (Uniswap-v2 / Sushi sur la chaîne choisie, ou Aerodrome **volatile** sur Base qui est bien
> du `x·y=k`). v3 / Curve / Aerodrome-stable = math différente → simulation numérique.

## 7. Ce qu'on NE fait PAS au début

Cross-chain · Uniswap v3 complet · Curve complet · flash loans complexes · mempool sniping ·
routes à 5-6 hops · toutes les chains en même temps.

> Note : ceci **redirige** la piste « cross-chain » évoquée avant la fiche. On suit le brief :
> **MVP mono-chaîne v2↔v2 d'abord**, le reste ensuite, chacun validé au même standard.

## 8. Stack — décision en attente

Le brief propose **TypeScript** (`.ts`) + **Solidity** (`.sol`). Réalité actuelle :
l'observatoire est en **Python** (`web3.py`). L'executor sera **Solidity** dans tous les cas.
À trancher : langage du **cerveau off-chain** (scanner / simulateur / detector).
Recommandation : **Python pour la recherche/simulation** (momentum + écosystème data),
**Solidity pour l'executor**. Voir échange avec l'utilisateur.

## 9. Structure (proposée par le brief, variante TS)

```
arbitrage-bot/
  docs/{core_notes.md, formulas.md, research/{R1,R2,R3}}
  src/scanner/poolScanner   simulator/{getAmountOut, simulateRoute, optimalTradeSize}
      detector/opportunityDetector   execution/executor   config/{chains,dexes,tokens}
  contracts/ArbitrageExecutor.sol
  tests/{simulator.test, forkExecution.test}
```

Réalité actuelle (Python) : `arb/scan_dex_gaps.py` (scanner+detector mid) + `arb/docs/`.
Le mapping TS↔Python est 1:1 si on reste en Python.

## 10. Glossaire

- **AMM** : Automated Market Maker — prix calculé par une formule.
- **CFMM** : Constant Function Market Maker — famille d'AMM conservant un invariant.
- **Constant product** : `x·y=k` (Uniswap v2-like).
- **Liquidity pool** : réserve de tokens permettant les swaps.
- **Slippage** : écart entre prix attendu et prix obtenu.
- **Price impact** : effet de **ton propre** trade sur le prix du pool.
- **Spread** : écart de prix entre deux marchés.
- **MAV** : Maximal Arbitrage Value — profit max extractible compte tenu de la liquidité.
- **Atomic arbitrage** : arbitrage en une seule transaction (revert si une étape échoue).
- **Flash loan** : emprunt remboursé dans la même transaction.
- **MEV** : Maximal Extractable Value — valeur extraite via l'ordre/inclusion/copie des tx.

## Références

R1 / R2 / R3 → [`research/README.md`](research/README.md).
