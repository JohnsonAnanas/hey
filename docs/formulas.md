# Formules AMM — cœur du simulateur

> Toutes ces formules servent à calculer un **profit net extractible**, jamais un simple
> écart de prix. Le simulateur les implémente, mais **toute** opportunité candidate doit
> être re-vérifiée par **simulation exacte** (ou quoter on-chain) avant exécution.

## 0. Décomposition du profit net (la cible)

```
profit_net(Δx) = montant_récupéré(Δx)        # sortie réelle des swaps
               - Δx                           # mise de départ
               - gas
               - flash_loan_fee (éventuel)
               - [risque_MEV / exécution]     # probabiliste, pas un coût fixe
```

> **Anti double-comptage.** Le *slippage* et le *price impact* sont **déjà** contenus dans
> `montant_récupéré(Δx)` (la formule AMM les capture par construction). Les coûts à
> **ajouter** après la simulation AMM sont : **gas**, **flash-loan fee**, et le **risque
> MEV/exécution** (probabilité de revert / d'être doublé — pas un coût déterministe).

## 1. Swap unique v2 — `getAmountOut`

`γ = 1 − fee` (ex. fee 0,30 % → γ = 0,997).

```
amountOut = (amountIn · γ · reserveOut) / (reserveIn + amountIn · γ)
```

## 2. Cycle 2 pools v2 ↔ v2

`X → Y` sur Pool A, puis `Y → X` sur Pool B.
Réserves : A = (a = réserveX, b = réserveY), B = (c = réserveX, d = réserveY).
Frais : `γ1 = 1 − feeA`, `γ2 = 1 − feeB`. Mise de départ : `Δx` (en token X).

```
xOut(Δx) = (b · c · γ1 · γ2 · Δx) / ( a·d + γ1·Δx·(d + b·γ2) )

profit(Δx) = xOut(Δx) − Δx
```

**Taille optimale** (✅ vérifiée par dérivation, voir encadré) :

```
Δx* = ( √(a·b·c·d·γ1·γ2) − a·d ) / ( γ1·(d + b·γ2) )
```

**Condition d'existence d'un arbitrage :**

```
opportunité  ⟺  (b·c·γ1·γ2) / (a·d) > 1     (⟺ √(a·b·c·d·γ1·γ2) > a·d ⟺ Δx* > 0)
```

**Règle de décision :**

```
Δx* ≤ 0            → pas d'arbitrage
profit_net(Δx*) ≤ 0 → pas d'arbitrage
sinon              → opportunité candidate (re-simuler exactement avant exécution)
```

> **Dérivation.** Pose `K = b·c·γ1·γ2`, `P = a·d`, `Q = γ1·(d + b·γ2)`, donc
> `xOut = K·Δx/(P + Q·Δx)`. Alors `d(profit)/dΔx = K·P/(P+Q·Δx)² − 1 = 0`
> ⟹ `(P + Q·Δx)² = K·P` ⟹ `Δx* = (√(K·P) − P)/Q`, et `√(K·P) = √(a·b·c·d·γ1·γ2)`. ∎

> ⚠️ **Domaine de validité.** v2 **constant-product uniquement**. Pour v3 (liquidité
> concentrée), Curve (stableswap), Aerodrome **stable** (`x³y+xy³=k`) → la forme fermée ne
> s'applique pas : simulation numérique ou **quoter on-chain** (`QuoterV2`, etc.).

## 3. MAV vs prix de référence (R3) — AMM ↔ CEX, constant product

`Pa` = prix AMM, `Pc` = prix de référence (CEX), `y` = réserve (profondeur).

```
Taille optimale :  Vmax = y · (Pa − Pc) / (2·Pa)        (R3, éq. 9)
MAV            :  MAV  = y · (Pa − Pc)² / (4·Pa)        (R3, éq. 10)
```

**Lecture structurelle (le cœur du projet) :** `MAV ∝ liquidité (y) × (écart de prix)²` —
**linéaire** en liquidité, **quadratique** en écart. ⟹ un petit écart sur un pool profond
peut dominer un gros écart sur un pool fin. (Définitions exactes des variables : R3 §3.)

Empirique R3 : USDC-ETH SyncSwap (zkSync Era) vs Binance, juil.→sept. 2023, MAV total
**104,96 K$ = 0,24 % du volume** ; ils mesurent le **decay time** des écarts (= notre
**persistance**) et l'impact des frais / block slippage / gas.

## 4. Du 2-pools au réseau de pools (R2)

Router optimalement un ordre sur **N CFMMs** = problème d'**optimisation convexe** (tractable)
sans coûts fixes ; **MIP convexe** avec coûts fixes. **La détection d'arbitrage en est un cas
particulier** (trouver un arb, ou *certifier* qu'il n'en existe pas). ⟹ au-delà de 2 pools,
formuler comme une **optimisation convexe** (ex. `cvxpy`), pas une énumération ad-hoc de
cycles. À garder pour la phase multi-hop / multi-pool.
