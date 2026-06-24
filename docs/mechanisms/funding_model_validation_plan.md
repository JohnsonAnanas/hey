# Plan — Phase 2A : validation de modèle (fidélité de reconstruction du funding ETHUSDT)

> **PLAN SEUL. AUCUN endpoint de données, AUCUN code, AUCUNE collecte, AUCUN calcul dans ce document.**
> Ce protocole est **préenregistré** : il fixe AVANT toute exécution les régimes, métriques, tolérances,
> partitions et règles d'arrêt. Il ne s'exécute qu'après **autorisation humaine explicite** et selon une
> phase de collecte **séparément autorisée**.
>
> **Objet :** transformer le verdict `RECONSTRUCTION_CANDIDATE / NON_CONCLUANT`
> (`funding_observability_recon.md`) en un verdict de **fidélité** : le funding **reconstruit ex ante**
> reproduit-il le taux **réglé ex post** (les **1 095** de Phase 1) dans une tolérance préenregistrée,
> **sans look-ahead** ?
>
> **Verdicts de sortie : `NON_CONCLUANT` ; `FIDELITE_MESUREE`** (fidélité **mesurée**, descriptive —
> plafond par défaut) **; et SEULEMENT si** la correspondance OHLC ↔ TWAP interne est **prouvée** (gate
> §2 bis), **`MODELE_VALIDE` / `MODELE_REJETE`.** Tant qu'il n'est pas `MODELE_VALIDE`, la
> reconstructibilité n'est **pas** acquise et **aucune** économie ne suit.

## 0. Portée & interdits (rappel)

- **Validé ici :** uniquement la **fidélité de reconstruction du TAUX** funding (reconstruit vs réglé).
- **Hors scope / INTERDITS :** PnL, annualisation, calibration économique, règle d'entrée, sélection de
  venue, **quotes exécutables**. **Les klines restent des proxys de prix, jamais des quotes exécutables.**
- **Le réglé ex post (Phase 1)** sert de **vérité de référence** ; il n'entre **jamais** dans la
  reconstruction d'un règlement (sinon look-ahead — cf §3).
- **Portée temporelle stricte :** cette fenêtre (`2025-06-23 → 2026-06-23`) sert **UNIQUEMENT** à valider
  la **reconstruction technique** du taux. Ce n'est **pas** une preuve économique et ne le deviendra
  **jamais** : toute future preuve économique exigera un **cycle avec QUOTES** (bid/ask exécutables),
  **idéalement sur une fenêtre FORWARD distincte** (postérieure), afin de ne **jamais** recycler la
  fenêtre de validation technique en backtest économique.

## 1. Hypothèse de fidélité (préenregistrée)

**Mesure (toujours) :** pour chaque règlement *i*, on mesure `e_i = F̂_i − F_i` entre le taux reconstruit
`F̂_i` (depuis les **seules** observations disponibles **avant** *t_i*) et le taux réglé `F_i` (Phase 1) ;
la sortie minimale est la **distribution mesurée** de `e_i` hors échantillon (`FIDELITE_MESUREE`).
**Test de réussite/échec (conditionnel) :** l'hypothèse `H0 : |e_i| ≤ τ` et ses seuils n'existent **que
si** la gate §2 bis est franchie (correspondance prouvée) **et** un budget théorique est réintroduit (§5) ;
sinon **aucun** verdict de réussite/échec n'est rendu.

## 2. Régime/version de formule **par période** (étape 1, documentaire)

Avant toute reconstruction, établir et **figer** le régime applicable, **période par période**, sur
`2025-06-23 → 2026-06-23`. **Chacun des paramètres ci-dessous est un paramètre HISTORIQUE à SOURCER par
régime** (source officielle + date + extrait) — **jamais une hypothèse implicite, jamais un « défaut »
supposé** : un exemple ou une valeur « courante » de doc **ne fait pas foi** tant que son applicabilité
**sur la fenêtre** n'est pas établie. Si une valeur change (ou ne peut être datée) dans la fenêtre,
**segmenter** en sous-périodes homogènes (un régime = une sous-période).

| Paramètre HISTORIQUE (à sourcer par régime) | Valeur de référence à **confirmer/dater** (ne fait pas foi) | Source à dater |
|---|---|---|
| Intervalle de funding + calendrier | 8 h — 00/08/16 UTC | FAQ funding / `fundingInfo` |
| **Échantillonnage de l'indice de prime** | **5 s → 5760 points / intervalle 8 h** | FAQ funding |
| **Pondération TWAP** | **poids croissants 1, 2, …, n** (sur l'intervalle de règlement) | FAQ funding |
| `interest rate` component | 0,01 %/intervalle | FAQ funding / `premiumIndex.interestRate` |
| `clamp` (interest − P) | ±0,05 % | FAQ funding |
| `cap` / `floor` (`adjustedFundingRateCap/Floor`) | ETHUSDT ±0,30 % (Phase 0B) ; **dynamiques** | `fundingInfo` |
| **Version de formule** | `F = [avg P + clamp(interest − P, ±0,05%)] / (8/N)` | FAQ funding |

**Aucune de ces lignes n'est une valeur par défaut implicite :** la colonne du milieu n'est qu'un point de
départ à **vérifier et dater par régime** (`5 s/5760`, pondération TWAP, `interest rate`, caps et version
de formule **inclus**). **Règle d'arrêt §2 :** si, pour une période, un paramètre historique est
**INDÉTERMINÉ** (valeur non documentée/non capturable, ou applicabilité sur la fenêtre non datable — p.ex.
`interest rate`, `cap`, échantillonnage, pondération, intervalle, version) → **`NON_CONCLUANT` pour ce
segment, sans extrapolation** (cf §6).

## 2 bis. Gate de correspondance OHLC ↔ TWAP interne (préalable, documentaire — BLOQUANTE)

> **STATUT (2026-06-24) : `GATE_2BIS_NON_FRANCHIE` (NON_PROUVÉE).** Levée documentaire effectuée
> (`funding_gate2bis_recon.md`) : la correspondance OHLC `premiumIndexKlines` ↔ TWAP interne (5 s/5760)
> **n'est pas démontrée par une source officielle — ni réfutée** (jamais `MODELE_REJETE`). Conséquence :
> Phase 2A **plafonnée à `FIDELITE_MESUREE`**, `MODELE_VALIDE` **inatteignable avec les sources actuelles**.
> **Aucune collecte `premiumIndexKlines` ne sera lancée pour une simple `FIDELITE_MESUREE`.** Réouverture :
> ① source officielle prouvant la correspondance OHLC ↔ échantillonnage TWAP du funding ; **ou** ② accès aux
> observations historiques **5 s** réellement utilisées par Binance.

Avant tout budget théorique ou verdict de réussite/échec, **documenter** (sources officielles, datées) :

1. **Granularité historique disponible** de `premiumIndexKlines` : intervalles offerts, **pas le plus
   fin**, profondeur d'historique réelle sur la fenêtre.
2. **Champ exact utilisé** pour reconstruire le premium (quel élément de la kline — `close` ou autre) et
   sa **définition** documentée.
3. **Correspondance démontrée — ou non —** entre la série OHLC de `premiumIndexKlines` et
   l'**échantillonnage interne** du funding (TWAP 5 s / 5760 points, pondération croissante) : existe-t-il
   une **relation PROUVÉE** (et non supposée) entre l'agrégat kline et la moyenne interne réellement
   appliquée par Binance ?

**Issue de la gate :**
- **Correspondance NON prouvée** (ou granularité/champ indéterminés) → **`NON_CONCLUANT`** sur toute
  fidélité « validée » : **aucun modèle « validé »** ne peut être déclaré ; la Phase 2A est **plafonnée à
  `FIDELITE_MESUREE`** (§5–§6).
- **Correspondance prouvée** → un **budget théorique** (§5) **pourra** être réintroduit, préenregistré
  avant toute comparaison, et un verdict `MODELE_VALIDE` / `MODELE_REJETE` devient atteignable.

## 3. Reconstruction strictement **ex ante** (anti-look-ahead)

- Pour reconstruire `F̂_i` du règlement à *t_i*, n'utiliser **que** des observations d'horodatage
  **strictement antérieur à *t_i*** : klines d'indice de prime **fermées avant *t_i*** couvrant la fenêtre
  d'intervalle `[t_{i−1}, t_i)`. **Aucune** observation d'horodatage `≥ t_i`, **aucun** recours à `F_i`
  lui-même ni à `premiumIndex.lastFundingRate` (live, non historique).
- **Invariant anti-look-ahead (vérifiable) :** l'ensemble des horodatages d'entrée de `F̂_i` est inclus
  dans `[t_{i−1}, t_i)`. À consigner par règlement (borne max < *t_i*).
- Variante optionnelle « affiché » : TWAP glissant `[t_i − 8 h, t_i)` (information réellement visible
  juste avant *t_i*) — **séparée** du réglé, jamais mélangée.

## 4. Séparation **calibration / validation hors échantillon** (partition temporelle EXACTE)

**Partition préenregistrée, bornes UTC exactes, embargo d'un règlement** (figée ici, avant toute
comparaison ; 1 095 règlements = slots 0–1094, pas 8 h) :

| Ensemble | Bornes UTC (inclusives) | Règlements |
|---|---|---|
| **Calibration** (in-sample) | `2025-06-23T00:00:00Z` → `2025-10-22T16:00:00Z` | 366 (slots 0–365) |
| **Embargo** (exclu des deux) | `2025-10-23T00:00:00Z` (slot 366) | 1 |
| **Validation** (hors échantillon) | `2025-10-23T08:00:00Z` → `2026-06-22T16:00:00Z` | 728 (slots 367–1094) |

Total = 366 + 1 + 728 = **1 095**. L'**embargo d'un règlement** (`2025-10-23T00:00:00Z`) garantit qu'aucune
fenêtre TWAP d'un règlement de validation ne chevauche la borne de calibration.

**Pourquoi 366 en calibration :** ce sont les **quatre premiers mois calendaires** (`2025-06-23 →
2025-10-22`), suivis d'un **embargo d'un règlement** (`2025-10-23`), puis de **huit mois de validation**
(`2025-10-23T08:00 → 2026-06-22`) — soit 4 + 8 = 12 mois, calibration en tête, validation hors échantillon
sur le reste.

- **Idéalement zéro paramètre économique libre** (formule entièrement sourcée, §2). La « calibration »
  **ne fixe que des conventions d'implémentation** (bords exacts de la fenêtre TWAP, gestion des klines
  manquantes, arrondis, granularité) — **gelées** à l'issue de la calibration, **jamais** ré-ajustées.
- **Intersection avec les régimes (§2) :** la partition ci-dessus est **globale et exacte** ; si le
  sourcing §2 révèle une frontière de régime, chaque régime est évalué sur son **intersection avec la
  validation**. Un régime **non représenté** dans la fenêtre de validation est **`NON_CONCLUANT`** pour sa
  fidélité (non validable hors échantillon), **jamais** validé par extrapolation.
- **Interdit :** tout re-réglage d'une convention **après** avoir vu la validation (fuite). Une seule passe
  de validation ; tout ajustement ultérieur invalide le run (relancer avec partition redéclarée).

## 5. Métriques & **fidélité mesurée** (budget théorique SUSPENDU)

Métriques **par règlement** (unités de taux ; 1 bp = 0,0001) : erreur signée `e_i = F̂_i − F_i` ; absolue
`|e_i|`. Agrégats **mesurés, descriptifs** (séparément calibration/validation) : `P50/P95/max(|e|)`,
distribution de `e_i`, biais `médiane(e_i)`. Ces quantités sont **mesurées**, sans seuil d'acceptation.

**Budget d'erreur théorique et seuils d'acceptation — RETIRÉS provisoirement.** Toute borne du type
`ε_twap = ( Σ_k w_k·(H_k − L_k)/2 ) / ( Σ_k w_k )` (et les seuils `τ95`, `τmax`, `β` qui en découlent)
**n'est valide que si** la correspondance entre l'OHLC de `premiumIndexKlines` et le **TWAP interne** de
Binance (5 s / 5760, pondération) est **elle-même démontrée** (gate §2 bis). Tant que cette gate n'est pas
franchie, **aucun budget théorique n'est posé et aucun seuil d'acceptation n'est défini** — les utiliser
reviendrait à supposer prouvée la relation OHLC↔TWAP qui reste à établir.

**Conséquence (cf §6) :** sans correspondance prouvée, la Phase 2A ne produit qu'une **fidélité mesurée**
(`FIDELITE_MESUREE`) — la **distribution observée** de `e_i` hors échantillon, **sans** verdict de
réussite/échec — **jamais** `MODELE_VALIDE` ni `MODELE_REJETE`. **Si** la correspondance est démontrée
(gate §2 bis), un budget théorique et ses seuils (`τ95`, `τmax`, `p`, `β`) **pourront être réintroduits**,
préenregistrés **avant** toute comparaison, et alors seulement un verdict de réussite/échec devient
possible.

## 6. Règles d'arrêt & verdicts (préenregistrés)

- **→ `NON_CONCLUANT`** si : un paramètre historique **indéterminé** sur une période (§2) ; primitive
  `premiumIndexKlines` **manquante/gappée** sur un segment (QC de collecte échoue, cf §7) ; granularité,
  champ ou correspondance de la **gate §2 bis indéterminés** ; reconstruction/comparaison infaisable.
- **→ `FIDELITE_MESUREE`** (**plafond par défaut**) si : reconstruction ex ante et comparaison aux 1 095
  réglés **faisables**, mais **correspondance OHLC ↔ TWAP interne NON prouvée** (gate §2 bis non franchie).
  Sortie = **distribution mesurée** de `e_i` hors échantillon, **sans** réussite/échec. **Ni
  `MODELE_VALIDE` ni `MODELE_REJETE`.**
- **→ `MODELE_REJETE` / `MODELE_VALIDE`** : **possibles UNIQUEMENT si** la gate §2 bis est **franchie**
  (correspondance prouvée) **et** un budget/seuils théoriques réintroduits et préenregistrés (§5) — alors
  `MODELE_REJETE` si l'erreur dépasse la tolérance hors échantillon ; `MODELE_VALIDE` si la tolérance tient
  **et** tous les paramètres déterminés (§2) **et** l'invariant anti-look-ahead (§3) **et** la
  reproductibilité (§7) sont respectés.
- Dans **tous** les cas : **aucune** étude économique ne suit sans **nouvelle validation humaine** ;
  `FIDELITE_MESUREE` **n'acquiert pas** la reconstructibilité.

## 7. Données, primitives & gouvernance d'exécution (cartographie — PAS de collecte ici)

- **Vérité de référence :** `fundingRate` Phase 1 (déjà certifié, **1 095**, `runs/…phase1…`).
- **Primitive à acquérir :** `premiumIndexKlines` (P) sur la fenêtre — via une **phase de collecte
  SÉPARÉE et SÉPARÉMENT AUTORISÉE**, à la **même discipline que Phase 1** : runner **versionné avant
  réseau**, requêtes **bornées** (`startTime/endTime`, `limit ≤ 1500`, non chevauchantes), **brut hors
  Git hashé**, **QC** (monotonie, dédup, gaps, intervalles observés, zéro interpolation), manifeste +
  provenance honnête. **Ce plan ne collecte rien.**
- **Paramètres :** `interest rate`, `cap/floor` (`fundingInfo`, Phase 0B ±0,30 %), intervalle (8 h) — figés
  par période (§2).
- **Reproductibilité :** kickoff 2A = manifeste préenregistré (régimes, partition, métriques, tolérances)
  versionné **avant** toute comparaison ; run = manifeste + reçus + hashes + verdict, **discipline
  identique** à Phase 0B/1.
- **Rappel :** klines = **proxys de prix**, **jamais** quotes exécutables ; le `bookTicker` (bid/ask
  exécutable) reste **à vérifier** et **hors** de cette validation de taux.

## 8. Enchaînement & gate

1. (Documentaire) **Gate §2 bis levée le 2026-06-24 → `GATE_2BIS_NON_FRANCHIE`**
   (`funding_gate2bis_recon.md`).
2. **SUSPENDU** : collecte bornée `premiumIndexKlines` — **non lancée** tant que la gate §2 bis n'est pas
   franchie (**pas de collecte pour une simple `FIDELITE_MESUREE`**).
3. (Autorisation séparée, **conditionnée à la réouverture de la gate**) Exécution 2A : reconstruction
   ex ante → comparaison → verdict de fidélité.
4. **Gate :** `MODELE_VALIDE` est un **prérequis** à toute Phase économique (premier cycle).
   `FIDELITE_MESUREE`, `MODELE_REJETE` ou `NON_CONCLUANT` ⇒ la reconstructibilité n'est **pas** acquise ;
   **stop**.

> **Aucune des étapes 1–4 n'est autorisée par ce document.** Il fixe le protocole ; chaque exécution exige
> une autorisation humaine explicite et distincte.
