# Manifeste de run — backfill-v3-fenetre-longue

- **Verdict** : **REJETE**
- **Créé (UTC)** : 2026-06-23T09:14:35Z
- **Version de code (git)** : `7fed31ca433336c5c7653065b6ca57ad3742411f`

## Hypothèse
Existe-t-il une route LENTE, NETTE, observable dans l'univers Base ÉLIGIBLE (ancre indépendante, ~WETH/USDC), sur cette fenêtre, à cadence horaire ? (Verdict SCOPÉ, jamais global.)

## Commande / paramètres
`python backfill_v3.py --days 14 --cadence-min 60 --start-block 47101032 --end-block 47705832 --l1-usd 0.02 --gas-margin-frac 0.5 --margin 5.0 --cap-min 200.0 --allow-forward`

## Période
blocs 47101032..47705832 (pas 1800, 337 demandés)

## Univers étudié
5 certifiés ; UniV3 {500,3000} ; v3↔v3 & v3↔v2 ; grille [1000.0, 5000.0, 25000.0, 100000.0, 250000.0] ; éligibles=['USDC/AERO', 'USDC/cbBTC', 'WETH/AERO', 'WETH/USDC', 'WETH/cbBTC']

## Coûts supposés
gas_estime_conservateur SÉPARÉ : exec (gasEstimate quoteur/forfait × baseFee) + L1-data $0.02 + marge 50% ; ancre USD indépendante au bloc

## Sources
- archive RPC Base : https://base-mainnet.g.alchemy.com/v2/***
- QuoterV2 Uniswap v3 (quote exacte au bloc) + état v2 on-chain

## Données d'entrée (hashées — la brute est hors Git, l'empreinte fait foi)
- `config\universe_base.json` — sha256 `bb317b1eb0f1423c…` (1342 o)
- `data\logs\backfill_v3_20260623_095012.csv` — sha256 `db951ffca1f11638…` (2101870 o)

## Résultat
ÉLIGIBLE 42161 routes ; PnL>0 [MEV_RACE 0, COURT 0, A_OBS 0, FWD 0] ; abst.sans-ancre 17435 ; reverts 11086 ; sha256(sortie)=db951ffca1f11638

## Notes
Verdict SCOPÉ à l'univers ÉLIGIBLE (ancre indépendante) ; cbETH/cbBTC/AERO NON testés. Borne SUPÉRIEURE (réserves+simulation, ni intra-bloc ni MEV). Détails structurés -> m['details'] (périmètre, abstentions, reverts ventilés, routes par paire/type, params gelés). JAMAIS 'pas d'alpha DeFi'.
