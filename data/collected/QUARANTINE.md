# QUARANTAINE — candidats cross-chain INVALIDES (identité non prouvée)

> Marqueur loud (charte d'intégrité : *échouer fort / abstention loggée + motif*). La donnée brute
> est **conservée** (append-only, re-testable), mais les **candidats** ci-dessous sont **INVALIDES**
> en l'état. Date : **2026-06-22**. Fix : [`../../sim/identity.py`](../../sim/identity.py).

## `crosschain_cand.csv` — INVALIDE (identité par TICKER, adresse jetée)

**Bug de classe identique au CEX↔CEX** : `collector.py` regroupait par symbole et **jetait l'adresse**
du contrat (présente dans `crosschain_obs.csv`, absente du candidat). Deux tokens partageant un ticker
(CTM, VELVET, DMT…) étaient appariés sans preuve que c'est le **même projet bridgé**. Le garde-fou
`gap < 2500 bps` est un espoir, pas une identité.

**Remplacé par** : `collector.py` **porte** désormais `lo_addr`, `hi_addr` et un verdict `identity`
(`VERIFIED` / `UNVERIFIED` / `COLLISION_SUSPECT`) via `sim.identity.crosschain_identity`. Schéma changé
→ l'appender bascule sur `crosschain_cand.v2.csv` (l'ancien fichier reste figé, ici quarantiné). Seuls
les `VERIFIED` (même contrat cross-EVM, ou même projet canonique tabulé) sont de vrais candidats.

- Exemple `VERIFIED` (prouvé par la donnée) : **CTM** = même contrat `0xc8fb…88888888` sur bsc ET eth.
- Exemple `UNVERIFIED` (non prouvable sans table de bridge) : **VELVET** base `0xbf92…` vs bsc `0x8b19…`.

## `../historical/settle_crosschain_velvet.csv` — identité UNVERIFIED

Série historique d'UN pair (VELVET base↔bsc), adresses **différentes** → identité non prouvée tant que
le registre canonique (`sim.identity.CANONICAL`) n'est pas rempli depuis la doc de bridge **officielle**
VELVET. Ne pas conclure un PnL cross-chain dessus avant certification de l'identité + du coût de
rééquilibrage/inventaire (cf audit).
