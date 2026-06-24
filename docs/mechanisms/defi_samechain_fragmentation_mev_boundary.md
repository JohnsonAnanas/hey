# Mécanisme / Décision — DeFi same-chain fragmentation / MEV boundary map (même contrat, 2 pools)

> **Track économique unique ACTIF** (funding **gelé**, `GATE_2BIS_NON_FRANCHIE`). Documentaire ; **aucun
> code, scanner, réseau ni collecte**. Objet : **cartographier la frontière MEV** de la fragmentation
> same-chain — **pas** trouver un edge tradable pour nous.

## 1. Mécanisme (hypothèse explicite — un mécanisme, pas un token)
Même **chaîne**, même **actif** (même **contrat**, identité certifiée), coté sur **deux pools/protocoles**.
Écart de prix A↔B. La **seule** capture mesurable ici est **atomique** (aller-retour en un bloc), bornée sur
quotes **exactes** :

`upper_bound_atomique = amountOut_B_exact(amountOut_A_exact(input)) − input − gas_normal`

Les **frais et l'impact sont déjà inclus dans les quotes** ; la **priorité MEV est inconnue,
compétition-dépendante et jamais supposée nulle** — elle **n'est pas soustraite**, donc
`upper_bound_atomique` est une **borne supérieure, pas un PnL garanti**. Sur **même chaîne, deux pools ne
sont PAS deux inventaires séparés** : c'est le **même actif**. « Une jambe maintenant + une jambe plus
tard » est un **pari de relative value / mean-reversion** de l'écart inter-pool (avec risque de prix entre
les deux), **pas un arbitrage** — **hors scope de ce track**, et **aucune jambe différée n'évite le coût
des deux legs**.

## 2. Périmètre
- **Inclus** : même chaîne, même contrat, 2 pools/protocoles, ERC-20 standard transférable trivialement.
- **Exclus (verbatim)** : cross-chain, bridge, **ticker matching** (identité par nom), **tokens à mécanique
  spéciale** (rebasing, fee-on-transfer, OFT/hooks, synthétiques), **tout bot d'exécution / searcher MEV**,
  et **toute jambe différée / relative-value / mean-reversion** (≠ arbitrage).
- **Contrôle (pas cible)** : majors déjà classés — atomique Base **REJETÉ_SCOPÉ**, DEX↔CEX majors
  **NON_CONCLUANT**. Le triage doit **y retrouver l'absence d'edge accessible** ; un edge détecté sur un
  major = **détecteur de faux positif** (méthode à corriger).

## 3. Identité certifiée (plancher — avant toute quote)
Même chaîne + **même adresse de contrat** + mêmes decimals + **transférabilité exécutable** entre les deux
pools (le token EST le même ERC-20 ; pas de wrapper/synthétique). Identité = **mapping économique**, jamais
ticker (discipline `config/economic_identity.json`). **Sans identité certifiée → `NON_CONCLUANT`, pas de
triage.**

## 4. Frontière atomique (MEV) — ce que la fragmentation same-chain ouvre, ou non
Sur **même chaîne**, la seule capture sans inventaire ni pari directionnel est l'aller-retour **atomique**
(1 bloc, 2 jambes), bornée par
`upper_bound_atomique = amountOut_B_exact(amountOut_A_exact(input)) − input − gas_normal`
(frais+impact **dans** les quotes ; **priorité MEV non soustraite** car inconnue, compétition-dépendante,
jamais supposée nulle → **borne supérieure**).

- `upper_bound_atomique` **> 0** à une taille testée → **PRÉSUMÉ COMPÉTITIF** : la priorité MEV étant
  **inconnue, compétition-dépendante et jamais supposée nulle**, **une borne positive reste un upper bound,
  pas un PnL garanti** ; l'edge se dispute dans l'enchère de priorité → **INCOMPATIBLE AVEC NOTRE PÉRIMÈTRE
  NON-MEV** → `ATOMIC_MEV_SCOPE`.
- `upper_bound_atomique` **≤ 0** à **toutes** les tailles testées → pas d'edge atomique même en ignorant la
  priorité → `NO_ATOMIC_EDGE`.
- Un écart non atomiquement profitable n'ouvre **aucun** chemin pour nous : le monétiser supposerait une
  **jambe différée** = pari **relative value / mean-reversion** (risque de prix), **pas un arbitrage** →
  **hors scope**.
- **Garde anti-artefact** : `amountOut_*_exact` proviennent de **quotes exécutables horodatées** (jamais
  mid/screen) ; un edge sur mid est présumé **artefact** (quote périmée, identité fausse). *(Leçon
  CBBTC/CTM/VELVET : screen agrégé ≠ exécutable.)*

## 5. Mesures requises (toutes sur quotes **exactes** par taille, jamais mid)
Pour chaque `input` d'une grille de tailles : `amountOut_A_exact(input)` puis `amountOut_B_exact(·)`
(quoteur exact ; **frais + impact inclus**), `gas_normal` au bloc, puis `upper_bound_atomique`. Sortie
principale : la **courbe `taille → upper_bound_atomique`** ; **persistance** descriptive (nb de blocs de
survie d'une borne > 0 — attribut de la carte, pas un levier). **Capacité = dimension séparée** (cf §6) :
classée **seulement** si un `minimum_research_notional` est **préenregistré avant les données** ; sinon →
publier la **seule courbe**.

## 6. Verdicts — deux dimensions séparées

**Dimension A — edge atomique :**
- **`ATOMIC_MEV_SCOPE`** : rendu **dès qu'une `upper_bound_atomique > 0` est observée à une taille testée**
  → **présumé compétitif** (priorité MEV **inconnue, compétition-dépendante, jamais supposée nulle** ⇒
  **une borne positive reste un upper bound, pas un PnL garanti**) ; **hors périmètre** (non-MEV).
- **`NO_ATOMIC_EDGE`** : `upper_bound_atomique ≤ 0` à **toutes** les tailles testées.
- **`NON_CONCLUANT`** : identité, quote ou coût manquant.

**Dimension B — capacité (séparée) :**
- **`CAPACITY_NON_CLASSIFIEE`** : tant que `minimum_research_notional` **n'est pas préenregistré** →
  publier **seulement la courbe `taille → upper_bound_atomique`**, sans classement.
- une fois `minimum_research_notional` **préenregistré (avant les données)** : **`CAPACITY_INSUFFICIENT`**
  si `upper_bound_atomique > 0` **seulement en-dessous** du seuil ; sinon **capacité documentée** (plage de
  tailles ≥ seuil où `upper_bound_atomique > 0`).

## 7. Preuve / discipline
Niveau 0 screen = **interdit décisionnel**. Ordre : **identité certifiée** → **quotes exécutables
archivées+hashées** (req/resp, timestamp, tailles, gas) → **courbe `taille → upper_bound_atomique`**
(+ persistance descriptive) → **classification de frontière** (capacité classée seulement si
`minimum_research_notional` préenregistré). Ce track **ne mène à aucun chemin capital** : un
`ATOMIC_MEV_SCOPE` est **hors périmètre**, pas un feu vert.

## 8. Interdits de phase (rappel)
**Aucun code, scanner, réseau ni collecte** maintenant. Aucun bot d'exécution/MEV. Aucun
cross-chain/bridge/ticker/token spécial. **Aucune jambe différée / relative value / mean-reversion.**
**Un seul track actif.** Mesurer avant de croire ; **brut ≠ net**.
