# Manifeste de run — cex-cex-20m-rejection

- **Verdict** : **REJETE**
- **Créé (UTC)** : 2026-06-22T21:35:49Z
- **Version de code (git)** : `84fa6419f316464477a98d5fb5bae47253a0e47f`

## Hypothèse
Les ~20M USD 'extractibles' CEX<->CEX (cex_monitor.csv) sont-ils un vrai profit capturable ?

## Commande / paramètres
`audit d'identité a posteriori sur data/logs/cex_monitor.csv (run cex_monitor.py historique, pré-garde)`

## Période
2026-06-15..2026-06-22

## Univers étudié
91 coins /USDT, vol24h>=1M sur >=2 venues, transferts OUVERTS

## Coûts supposés
taker 10bps x2 (frais trading seuls ; pas de transfert/inventaire/latence)

## Sources
- ccxt fetch_order_book binance/okx/htx (paires /USDT)

## Données d'entrée (hashées — la brute est hors Git, l'empreinte fait foi)
- `data/logs/cex_monitor.csv` — sha256 `1083814fbefd18b0…` (164667 o)

## Résultat
Artefact d'identité par ticker : HYPE profitable dans les 2 sens (20.62M et 20.60M USD) a 0.3-5.6 bps ; 3352/3363 lignes >= 1M USD ; 22 coins vus 2-sens. Falsifie par directional_inconsistency + implausible_magnitude.

## Notes
Motive le fix sim/identity.py + la quarantaine data/logs/QUARANTINE.md. Le net_bps (tickers) restait sain ; c'est extract_usd (walk de carnet sur identite fausse) qui explosait.
