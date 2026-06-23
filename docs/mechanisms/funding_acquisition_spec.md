# Spécification d'acquisition — Série funding **certifiée** (track C)

> **Statut : pré-collecte (`NON_CONCLUANT`). Document présenté pour validation humaine AVANT toute
> collecte.** Aucun code, réseau ni collecte lancés. Compagnon de `funding_data_contract.md` (schéma
> §2a, procédure §4) et `funding_cash_and_carry.md`.
>
> Cette spec définit **comment acquérir** une série funding brute, certifiée et reproductible. **Elle ne
> fixe AUCUN seuil d'entrée ni rendement attendu.** Elle **interdit explicitement `best_carry =
> max(exchange)` et tout choix de venue a posteriori** (look-ahead). La venue (ou une règle de sélection
> multi-venue) se fixe **avant la fenêtre de test**, sur **données observables avant le règlement**.

## 1. Objet

Acquérir une **donnée brute par marché/venue**, immuable et hashée, dont l'agrégat sera
**reconstructible** (doctrine §6). Cette spec **n'établit rien** (ni seuil, ni rendement) ; elle décrit
l'acquisition. La conception d'une règle d'entrée vient **après**, sur calibration (contrat §4).

## 2. Venues, marchés & univers FIXE (préenregistré)

- **Liste de venues explicite et figée** : chaque venue nommée, avec son **mécanisme de funding
  documenté** (intervalle, convention de signe, formule, plafond éventuel). Une venue dont le mécanisme
  n'est pas documentable est **exclue** (pas certifiable).
- **Marchés** : pour chaque venue, les **`perp_market_id` exacts** (instrument), le **type** (USDT-margin
  linéaire vs coin-margined inverse), la **devise de marge/règlement**, le **multiplicateur/unité**.
- **Univers FIXE** : l'ensemble des couples **(venue, marché)** est **déclaré une fois, gelé avant
  collecte**. Aucun ajout/retrait en cours de collecte. **Critères de sélection d'univers ORTHOGONAUX
  au funding** (cotation + disponibilité + liquidité à une **date de référence préenregistrée**) —
  **jamais** une sélection par le funding observé (ce serait sélectionner sur le résultat).
- **Collecte de plusieurs venues AUTORISÉE** ; chaque `(venue, marché)` est **suivi, stocké ET analysé
  INDÉPENDAMMENT**. **Aucune règle de sélection, fusion ou bascule multi-venue** dans ce mécanisme
  (« meilleure venue du jour » exclue). **Une stratégie multi-venue serait un mécanisme FUTUR SÉPARÉ**
  (cf §11).

## 3. Source primaire

- **Source = l'endpoint de funding propre à la venue** (le funding qu'elle **règle réellement**), **pas**
  un agrégateur tiers. Endpoint/méthode documentés (texte, pas de code ici).
- On archive le **primaire** : funding **tel que réglé**, **instant de fixation** et **de règlement**, et
  le **mark/index** auquel il s'applique. Tout dérivé (annualisation, agrégat) est **calculé depuis ce
  primaire**, jamais saisi.

## 4. Champs bruts — une observation = (venue × marché × settlement)

Reprend le schéma brut du contrat (`funding_data_contract.md §2a`), complété pour l'acquisition :

| Champ | Définition | Obligatoire |
|---|---|---|
| `venue` · `perp_market_id` | Venue + instrument exact | ✅ |
| `asset` | Sous-jacent, **mapping économique canonique** (doit matcher la jambe spot) | ✅ |
| `margin_settlement_ccy` · `contract_multiplier_unit` | Devise de règlement + multiplicateur/unité | ✅ |
| `funding_rate` | Taux **tel que réglé** par la venue (brut, non annualisé) | ✅ |
| `funding_formula_cap` | Formule de funding de la venue + **plafond/cap** documenté | ✅ |
| `sign_convention` | Qui paie qui — **fait de venue** | ✅ |
| `mark_index_basis` | Mark/index servant au funding **à la fixation** | ✅ |
| `settlement_interval` | Intervalle natif + calendrier | ✅ |
| `fixing_time_utc` · `settlement_time_utc` | Instant de **fixation** et de **règlement** | ✅ |
| `source` · `endpoint` | Provenance primaire (venue) | ✅ |
| `raw_request` · `raw_response` | Réponse brute archivée verbatim | ✅ |
| `request_hash` · `response_hash` | Empreintes (sha256) | ✅ |
| `collection_time_utc` | Horodatage de la collecte (≠ settlement) | ✅ |
| `completeness_flag` | Présent / gap / abstention + **motif** | ✅ |

## 5. Cadence / settlements

- Collecte à la **cadence native de settlement de chaque marché** (8 h, 1 h… — **fait de venue, capté
  par marché**, jamais supposé). **Chaque settlement** est capté (**pas d'échantillonnage**).
- **Backfill** : paginer l'historique de funding de la venue jusqu'à couvrir la durée préenregistrée
  (§6), **dédup par `(venue, marché, settlement_time)`**.
- **Continu** : capter chaque settlement à mesure (append, §7).

## 6. Durée — objectif de couverture + fenêtre à figer

- **`≥ 1 an` est un OBJECTIF de couverture** (couvrir plusieurs régimes de funding), **PAS** une fenêtre
  préenregistrée.
- La fenêtre **exacte** (`start_utc`, `end_utc`) doit être **remplie et validée** dans l'**Annexe A.2** —
  **GATE : aucun appel réseau tant qu'elle n'est pas remplie et validée**.
- **Aucune extension après avoir vu les données** (la séparation calibration / règle figée / test se
  fait plus tard, contrat §4).

## 7. Stockage append-only

- **Brut immuable, append-only** (doctrine §5) : un enregistrement par `(venue, marché, settlement)` ;
  **jamais réécrit**.
- **Réponses brutes archivées verbatim** (la brute fait foi par son hash). Disposition indicative :
  `data/raw/funding/<venue>/<perp_market_id>/…` (réponses) **+** table normalisée append-only dérivée.
- La table normalisée doit être **reconstructible** depuis le brut hashé (doctrine §6).

## 8. Hashes & manifeste

- **Chaque réponse brute hashée** (`request_hash` / `response_hash`, sha256).
- **Manifeste de run** (`manifest.py` / `docs/run_manifest_standard.md`) qui épingle : **version de code
  (git)**, **univers + venues + durée préenregistrés**, **inputs bruts avec sha256**, paramètres,
  verdict de collecte. **La série n'est CERTIFIÉE qu'une fois manifestée + hashée + QC passés (§9).**

## 9. Contrôles qualité (QC) — à passer pour certification

- **Complétude** : chaque settlement attendu présent ; **gaps explicités** (jamais comblés en silence).
- **Horodatages** monotones ; **dédup** par `(venue, marché, settlement_time)`.
- **Convention de signe vérifiée par venue** (recoupement doc venue / un règlement connu).
- **Plafond** : tout `funding_rate` au-delà du **cap documenté de la venue** est **signalé** (détecte/explique un plafond type ~10,9 %).
- **Unités** : recoupement `funding réglé` ≈ `taux × notionnel × multiplicateur` sur un échantillon.
- **Cadence** cohérente avec la spec de la venue.
- **Anti-look-ahead** : chaque enregistrement n'utilise que des données **observables à/avant son
  règlement**.

## 10. Critères d'abstention (jamais un faux 0, jamais un fallback)

- QC en échec pour une `(venue, marché, settlement)` ⇒ **observation ABSTENUE** (non comblée), **motif
  loggé**.
- Endpoint d'une venue indisponible/incomplet ⇒ **abstention pour cette venue** — **on ne substitue
  PAS** une autre venue (pas de sélection a posteriori).
- Convention de signe non vérifiable pour une venue ⇒ **venue non certifiée** (abstention).
- Brut non hashable / non manifestable ⇒ **non certifié**.
- **Abstention ≠ négatif** : c'est « pas de donnée », loggé.

## 11. Interdictions explicites

- **`best_carry = max(exchange)` est INTERDIT** : jamais de max sur exchanges (enveloppe haute a
  posteriori = diagnostic rétrospectif, pas un PnL exécutable). Chaque `(venue, marché)` reste
  **indépendant**.
- **Collecte multi-venue autorisée, mais AUCUNE règle de sélection ni bascule multi-venue dans ce
  mécanisme.** Chaque `(venue, marché)` est **analysé INDÉPENDAMMENT** ; aucune sélection de venue a
  posteriori, aucune combinaison/bascule entre venues. **Une stratégie multi-venue serait un mécanisme
  FUTUR SÉPARÉ** (hors-scope ici).
- **Univers FIXE** : pas de cherry-picking de marchés/venues en cours de route, ni de sélection par le
  funding observé.
- **Aucun seuil d'entrée, aucun rendement attendu** n'est fixé ici (la règle d'entrée se conçoit plus
  tard sur calibration, contrat §4).

## 12. Statut & suite

**Pré-collecte (`NON_CONCLUANT`).** À **valider humainement AVANT toute collecte**. Ordre (le code de
collecte n'est écrit qu'**après** validation) :

① valider cette spec **+ remplir/valider l'Annexe A (univers + fenêtre)** → ② **collecter** selon la spec
(univers/venues figés ; brut append-only ; hash) → ③ **certifier** (manifeste + QC §9) → ④ la série
certifiée entre **alors** dans la procédure **calibration / règle figée / test** (contrat §4). **Aucune
collecte ni appel réseau tant que ① (spec + Annexe A) n'est pas validé.**

---

## Annexe A — À figer et valider AVANT toute collecte

> **GATE de collecte.** Tant que **A.1 (univers)** OU **A.2 (fenêtre)** est **vide ou non validé**,
> **AUCUNE collecte et AUCUN appel réseau ne sont autorisés.**

### A.1 Univers à figer avant collecte — *table OBLIGATOIRE (vide = collecte INTERDITE)*

| venue | `perp_market_id` | sous-jacent | type de contrat | devise marge/règlement | multiplicateur | endpoint primaire |
|---|---|---|---|---|---|---|
| *(à remplir et valider humainement — aucune ligne ⇒ collecte interdite)* | | | | | | |

### A.2 Fenêtre temporelle à figer — *GATE (à remplir + valider avant tout appel réseau)*

- `start_utc` = **__________** *(à remplir)*
- `end_utc` = **__________** *(à remplir)*
- `≥ 1 an` reste un **objectif de couverture**, jamais un défaut : la fenêtre exacte est **explicite et
  gelée ici** avant toute collecte.
