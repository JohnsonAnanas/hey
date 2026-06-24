# Pré-enregistrement D2B — test de borne atomique cross-protocole (cohorte USDC)

> **PRÉ-ENREGISTRÉ avant données.** Documentaire ; le runner D2B-0 (hors réseau) gèle l'ordre déterministe
> AVANT toute mesure. Réseau (D2B-1, D2B-2) **interdit sans validation humaine explicite**. Réf : registre
> D2A (`REGISTRE_STRUCTUREL_COMPLET` au snapshot B = 47755737), exécuteur simulé D1.6.

## 0. Cadre & terminologie (corrigée)
D2A a livré **535 paires structurellement enregistrées (decimals lisibles)** — **aucune** viabilité
économique, liquidité ni exécutabilité établie. D2B mesure, par **route**, la **borne atomique** (upper
bound hors priorité MEV, jamais un PnL garanti) via l'exécuteur simulé D1.6 — **sans choix opportuniste de
token après avoir vu les écarts** (l'ordre est figé en D2B-0).

## 1. Cohorte initiale = paires contenant directement l'USDC canonique Base
La grille `$250/$1k/$2.5k/$5k/$10k` exige une **ancre USD indépendante**. Donc **cohorte D2B initiale =
uniquement les paires candidates D2A qui contiennent DIRECTEMENT le contrat USDC canonique Base**
`0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913` (jambe d'entrée = USDC, sizing en USD direct).
- Les paires **sans USDC** ne sont **ni rejetées ni oubliées** : elles restent **hors cohorte initiale**, en
  attente d'une **règle d'ancrage séparée et préenregistrée** (futur D2B′).

## 2. Phases (toutes pré-enregistrées)

**D2B-0 — hors réseau (figeage).** Depuis le registre D2A : sélectionner la cohorte USDC, énumérer **TOUTES
les routes `Uni-pool × Slip-pool`** (pour chaque paire : chaque pool Uni v3 × chaque pool SlipStream), et
**figer leur ordre déterministe par `route_hash`** (`sha256` d'un descripteur canonique). Sortie : nombre
de paires de cohorte, nombre de routes, liste ordonnée gelée. **Aucun réseau.**

**D2B-1 — liveness à $250 (réseau, sur validation).** Pour chaque route, dans l'ordre gelé : exécuteur
simulé D1.6 (override `code`+balances), `$250` dans **les deux orientations**. **Filtre = UNIQUEMENT
non-revert des deux orientations** ; **jamais le signe du PnL**. **Toutes les sorties brutes archivées**
(vivantes ET mortes). Pré-condition technique : slot de balance USDC (FiatToken) **auto-vérifié** (override
reflété par `balanceOf`) ; sinon `NON_CONCLUANT`.

**D2B-2 — mesure (réseau, sur validation).** Chaque route **vivante** : **300 blocs**, aux **tailles
figées**, dans l'**ordre déterministe pré-enregistré**. Si le volume est grand : **lots fixes définis AVANT
les quotes**, puis **TOUS les lots exécutés — aucun arrêt après un résultat positif ou négatif**.
- **Reverts aux tailles supérieures = résultats de capacité**, jamais une exclusion silencieuse.
- **Tous les résultats = bornes atomiques hors priorité MEV**, jamais un PnL garanti.

## 3. Paramètres figés (avant données)
- Ancre/cohorte : USDC `0x8335…2913` direct.
- Grille : `$250 / $1 000 / $2 500 / $5 000 / $10 000`. Liveness : `$250`, deux orientations, non-revert.
- Fenêtre : `N = 300` blocs. Exécuteur : `CrossProtocolExecutor` D1.6 (bytecode versionné, sha source
  `53417e97…`, solc `0.8.26+commit.8a97fa7a`, evm `cancun`, optimizer runs=200).
- `route_hash = sha256("{token0}|{token1}|uni:{uni_pool}:{uni_fee}|slip:{slip_pool}:{slip_tickSpacing}")` ;
  ordre = `route_hash` croissant (déterministe, gelé en D2B-0).
- Orientations : `usdc→other(uni) puis other→usdc(slip)` et l'inverse (round-trip ancré USDC).

## 4. Sorties & verdicts (par route, jamais agrégé en signal d'achat)
- D2B-1 : `vivante` / `morte` (non-revert des deux sens) + sorties brutes archivées.
- D2B-2 : **courbe `taille → upper_bound_atomique`** + **persistance** + **capacité** (reverts conservés),
  par route. Verdict d'edge réutilise D0/D1.6 : `ATOMIC_MEV_SCOPE` / `NO_ATOMIC_EDGE` / `NON_CONCLUANT`. Un
  positif sur n'importe quelle route ⇒ **borne supérieure présumée compétitive (audit renforcé)**, jamais un
  PnL tradable.

## 5. Gouvernance
- Runner/tests **versionnés avant réseau** ; lecture seule ; **aucun contrat, clé, wallet, approbation,
  transaction ni capital** (override de code = simulation, pas un déploiement).
- D2B-0 (hors réseau) gèle l'ordre **avant** D2B-1/D2B-2. **D2B-1/D2B-2 (réseau) interdits sans validation
  humaine explicite et distincte.**
- Si l'énumération/override/coût n'est pas fiable à une étape → `NON_CONCLUANT` avec la limite exacte, sans
  fallback.
