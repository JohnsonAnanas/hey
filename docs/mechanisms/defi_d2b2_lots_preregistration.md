# Pré-enregistrement D2B-2 — lots déterministes (145 routes vivantes)

> **PRÉ-ENREGISTRÉ avant données.** Documentaire + runner D2B-2-lots **hors réseau** (gèle les lots AVANT
> toute mesure). **Réseau D2B-2 INTERDIT sans validation humaine explicite.** Réf : D2B-1 (`LIVENESS_OK`,
> B1 = 47762470, 145 vivantes), exécuteur simulé D1.6, ordre gelé D2B-0.

## 0. Objet
D2B-2 mesure, pour chaque **route vivante** (D2B-1), la **borne atomique** (upper bound **hors priorité
MEV**, jamais un PnL garanti) sur la grille et la fenêtre figées. C'est **le premier test pouvant voir une
borne positive**. Cohorte = les **145 routes vivantes** (non-revert des deux sens à $250 en D2B-1),
**dans l'ordre `route_hash` gelé** (sous-ensemble vivant de l'ordre D2B-0). **Aucun choix opportuniste** :
l'ordre et les lots sont gelés avant les quotes.

## 1. Échelle réelle
`145 routes × 300 blocs × 5 tailles × 2 directions = 435 000 cycles atomiques simulés.`
Volume élevé ⇒ **découpage en lots déterministes** (définis AVANT les quotes). **Tous les lots doivent être
exécutés ; aucun arrêt après un résultat ± ; l'ordre gelé ne change jamais.**

## 2. Découpage en lots (figé)
- **`lot_size = 5` routes** ⇒ **29 lots** (145 = 5 × 29), dans l'ordre `route_hash` gelé.
- Route *i* (0-based, ordre gelé) → **lot `i // 5`**. Affectation **déterministe**, gelée par
  `d2b2_lots.py` (hors réseau) ; chaque lot porte un `lot_digest` (sha256 des `route_hash`), et le plan un
  `plan_digest`.
- À l'exécution : les lots sont parcourus **dans l'ordre** ; **chaque lot est exécuté en entier** ; aucun
  lot n'est sauté, réordonné, ni interrompu sur un résultat.

## 3. Paramètres figés (avant données)
- Cohorte : 145 routes vivantes (D2B-1), ancre **USDC** `0x8335…2913` (entrée en USDC).
- Grille : `$250 / $1 000 / $2 500 / $5 000 / $10 000`. Fenêtre : `N = 300` blocs (figés au lancement de
  CHAQUE lot ; à consigner par lot). Directions : `usdc→other→usdc` via Uni puis Slip, **et** l'inverse.
- Exécuteur : `CrossProtocolExecutor` D1.6 (bytecode versionné, source sha `53417e97…`, solc
  `0.8.26+commit.8a97fa7a`, evm `cancun`, optimizer runs=200). Mesure : sortie atomique exacte (`eth_call`),
  gas L2 (`estimateGas`) + L1 (`getL1Fee`) sur octets exacts ; **priorité MEV exclue → borne supérieure**.
- **Ancre ETH/USD (conversion du gas)** : feed **Chainlink ETH/USD canonique Base**
  `0x71041dddad3595F9CEd3DcCFBe3D1F4b0a16Bb70`, `decimals=8`, fonction `latestRoundData()`, **lue au bloc
  b** ; garde-fous `answer>0`, `updatedAt ≤ timestamp(b)`, **staleness ≤ 3600 s** (préenregistré ; max
  observé sur la fenêtre = 618 s) ; **indépendante des pools cibles** (oracle, pas un pool). Absence /
  staleness / erreur du feed → `NON_CONCLUANT`, **jamais gas=0**.

## 4. Règles de mesure (par route, dans chaque lot)
- Pour chaque (taille, direction, bloc) : `upper_bound_atomique = sortie − entrée − gas_normal` (USD).
- **Reverts aux tailles supérieures = résultats de CAPACITÉ**, jamais une exclusion silencieuse.
- Sortie : **courbe `taille → upper_bound`** + **persistance** (sur 300 blocs) + **capacité**, par route.
- **Tous les résultats = bornes supérieures hors priorité MEV** ; **aucun PnL garanti**, **aucun verdict
  économique** dans D2B-2 (l'interprétation économique est une décision ultérieure).
- Un `upper_bound > 0` sur une route ⇒ **présumé compétitif (audit renforcé)**, jamais un signal d'achat.

## 5. Gouvernance
- Lots gelés **hors réseau** (`d2b2_lots.py`) + versionnés AVANT tout réseau. Lecture seule ; **aucun
  contrat, clé, wallet, approbation, transaction ni capital** (override de code = simulation).
- **Chaque lot réseau exige une autorisation humaine** (ou un feu vert global pour la série, à ta main).
- Tout problème slot/RPC/code-override/coût incomplet à un lot → `NON_CONCLUANT` pour ce lot, avec la limite
  exacte ; jamais silencieusement traité.
- Considération RPC : ~3 900 appels/route ⇒ ~19,5k appels/lot (Alchemy) — à surveiller (quota CU).
