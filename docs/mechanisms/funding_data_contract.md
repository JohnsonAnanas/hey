# Contrat de données — Funding (track C, cash-and-carry)

> **Statut : `NON_CONCLUANT`. Document de gouvernance, présenté pour validation humaine AVANT toute
> mesure.** Aucun code, réseau, collecte ni backfill. Compagnon de
> `docs/mechanisms/funding_cash_and_carry.md` (gates §5.1 certification, §5.3 règle d'entrée).
>
> **Aucun seuil chiffré d'entrée n'est fixé ici.** La série actuelle n'est **pas certifiée** : elle ne
> peut donc **pas** servir à calibrer une règle. Ce document définit (a) le **schéma minimal** d'une
> série de funding certifiée, (b) ses exigences de **provenance**, (c) la **procédure** qui séparera
> *ultérieurement* **données de calibration / règle figée / fenêtre de test**, et (d) l'**état bloquant**
> de `data/logs/funding_regime.csv`.

## 1. Objet & principe

- Définir ce qu'une série de funding doit être **avant de servir à décider**, et la procédure de
  séparation calibration/règle/test. **Aucun rendement estimé, aucun seuil calibré ici.**
- Principe (§9 — recherche historique sans auto-illusion) : **séparer strictement** les données de
  **calibration** (in-sample), la **règle figée** (préenregistrée), et la **fenêtre de test**
  (out-of-sample) ; **ne jamais** calibrer sur une donnée non certifiée ; **ne jamais** retoucher un
  seuil après avoir vu le test.

## 2. Schéma minimal d'une série de funding **certifiée**

Toute observation de funding est une **donnée brute archivée+hashée** (la brute fait foi par son hash,
§4/§5). On **sépare le brut par marché (§2a) des métriques agrégées (§2b)** : un agrégat n'est
certifiable que s'il est **reconstructible depuis le brut certifié** (§6 doctrine).

### 2a. Schéma BRUT, par marché — *l'unité certifiée (une ligne par marché × settlement)*

| Champ | Définition | Obligatoire | Note |
|---|---|---|---|
| `venue` | Plateforme du perp (CEX / perp DEX) | ✅ | Vettée (ToS, retrait) — mécanisme §5.6 |
| `perp_market_id` | **Identifiant exact du marché perp** (instrument/symbole) | ✅ | Le marché précis, pas seulement l'actif |
| `asset` | Sous-jacent, **mapping économique canonique** (actif + réseau + contrat/decimals + transférabilité) | ✅ | Doit matcher la jambe spot ; `config/economic_identity.json` |
| `margin_settlement_ccy` | **Devise de marge / de règlement** (USDT, USDC, coin-margined…) | ✅ | Monnaie dans laquelle le funding est réglé |
| `contract_multiplier_unit` | **Multiplicateur / unité** du contrat | ✅ | Pour convertir taux → montant réglé |
| `funding_rate` | Taux de funding **réglé, par settlement** (brut, non annualisé) | ✅ | Valeur réglée, pas un mid affiché |
| `funding_formula_cap` | **Formule de funding de la venue + plafond/cap** éventuel | ✅ | **Explique un plafond** (cf §5) ; sans elle, une valeur capée est un artefact |
| `sign_convention` | Qui paie qui — **fait de venue, certifié ici** (pas un choix de calibration) | ✅ | Un signe inversé inverse la thèse |
| `mark_index_basis` | Prix mark/index servant au funding | ✅ | Base du calcul de la venue |
| `settlement_interval` | Période entre settlements + **calendrier** | ✅ | Nécessaire pour cumuler/annualiser |
| `fixing_time_utc` | **Instant de fixation** du funding | ✅ | Distinct du règlement |
| `settlement_time_utc` | **Instant de règlement** | ✅ | Quand le funding est effectivement échangé |
| `source` / `endpoint` | Provenance brute (API/endpoint) | ✅ | Reproductible |
| `request_hash` / `response_hash` | Empreintes brutes | ✅ | Immuabilité (`manifest.py`) |
| `completeness` | Gaps, halts, manquants **explicités** | ✅ | **Jamais de remplissage silencieux** (abstention) |

### 2b. Métriques AGRÉGÉES — *dérivées du brut certifié, jamais l'inverse*

| Métrique | Définition | Note |
|---|---|---|
| `n_markets` / `n_assets` | Nombre de marchés / actifs couverts | **Déplacé du brut** : descripteur d'agrégat |
| `universe` | Périmètre (actifs, venues) + critères | Doit pointer vers les marchés bruts inclus |
| niveau / p90 / dispersion / `breadth` | Statistiques cross-marché | **Calculées depuis le brut certifié**, jamais saisies à la main |

- **Annualisation — explicite.** Toute valeur « %/an » déclare la méthode : **simple**
  (`taux_settlement × nb_settlements_par_an`) **ou composée** (`(1 + taux_settlement)^(nb_settlements_par_an) − 1`),
  **et la convention de jours** (365 vs 360 ; nb de settlements/an selon le calendrier). Sans cela, un
  « %/an » est **ininterprétable**.
- **Reconstructibilité (gate).** Un agrégat **n'est certifiable que s'il se reconstruit** depuis le brut
  certifié (§6 doctrine). Un agrégat **sans brut primaire** (ex. `funding_regime.csv`) **n'est pas
  certifiable** → §5 : on **ne répare pas** un agrégat sans sa **provenance primaire**.

## 3. Provenance (exigences)

- **Source explicite** (venue + endpoint) et **méthode de collecte** (à écrire le moment venu — pas
  maintenant), horodatée, **append-only** (brute immuable, re-testable).
- **Convention de signe** documentée **et vérifiée** par venue.
- **Méthode d'annualisation** explicite — **simple/composée + convention de jours** (cf §2b ; sinon un « %/an » est ininterprétable).
- **Univers et complétude** documentés (actifs, venues, gaps, halts).
- **Manifeste + hash** (`docs/run_manifest_standard.md`) : une série non manifestée n'est pas certifiée.

## 4. Procédure de séparation **calibration / règle figée / test**

L'ordre est strict ; **un seuil chiffré n'existe qu'à l'étape 3**, jamais avant certification.

0. **Pré-condition — certification** : la série respecte le **schéma §2 (brut §2a + agrégées §2b) +
   provenance §3 + hash**. La **convention de signe** est **certifiée ici** comme un **fait de venue**,
   **pas** un choix de calibration. Sinon **STOP** : aucune des étapes ci-dessous (gate §5.1 du
   mécanisme).
1. **Données de calibration (in-sample)** : une **fenêtre préenregistrée**, **disjointe** du test,
   destinée à **concevoir** la règle d'entrée (**persistance, seuil** ; le signe est déjà certifié §0).
   Déclarée **avant** de regarder le test.
2. **Conception de la règle** : sur la calibration uniquement — choix du **seuil**, de la **condition
   d'entrée** et de l'**horizon** (la **convention de signe** est déjà un fait de venue certifié §0,
   **pas** un paramètre de calibration).
3. **Règle FIGÉE** : la règle est **gelée et préenregistrée** (un artefact daté+hashé). **Aucune
   modification ultérieure.**
4. **Fenêtre de test (out-of-sample)** : **disjointe** de la calibration, **préenregistrée**, pour
   **évaluer** la règle figée. **Aucun re-tuning** après avoir vu le résultat (§9 : pas de retouche des
   seuils a posteriori).

| Jeu | Rôle | Préenregistré ? | Interdit |
|---|---|---|---|
| **Calibration** (in-sample) | Concevoir la règle | Fenêtre déclarée avant | Servir aussi de test |
| **Règle figée** | Geler seuil/condition/horizon (signe = fait de venue, §0) | Artefact daté+hashé | Être modifiée après coup |
| **Test** (out-of-sample) | Évaluer la règle figée | Fenêtre déclarée avant | Re-tuning après résultat ; chevauchement avec calibration |

## 5. État bloquant de `data/logs/funding_regime.csv`

| Défaut | Description | Pourquoi ça bloque | À expliquer / résoudre |
|---|---|---|---|
| **Provenance non documentée** | Colonnes `level_pct_an`, `p90_pct_an`, `breadth`, `n_assets` sans source, venues, settlement, méthode d'annualisation | On ne sait pas **ce qui est mesuré** ni comment | Venue(s), calendrier de settlement, convention de signe, méthode d'annualisation |
| **Plafond suspect ~10,9 %** | Valeurs plafonnées (ex. `level=p90=10.95`) | Cap ou artefact → **distribution faussée** | Origine du plafond (cap exchange ? bug de calcul ?) |
| **`breadth = 0`** | Colonne constante à 0 sur la série | Indicateur **cassé ou mal défini** → inexploitable | Définition de `breadth` et pourquoi elle est nulle |
| **Convention de signe absente** | Le signe du funding n'est pas énoncé | Un signe inversé inverse la thèse | Documenter + vérifier par venue |
| **Non manifestée / non hashée** | Pas de manifeste ni de hash | **Non certifiée** (gate §5.1 échoue) | Manifester + hasher, ou produire une série certifiée |

> **Conclusion honnête.** Tant que **provenance, plafond suspect et `breadth=0`** ne sont **pas expliqués
> et résolus**, `funding_regime.csv` est **NON UTILISABLE pour décider** — ni pour **calibrer** une
> règle, ni pour **tester**. C'est au mieux une **série indicative non certifiée** (cf `STATE.md §4`,
> `EVIDENCE_LEDGER` : funding = `NON_CONCLUANT`). Aucune mesure ne doit s'y appuyer.

## 6. Gate de certification (rappel du mécanisme)

Reprend **gate §5.1** de `funding_cash_and_carry.md` : données non **certifiées+hashées** ⇒
**abstention**, aucune mesure. **Critères d'acceptation** : schéma §2 complet **+** provenance §3 **+**
hash **+** les défauts du §5 résolus.

## 7. Statut & suite

**`NON_CONCLUANT`.** Document présenté pour **validation humaine avant toute mesure**. Suite (toujours
**sans code** tant que non validé) :

① valider ce contrat → ② **expliquer/résoudre** les défauts de `funding_regime.csv` (provenance,
plafond, `breadth`) **ou acter son inutilisabilité** → ③ produire/certifier une série conforme (§2/§3,
hashée) → ④ **alors seulement** : calibration → **règle figée** → test (§4). **Aucun seuil chiffré
n'est défini tant que ③ n'est pas atteint.**

## Note (hors-scope) — candidat gelé, distinct du funding

Le **DEX↔CEX rapide sur ETH/WETH** (exécution **à la seconde**) est un **candidat futur GELÉ**,
**jamais testé proprement à la seconde**. Il est **distinct du track funding** décrit ici et **ne doit
lancer aucun travail** (§13). Noté pour mémoire uniquement.
