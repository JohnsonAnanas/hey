# D2B2_ABORTED_PERFORMANCE

**Arrêt VOLONTAIRE de performance** de la 1re série D2B-2 (runner v1 `@938b6a5`), tout au début (lot 0 en
cours). **Ce n'est PAS un résultat économique.**

- Lot 0 interrompu **avant écriture** : le runner v1 n'écrit raw + manifeste qu'à la **fin** d'un lot →
  le dossier `20260624T202859Z_d2b2-measure-lot00/` est **vide** (aucun cycle persisté, aucun raw).
- Aucun autre lot produit. Progression série : `DEMARRAGE` + `lot 00 START` uniquement.

**Classement** : ces artefacts (vides) sont **JAMAIS interprétés** et **JAMAIS mélangés** à une future
série. La nouvelle série D2B2-v2 écrira dans un **namespace distinct** (`*_d2b2v2-measure-lotNN`,
`data/raw/defi/d2b2v2/`) pour éviter toute confusion. La sémantique reste identique ; seul le transport RPC
change (cf `docs/mechanisms/defi_d2b2v2_transport.md`).
