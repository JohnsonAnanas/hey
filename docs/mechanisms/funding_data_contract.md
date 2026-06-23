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

- **Règle de sélection (anti-look-ahead).** Conserver les observations **par marché/venue** ;
  **interdire toute sélection quotidienne a posteriori de la « meilleure » venue** (`max(exchange)`
  choisi après coup = **enveloppe haute, diagnostic rétrospectif, jamais un PnL exécutable**). Une
  **venue** ou une **règle de sélection** doit être **fixée avant la fenêtre de test**, sur **données
  observables avant le règlement**.

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
| **`breadth = 0`** | Métrique **définie mais dégénérée** dans cet agrégat : `breadth` = fraction d'actifs **au-dessus de 15 %/an** (`--hot 15`), **seuil jamais franchi** (funding ≤ ~10,9 %) | Ne permet **pas de caractériser des épisodes chauds** (constante à 0) | Recalibrer le seuil, ou ne pas l'utiliser comme mesure d'ampleur |
| **Convention de signe absente** | Le signe du funding n'est pas énoncé | Un signe inversé inverse la thèse | Documenter + vérifier par venue |
| **Non manifestée / non hashée** | Pas de manifeste ni de hash | **Non certifiée** (gate §5.1 échoue) | Manifester + hasher, ou produire une série certifiée |
| **Sélection a posteriori de la venue** | `best_carry = max(exchange)` : la meilleure venue est choisie **après coup**, chaque jour | **Enveloppe haute / diagnostic rétrospectif** — jamais un PnL exécutable | Conserver les obs **par marché/venue** ; venue/règle **fixée avant le test** (données observables **avant le règlement**) |
| **Brut absent du projet** | Obs par marché/venue calculées **en mémoire**, jamais écrites | Agrégat **non reconstructible** ; brut **ni archivé ni présent dans le projet** | Produire/archiver une série **brute** certifiée (§2a) |

> **Conclusion (enquête de provenance, 2026-06-23).** Producteur `funding_regime.py` (ccxt binance/okx,
> panier de 22 coins) ; CSV **non suivi Git, sans manifeste** ; **brut par marché ni archivé ni présent
> dans le projet** (calculé en mémoire, jamais écrit) ; `breadth=0` **expliqué** (fraction > 15 %/an,
> jamais atteinte) ; plafond ~10,9 % **sans cap dans le code, invérifiable sans brut** ; surtout
> `best_carry = max(exchange)` = **enveloppe haute a posteriori** (diagnostic rétrospectif, jamais un
> PnL exécutable). → `funding_regime.csv` est **définitivement INDICATIF / NON UTILISABLE POUR DÉCIDER**.
> **On ne le répare pas** : il faut **produire une nouvelle série certifiée** (§2a, brut par marché,
> hashée). Cf `STATE.md §4`, `EVIDENCE_LEDGER` (funding = `NON_CONCLUANT`).

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
