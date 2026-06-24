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
> **Verdict de sortie attendu : `MODELE_VALIDE` / `MODELE_REJETE` / `NON_CONCLUANT`.** Tant qu'il n'est pas
> `MODELE_VALIDE`, la reconstructibilité n'est **pas** acquise et **aucune** économie ne suit.

## 0. Portée & interdits (rappel)

- **Validé ici :** uniquement la **fidélité de reconstruction du TAUX** funding (reconstruit vs réglé).
- **Hors scope / INTERDITS :** PnL, annualisation, calibration économique, règle d'entrée, sélection de
  venue, **quotes exécutables**. **Les klines restent des proxys de prix, jamais des quotes exécutables.**
- **Le réglé ex post (Phase 1)** sert de **vérité de référence** ; il n'entre **jamais** dans la
  reconstruction d'un règlement (sinon look-ahead — cf §3).

## 1. Hypothèse de fidélité (préenregistrée)

**H0 (à réfuter) :** pour chaque règlement *i* de la fenêtre figée, le taux reconstruit `F̂_i` (depuis les
seules observations disponibles **avant** *t_i*) et le taux réglé `F_i` (Phase 1) vérifient
`|F̂_i − F_i| ≤ τ`, où `τ` et les agrégats d'acceptation sont fixés au §5 **avant** toute comparaison.
Réussite = H0 tenue **hors échantillon** ; échec = H0 violée au-delà de la tolérance.

## 2. Régime/version de formule **par période** (étape 1, documentaire)

Avant toute reconstruction, établir et **figer** le régime de formule applicable, **période par période**,
sur `2025-06-23 → 2026-06-23`. Chaque paramètre = **source officielle + date + extrait**. Si un paramètre
change dans la fenêtre, **segmenter** en sous-périodes homogènes (un régime = une sous-période).

| Paramètre à figer par période | Exemple/défaut documenté | Source |
|---|---|---|
| Intervalle de funding (et calendrier) | 8 h — 00/08/16 UTC | FAQ funding / `fundingInfo` |
| Méthode TWAP de l'indice de prime | 5 s, 5760 points, poids croissants ; fenêtre d'intervalle (réglé) | FAQ funding |
| `interest rate` component | 0,01 %/intervalle (défaut) | FAQ funding / `premiumIndex.interestRate` |
| `clamp` (interest − P) | ±0,05 % | FAQ funding |
| `cap` / `floor` (`adjustedFundingRateCap/Floor`) | ETHUSDT ±0,30 % (Phase 0B) ; **dynamiques** | `fundingInfo` |
| Formule (version) | `F = [avg P + clamp(interest − P, ±0,05%)] / (8/N)` | FAQ funding |

**Règle d'arrêt §2 :** si, pour une période, un paramètre historique est **INDÉTERMINÉ** (p.ex. `interest
rate` ou `cap` non documenté/non capturable pour ce segment, ou changement d'intervalle non datable) →
**`NON_CONCLUANT` pour ce segment, sans extrapolation** (cf §6).

## 3. Reconstruction strictement **ex ante** (anti-look-ahead)

- Pour reconstruire `F̂_i` du règlement à *t_i*, n'utiliser **que** des observations d'horodatage
  **strictement antérieur à *t_i*** : klines d'indice de prime **fermées avant *t_i*** couvrant la fenêtre
  d'intervalle `[t_{i−1}, t_i)`. **Aucune** observation d'horodatage `≥ t_i`, **aucun** recours à `F_i`
  lui-même ni à `premiumIndex.lastFundingRate` (live, non historique).
- **Invariant anti-look-ahead (vérifiable) :** l'ensemble des horodatages d'entrée de `F̂_i` est inclus
  dans `[t_{i−1}, t_i)`. À consigner par règlement (borne max < *t_i*).
- Variante optionnelle « affiché » : TWAP glissant `[t_i − 8 h, t_i)` (information réellement visible
  juste avant *t_i*) — **séparée** du réglé, jamais mélangée.

## 4. Séparation **calibration / validation hors échantillon**

- Partitionner les **1 095** règlements **par régime homogène** (§2), puis, **dans chaque régime**,
  réserver un sous-ensemble de **validation hors échantillon** jamais utilisé pour fixer un choix
  d'implémentation.
- **Idéalement zéro paramètre économique libre** (formule entièrement documentée). La « calibration » ne
  fixe que des **conventions d'implémentation** (bords exacts de la fenêtre TWAP, gestion des klines
  manquantes, arrondis, granularité retenue) — **figées sur la calibration**, **gelées**, puis évaluées
  sur la validation.
- **Partition préenregistrée** (avant toute comparaison) : calibration = **≈ 30 %** chronologiques en tête
  de chaque régime ; validation = **≈ 70 %** restants. **Embargo** d'un intervalle entre les deux pour
  éviter tout chevauchement de fenêtre TWAP au raccord.
- **Interdit :** tout re-réglage d'une convention **après** avoir vu la validation (fuite). Une seule passe
  de validation ; tout ajustement ultérieur invalide le run (relancer avec partition redéclarée).

## 5. Métriques & **tolérance d'acceptation préenregistrées**

Métriques **par règlement** (en unités de taux ; 1 bp = 0,0001) :
- erreur signée `e_i = F̂_i − F_i` ; erreur absolue `|e_i|`.

Agrégats (séparément **calibration** et **validation**) :
- `P50(|e|)`, `P95(|e|)`, `max(|e|)` ;
- `couverture = fraction(|e_i| ≤ τ_unit)` ;
- **biais** `|médiane(e_i)|` (détecte une erreur systématique de fenêtre/interest).

**Tolérance d'acceptation** (structure figée ici ; **valeurs numériques gelées au lancement 2A**, dans le
manifeste de kickoff, **dérivées d'un budget d'erreur a priori** = quantification du taux + borne
d'approximation TWAP 1 m vs 5 s + arrondi `interest`/`clamp`, **jamais** assouplies après coup) :
- `P95(|e|) ≤ τ95` **et** `max(|e|) ≤ τmax` **et** `couverture ≥ p` **et** `|médiane(e)| ≤ β`,
- **évalués sur la VALIDATION hors échantillon** (la calibration ne sert qu'à geler les conventions).
- Candidats indicatifs à justifier/figer au kickoff (non contraignants ici) : `τ95` et `τmax` de l'ordre
  de la quantification du taux + la borne TWAP ; `p ≥ 0,95` ; `β` proche de 0. **Si un seuil ne peut être
  justifié a priori par le budget d'erreur → c'est une raison d'arrêt (§6), pas un seuil « au doigt ».**

## 6. Règles d'arrêt (préenregistrées)

- **→ `NON_CONCLUANT`** si : un paramètre historique **indéterminé** sur une période (§2) ; primitive
  `premiumIndexKlines` **manquante/gappée** sur un segment (QC de collecte échoue, cf §7) ; ambiguïté de
  fenêtre/pondération TWAP **non levée documentairement** ; tolérance non justifiable a priori (§5).
- **→ `MODELE_REJETE`** si : l'erreur **dépasse la tolérance** sur la **validation hors échantillon**.
- **→ `MODELE_VALIDE`** seulement si : **tous** les paramètres déterminés (§2) **et** tolérance tenue sur
  la validation (§5) **et** invariant anti-look-ahead respecté (§3) **et** run reproductible (§7).
- Dans **tous** les cas : **aucune** étude économique ne suit sans **nouvelle validation humaine**.

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

1. (Documentaire) Lever les gates §8 du dossier 1.5 nécessaires (interest/cap par période, granularité P).
2. (Autorisation séparée) Collecte bornée `premiumIndexKlines` — discipline Phase 1.
3. (Autorisation séparée) Exécution 2A : reconstruction ex ante → comparaison → verdict de fidélité.
4. **Gate :** `MODELE_VALIDE` est un **prérequis** à toute Phase économique (premier cycle). `MODELE_REJETE`
   ou `NON_CONCLUANT` ⇒ la reconstructibilité n'est pas acquise ; **stop**.

> **Aucune des étapes 1–4 n'est autorisée par ce document.** Il fixe le protocole ; chaque exécution exige
> une autorisation humaine explicite et distincte.
