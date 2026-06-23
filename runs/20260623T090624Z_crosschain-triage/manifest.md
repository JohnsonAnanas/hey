# Manifeste de run — crosschain-triage

- **Verdict** : **VALIDE**
- **Créé (UTC)** : 2026-06-23T09:06:24Z
- **Version de code (git)** : `4e91247a473793dcb32768ee81ba8c952918fc22`

## Hypothèse
Quels tokens à IDENTITÉ PROUVÉE (même adresse) ont une vraie profondeur des DEUX côtés (liq + vol24h>0) ET un basis ≥ seuil — donc un candidat NON-mirage pour l'œil-inventaire ?

## Commande / paramètres
`python crosschain_triage.py --min-liq 100000 --min-vol 1000 --min-gap-bps 30`

## Période
fenêtre actuelle du collecteur (crosschain_obs.csv)

## Univers étudié
327 tokens vus ; 3 à identité prouvée (≥2 chaînes)

## Coûts supposés
aucun (crible liq/vol ; pas de quote exécutable — c'est la Phase 2)

## Sources
- data/collected/crosschain_obs.csv (GeckoTerminal, prix/liq/vol agrégés)

## Données d'entrée (hashées — la brute est hors Git, l'empreinte fait foi)
- `data\collected\crosschain_obs.csv` — sha256 `c44ce204ebb59e79…` (1381371 o)

## Résultat
shortlist PROFOND 2 ; mirages écartés 0 ; watchlist registre 16

## Notes
Crible GROSSIER anti-mirage (liq/vol agrégés), pas un verdict éco. Identité PAR ADRESSE. Un basis qui survit ici doit ENCORE passer la profondeur exécutable on-chain (Phase 2). Les candidats à identité non prouvée (adresses ≠) exigent un registre de bridge officiel.
