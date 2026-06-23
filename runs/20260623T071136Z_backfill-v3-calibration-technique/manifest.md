# Manifeste de run — backfill-v3-calibration-technique

- **Verdict** : **VALIDE**
- **Créé (UTC)** : 2026-06-23T07:11:36Z
- **Version de code (git)** : `3ac5e605474fde7a71973e42f176290adf608027`

## Hypothèse
CALIBRATION TECHNIQUE : le quoteur v3 historique, la couverture, le coût (gas séparé), la courbe de taille et la qualité des abstentions fonctionnent-ils ? (PAS de conclusion éco.)

## Commande / paramètres
`python backfill_v3.py --days 2 --cadence-min 60 --start-block 47617884 --end-block 47704284 --l1-usd 0.02 --gas-margin-frac 0.5`

## Période
blocs 47617884..47704284 (pas 1800, 49 demandés)

## Univers étudié
5 tokens certifiés ; UniV3 {500,3000} ; routes v3↔v3 & v3↔v2 ; grille [1000.0, 5000.0, 25000.0, 100000.0, 250000.0]

## Coûts supposés
gas_estime_conservateur SÉPARÉ : exec (gasEstimate quoteur/forfait × baseFee) + L1-data $0.02 + marge 50% ; ancre USD indépendante au bloc

## Sources
- archive RPC Base : https://base-mainnet.g.alchemy.com/v2/***
- QuoterV2 Uniswap v3 (quote exacte au bloc) + état v2 on-chain

## Données d'entrée (hashées — la brute est hors Git, l'empreinte fait foi)
- `config\universe_base.json` — sha256 `bb317b1eb0f1423c…` (1342 o)
- `data\logs\backfill_v3_20260623_085836.csv` — sha256 `7dfcbbfe8316eb6b…` (315675 o)

## Résultat
49/49 blocs ; routes v3 7399 ; quotes ok 8379 revert 1748 ; PnL>0 [MEV_RACE 0, COURT 0, A_OBSERVER 0] ; sha256(sortie)=7dfcbbfe8316eb6b

## Notes
CALIBRATION TECHNIQUE (#1) : aucun CANDIDAT_FORWARD produit ici ; toute conclusion éco exige une fenêtre PRÉFIXÉE 7–14 j. Borne SUPÉRIEURE (quote = réserves+simulation, ne voit ni intra-bloc ni MEV). Un résultat vide sur cet univers de calibration n'est JAMAIS 'pas d'alpha DeFi'.
