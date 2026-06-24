# Protocole D0 — DeFi same-chain / MEV boundary map (Base)

> **Pré-enregistrement du protocole de mesure.** Documentaire ; **aucun code, réseau ni collecte**.
> Réf. mécanisme : `defi_samechain_fragmentation_mev_boundary.md`. **Reconnaissance et collecte = étapes
> séparées, sur autorisation explicite et distincte.**

## 0. Paramètres économiques FIGÉS (pré-enregistrés avant données)
- `minimum_research_notional = 1 000 USD`.
- **Grille de tailles** (notional USD de la jambe d'entrée) : **1 000 / 2 500 / 5 000 / 10 000**.
- **Sonde poussière** sous le minimum : **250 USD (FIGÉ)** — sert **uniquement** à distinguer
  `CAPACITY_INSUFFICIENT` (edge sous $1k) de `NO_ATOMIC_EDGE` (aucun edge), puisque la grille démarre à $1k.
- **Persistance : `N = 300 blocs`** consécutifs (≈ 10 min sur Base).
- **Règle capacité** : `upper_bound > 0` **seulement sous $1k ⇒ `CAPACITY_INSUFFICIENT`** ; sinon
  **capacité = courbe complète $1k–$10k**.
- **Chaîne : Base** (infra quoteur/AMM v3 déjà existante).

## 1. Chaîne, pools, contrôle
- **Base.** **Deux pools** same-pair (**éventuellement deux paliers de frais du même protocole**), chacun
  exposant un **quoteur EXACT VALIDÉ** (`amountOut`). À D0, **seul Uniswap v3 (`QuoterV2`, validé) est
  admis** ; **Aerodrome/Slipstream et tout protocole non-Uniswap-v3 sont EXCLUS tant que leur quoteur exact
  n'est pas validé** (étape séparée).
- **Contrôle faux-positifs : WETH/USDC entre les paliers Uniswap v3 0,05 % et 0,30 %**, attendu
  `NO_ATOMIC_EDGE`. **Un major POSITIF n'est PAS un faux positif automatique** : il déclenche un **AUDIT
  RENFORCÉ** (quote/identité/gas/timing/bloc) — il pourrait être un edge réel fugace ; **aucun résultat
  cible n'est produit tant que l'audit n'a pas tranché** (artefact corrigé, ou positif réel documenté). Le
  contrôle est traité **en premier**.
- Adresses exactes pools/tokens : **certifiées à l'étape identité**, pas ici.

## 2. Identité (plancher — avant toute quote)
- Même chaîne (Base) + le token **EST le même ERC-20** sur les deux pools (mêmes **adresses de contrat**
  des deux tokens du couple) + **mêmes decimals** + **standard** (ni rebasing, fee-on-transfer, OFT/hooks,
  synthétique).
- Vérifier que les deux pools tradent **exactement le même couple de contrats** (pas un wrapper/variant).
- Discipline `config/economic_identity.json` (`evidence_hash` requis). **Sans identité certifiée →
  `NON_CONCLUANT`, pas de quote.**

## 3. Données & quotes (exactes, par taille)
- Pour chaque taille `s` (grille ∪ sonde) et chaque **orientation** (achat pool A / vente pool B, **et**
  l'inverse) :
  - jambe d'entrée = **USDC** (≈ USD), montant `s` ;
  - `amountOut_A_exact(s)` puis `amountOut_B_exact(·)` — **quoteur EXACT, frais + impact inclus** ;
  - `upper_bound_atomique(s, orient) = amountOut_B_exact(amountOut_A_exact(s)) − s − gas_normal`.
- **Les deux jambes au MÊME bloc** (cohérence atomique), **horodatées au numéro de bloc** ; req/resp
  **archivés + hashés**.
- **Jamais de mid/screen** ; uniquement `amountOut` exact exécutable.

## 4. Gas (`gas_normal` Base COMPLET, sans priorité)
- Base est un **L2 OP-stack** : `gas_normal = coût_L2_exécution + coût_L1_data/DA` (**les deux**), **sans**
  priorité.
  - `coût_L2_exécution = gas_units(round-trip 2 swaps) × base_fee_L2(bloc)` ;
  - `coût_L1_data/DA = frais de publication des données (data/blob) de la tx sur L1` (composante OP-stack
    `l1Fee`) ;
  - converti en USD via `prix_ETH_USD(bloc)`.
- **Base fee uniquement** — la **priorité MEV est EXCLUE** (inconnue, compétition-dépendante, jamais
  supposée nulle ⇒ `upper_bound` reste une **borne supérieure**).
- **Gate d'enveloppe d'exécution — pré-enregistrée AVANT toute mesure** (tous figés) : **routeur(s)**,
  **ordre des deux swaps**, **type de transaction**, **modèle de calldata**, **source de `gas_units`**,
  **méthode de calcul du coût L1/data**.
- **Tant que cette enveloppe n'est pas définie ET calibrée par un reçu, `gas_normal` est INCONNU ⇒ verdict
  `NON_CONCLUANT`, jamais une borne atomique utilisable.**
- Si une composante (L2 **ou** L1/data/DA) ne peut être obtenue de façon fiable → `NON_CONCLUANT`
  (abstention), **jamais** un gas partiel mis à 0.

## 5. Temps de bloc & échantillonnage
- Base ≈ **2 s/bloc**.
- Fenêtre d'observation : **`N = 300` blocs consécutifs** (≈ 10 min), quotes ré-échantillonnées **par
  bloc** ; chaque point `(taille, orientation)` rattaché à son **numéro de bloc**.

## 6. Persistance descriptive
- Par `(taille, orientation)` sur la fenêtre `N = 300` : **run-length** et **fraction de blocs** où
  `upper_bound > 0`.
- **Descriptif uniquement** (attribut de la carte) — **jamais un levier**, jamais une promesse
  d'exécution. Un `upper_bound` persistant **reste un upper bound** (priorité exclue).

## 7. Verdicts (deux dimensions, seuil $1k figé)
**Dimension A — edge** (sur grille ∪ sonde, meilleure orientation) :
- **`ATOMIC_MEV_SCOPE`** : `upper_bound > 0` à **≥ 1 taille testée** → présumé compétitif, hors périmètre.
  **Sur le contrôle major → ne conclut pas seul : déclenche l'audit renforcé (§1).**
- **`NO_ATOMIC_EDGE`** : `upper_bound ≤ 0` à **toutes** les tailles testées (non-revert).
- **`NON_CONCLUANT`** : identité, quote, **enveloppe d'exécution non calibrée (§4)**, ou **gas Base
  incomplet (L2 ou L1/data/DA manquant)**.

**Dimension B — capacité** (seuil = `minimum_research_notional` = $1k) :
- **capacité documentée** = **courbe complète `upper_bound` sur $1k–$10k**, si `upper_bound > 0` à **≥ 1
  taille ≥ $1k**.
- **`CAPACITY_INSUFFICIENT`** : `upper_bound > 0` **seulement sous $1k** (sonde $250 > 0 mais ≤ 0 à
  **toutes** les tailles ≥ $1k).
- **Reverts de grille conservés** : un revert à `s ∈ $1k–$10k` = **capacité plafonnée sous `s`** (point de
  la courbe), jamais écarté.
- (≤ 0 partout, sans edge sous $1k ⇒ pas de capacité ; l'edge est `NO_ATOMIC_EDGE`.)

## 8. Procédure de sélection de l'univers cible (same-contract / 2 pools actifs)
- **Inclusion** : un token (**contrat unique** sur Base) tradé sur **≥ 2 pools** du même couple
  (**éventuellement deux paliers de frais du même protocole**), chacun avec **quoteur exact VALIDÉ** (à
  D0 : Uniswap v3 uniquement).
- **« Actif » = quoteur non-revert à $250 (liveness à la sonde poussière UNIQUEMENT)** — **sans** utiliser
  liquidité/volume comme critère d'edge (doctrine : la liquidité **n'est pas** un critère décisionnel ;
  seulement « quotable »).
- **Reverts aux tailles de grille ($1k–$10k) CONSERVÉS comme résultat de capacité (§7)**, jamais un motif
  d'exclusion.
- **Exclusions** (re-vérifiées par token) : tokens à mécanique spéciale, wrappers/variants (identité ≠),
  ticker matching, cross-chain/bridge ; **protocoles sans quoteur exact validé** (p.ex. Aerodrome tant que
  non validé).
- **WETH/USDC (paliers v3 0,05 %/0,30 %) traité en premier** ; un major positif → **audit renforcé** (§1),
  pas un rejet automatique.
- C'est une **procédure** (critères) ; la **reconnaissance effective** (lister les pools) est une étape
  **séparée, non autorisée ici**.

## 9. Gouvernance / sorties
- Pré-enregistrement (ce doc) **versionné AVANT** toute reconnaissance/collecte ; l'**enveloppe d'exécution
  (§4)** doit être **définie + calibrée par un reçu** avant toute borne atomique.
- Sorties d'un run ultérieur (si autorisé) : **manifeste + reçus** (req/resp quotes, blocs, gas L2+L1)
  **archivés + hashés**, **courbe `taille → upper_bound`**, persistance, **verdicts A & B**. Discipline
  manifeste identique aux phases funding.
- **Interdits à D0** : aucun code/scanner/réseau/collecte ; aucun bot d'exécution/MEV ; aucun chemin
  capital.
