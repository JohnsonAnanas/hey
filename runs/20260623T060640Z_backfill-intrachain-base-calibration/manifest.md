# Manifeste de run — backfill-intrachain-base-calibration

- **Verdict** : **NON_CONCLUANT**
- **Créé (UTC)** : 2026-06-23T06:06:40Z
- **Version de code (git)** : `31e52142539093e8acda154be535accfe6e08c0c`

## Hypothèse
Sur Base v2 certifie, le moteur observe-t-il des PnL nets POSITIFS, sur routes certifiees, a taille utile, et assez de blocs pour justifier un test FORWARD ? (PAS 'on aurait gagne'.)

## Commande / paramètres
`python backfill_intrachain.py --days 7 --cadence-min 60 --start-block 47400317 --end-block 47702717 --min-usd 50000 --gas-units 300000`

## Période
blocs 47400317..47702717 (pas 1800, 169 demandes)

## Univers étudié
5 tokens certifies v2 ; 9 paires routables ; 30 pools v2

## Coûts supposés
frais pool au bloc ; gas 300000u x baseFee(bloc) ; ancre USD(bloc) ; taille optimale ENTIERE EVM ; marge statut $5

## Sources
- archive RPC Base : https://base-mainnet.g.alchemy.com/v2/***
- etat on-chain au bloc (getReserves/getFee + baseFee du bloc)

## Données d'entrée (hashées — la brute est hors Git, l'empreinte fait foi)
- `config\universe_base.json` — sha256 `bb317b1eb0f1423c…` (1342 o)
- `data\logs\backfill_intrachain_20260623_080620.csv` — sha256 `deccf5c69e0a82d8…` (31557 o)

## Résultat
169 demandes / 169 lus / 0 abstentions ; lectures illisibles 0.0% ; routes v2 169 ; A_OBSERVER 0 ; FORWARD 0 ; v3 non quotees 151 ; sha256(sortie)=deccf5c69e0a82d8

## Notes
Backfill de RESERVES : reconstruit le prix/PnL exact au bloc, mais NE VOIT NI les transactions concurrentes intra-bloc NI le positionnement MEV reel. Ne prouve donc PAS qu'on aurait gagne ; borne SUPERIEURE optimiste. Un FORWARD reste requis pour conclure.
