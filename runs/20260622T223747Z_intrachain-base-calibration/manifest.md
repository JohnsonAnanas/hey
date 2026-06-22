# Manifeste de run — intrachain-base-calibration

- **Verdict** : **NON_CONCLUANT**
- **Créé (UTC)** : 2026-06-22T22:37:47Z
- **Version de code (git)** : `9fdc34e06840c91ad6af698ec0cb66f49e462bbb`

## Hypothèse
Le moteur de route intra-chaine surface-t-il des dislocations v2-v2 net-positives et persistantes sur Base (univers de calibration) ?

## Commande / paramètres
`python scan_dex_intrachain.py --seconds 40 --min-usd 50000 --gas-units 300000`

## Période
blocs 47689240..47689260 (live 2026-06-23)

## Univers étudié
5 tokens certifies (config v1) ; 9 paires routables

## Coûts supposés
frais pool on-chain ; gas 300000 u @ block ; taille optimale entiere ; marge statut $5

## Sources
- Base RPC public (sim/chain RPC garde, same-block Multicall3)
- factories UniV2/Sushi/BaseSwap/Aerodrome + v3 UniV3/Panc

## Données d'entrée (hashées — la brute est hors Git, l'empreinte fait foi)
- `config\universe_base.json` — sha256 `bb317b1eb0f1423c…` (1342 o)

## Résultat
9 blocs ; routes 639 ; A_OBSERVER 0 ; FORWARD 0 ; rejets v3=630

## Notes
CALIBRATION du moteur. Resultat vide/court = couverture & liquidite v2 sur Base (v3 ABSTENU faute de quoter, fenetre courte), PAS une absence d'alpha DeFi. v3 = grosse part de la liquidite Base -> a instrumenter (quoter) avant toute conclusion.
