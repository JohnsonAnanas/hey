# Dossier — sources officielles candidates (funding cash-and-carry, ETH)

> **Reconnaissance documentaire PRÉLIMINAIRE, présentée pour validation humaine.** Aucune collecte,
> aucun appel réseau, aucun code, **aucune doc officielle lue à ce stade**. Périmètre minimal proposé :
> **ETH spot + ETH perp sur UNE SEULE venue** (pas de multi-venue ; cf `funding_acquisition_spec.md
> §11`). **Annexe A NON remplie. Aucune venue recommandée ni choisie par défaut.**
>
> Tout ci-dessous est **HYPOTHÈSE / candidat à VÉRIFIER** par **reconnaissance documentaire officielle**
> (permise, autorisée humainement — spec §1bis), selon le **protocole §6**. Rien ne fait foi tant que la
> doc officielle n'est pas lue et sourcée. **La liquidité n'est pas une donnée documentaire** et ne sert
> pas au choix à ce stade.

## 1. Périmètre minimal proposé

- **ETH spot + ETH perpétuel sur une seule venue CEX** (spot et perp co-localisés → delta-neutre
  propre, marge/règlement en USDT). **Pas de sélection ni bascule multi-venue** (mécanisme futur séparé).
- Contrat perp **linéaire USDT-margin** privilégié (la jambe spot `ETH/USDT` matche la quote du perp) —
  **à vérifier** ; coin-margined (inverse) écarté pour ce premier test (marge en ETH → complexité).

## 2. Candidats (déjà en jeu dans le projet)

- **Binance**, **OKX** — déjà utilisées par `funding_regime.py` (ccxt). **Candidats à égalité.**
- *(Bybit = candidat tiers commun ; hors périmètre minimal sauf décision explicite.)*

## 3. Grille à vérifier (par reconnaissance documentaire officielle)

> Cellules = **hypothèses à confirmer** ; aucune valeur n'est figée tant que la doc officielle n'est pas
> lue et sourcée (§6).

| Point à vérifier | Binance (hypothèse) | OKX (hypothèse) |
|---|---|---|
| Marché **spot** ETH (id) | `ETHUSDT` ? | `ETH-USDT` ? |
| Marché **perp** ETH (`perp_market_id`) | `ETHUSDT` (USDⓈ-M) ? | `ETH-USDT-SWAP` ? |
| **Type de contrat** | linéaire USDT-M ? | linéaire USDT ? |
| **Devise de marge/règlement** | USDT ? | USDT ? |
| **Multiplicateur/unité** | ? | ? (contractSize) |
| **Intervalle de funding + calendrier** | ? | ? |
| **Convention de signe** | ? | ? |
| **Instants fixation / settlement** | ? | ? |
| **Cap de funding (formule + plafond)** | ? | ? |
| **Endpoint funding documenté** | ? | ? |
| **Endpoint historique funding + profondeur** | ? | ? |

*(Les ids `ETHUSDT` / `ETH-USDT-SWAP` et le type linéaire USDT-M sont des **repères usuels à vérifier**,
**pas** des faits.)*

## 4. Hypothèses à vérifier *(rien de documenté tant que la doc officielle n'est pas lue)*

> Aucune doc officielle n'a été lue : les points ci-dessous sont des **hypothèses/candidats à VÉRIFIER**,
> **pas** des contraintes documentées.

- **Hypothèse** : Binance et OKX auraient chacune **ETH spot + perp USDT-M sur la même venue**
  (single-venue) — **à vérifier**.
- **Hypothèse** : existence d'un **mécanisme de funding documenté** et d'un **endpoint d'historique de
  funding** (qui permettrait un backfill certifié) — **à vérifier** (rien de lu).
- **Hypothèse** : **convention de signe** et **cap** publiés par venue — **à vérifier**, puis **à
  certifier à l'acquisition** (spec §0/§9).
- Risque générique (non spécifique) : **ToS / retrait / contrepartie** — **à vérifier** au vetting
  (spec §5.6/§10).

## 5. Pas de recommandation à ce stade

- **Aucune doc officielle n'a été lue → aucune venue n'est recommandée ni écartée.** Binance et OKX sont
  des **candidats à égalité** jusqu'à la reconnaissance documentaire (protocole §6).
- **La liquidité n'est PAS une donnée documentaire** : elle **ne sert pas au choix** à ce stade.
- Un choix de venue ne sera **proposé qu'après** la reconnaissance documentaire (grille §3 remplie sur
  **sources officielles**) et **validé humainement**.

## 6. Protocole de reconnaissance documentaire

Toute caractéristique vérifiée doit être **traçable**. Pour **chaque** point de la grille §3, consigner :

- **Source officielle uniquement** (doc/API officielle de la venue ; **jamais** un agrégateur ou un
  tiers).
- **URL exacte** de la page consultée.
- **Date d'accès** (UTC).
- **Version / date de la documentation** si disponible.
- **Extrait** cité (verbatim) **ou hash** de l'artefact documentaire (capture).

Règles :
- **Aucun appel aux endpoints de données de marché** (funding, prix, klines…) : on lit la **doc**, pas
  les données (spec §1bis).
- **La liquidité n'est pas une donnée documentaire** → **hors critères** de choix à ce stade.
- Un point **non sourçable** reste **« à vérifier »** ; il **n'est jamais promu en fait**.

## 7. Prochaine étape (après ta validation + commit)

Sur ton autorisation : **reconnaissance documentaire officielle** des candidats (lecture de leur doc
funding — permis §1bis, **selon le protocole §6, aucune collecte**) → remplir la **grille §3** avec
sources/URL/date/extrait → **alors** proposer une **venue** et la/les **ligne(s) Annexe A.1** (ETH spot
+ ETH perp) **pour validation**. **Aucune collecte ni réseau** tant que l'Annexe A n'est pas remplie et
validée.
