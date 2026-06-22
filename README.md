# arb — observatoire d'arbitrage crypto (sous-projet)

Sous-projet **isolé** de Mercor (venv propre, dépendances propres). Rupture assumée avec
l'ADN Mercor : ici on est en **live / exécution / microstructure**, pas en backtest
no-lookahead. La discipline transférée reste la même : **brut ≠ net**, *quel risque suis-je
payé pour absorber*, et on **mesure avant de croire**.

## État : phase 0 — OBSERVATOIRE (lecture seule, zéro capital, zéro clé privée)

Avant tout bot qui exécute, on mesure la surface d'opportunité. `scan_dex_gaps.py` lit
le prix mid de **WETH/USDC** sur plusieurs DEX d'une même chaîne (**Base**) et logue :

- le **gap brut** entre venues (bps) ;
- le **gap net des frais de pool** (condition *nécessaire*, pré-slippage / pré-gas) ;
- surtout la **persistance** du gap (combien de temps il survit) — le chiffre qui tranche
  entre « capturable par un solo » et « déjà mangé par les bots MEV » (mort en 1 bloc).

Aucune transaction, aucune clé privée, aucun capital engagé. RPC public en lecture seule.

## Usage
```bash
.venv/Scripts/python.exe scan_dex_gaps.py --seconds 90 --interval 2.5
```

## Ce que ça ne fait PAS (encore)
- Pas de slippage-pour-taille (prix mid seulement ; le quoter on-chain viendra après).
- Pas de proxy de concurrence MEV fin (mempool/bundles) — la persistance sert de proxy v1.
- Pas d'exécution. C'est un capteur.
