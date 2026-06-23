# Contrat de l'évaluateur de route (Phase B) — FIGÉ

> Mission : établir si on peut capter des **inefficiences DeFi lentes, liquides, persistantes** dues à
> la **fragmentation de liquidité entre protocoles d'une même chaîne**. PAS des « bugs », PAS des prix
> affichés. Sortie = **tableau de décision**, jamais une liste d'« opportunités ».
> Code : [`../sim/route_eval.py`](../sim/route_eval.py), [`../sim/amm_v2_int.py`](../sim/amm_v2_int.py),
> [`../scan_dex_intrachain.py`](../scan_dex_intrachain.py).

## Périmètre (verrouillé)
Lecture seule · **Base seule** · petit univers de tokens **certifiés** · identité certifiée **avant tout
calcul** · pools liquides+actifs · **pas** d'exécution / clé privée / flash loan / mempool · **pas** de
cross-chain actif. Tout run produit un **manifeste** ([`run_manifest_standard.md`](run_manifest_standard.md)).

## Les 7 portes (chacune REJETTE avec MOTIF explicite)
| # | Porte | Règle |
|---|---|---|
| 1 | **Identité certifiée** | les 2 pools référencent le **même contrat** de token, ET ce token ∈ univers certifié **par adresse**. Jamais un ticker, jamais un seuil. Décimales **re-vérifiées on-chain** au run. |
| 2 | **Quote exécutable, math ENTIÈRE EVM** | `getAmountOut` en **wei, floor division** (UniV2 997/1000 ; Aerodrome = retire fee bps puis x·y=k). Le float n'EXPLORE (Δx*) ; l'entier **classe**. Jamais un mid. |
| 3 | **Décomposition séparée** | `PnL brut` (frais nuls) − `frais de pool` − `gas (au bloc)` = `PnL net`. **Le gas compte UNE seule fois.** + `marge de sécurité de statut` distincte. |
| 4 | **Persistance (figée, ci-dessous)** | à **taille fixe**, sur ≥ `min_blocks` ; proxy de compétition/MEV, **pas** une preuve. |
| 5 | **Courbe taille→PnL** | au minimum : taille optimale, PnL net max, **taille de break-even** (capacité), **taille gardant 90 %** du max, taille min viable (gas couvert). |
| 6 | **Capacité max** | dernière taille net ≥ 0 ; notionnel USD déployable. |
| 7 | **Rejet explicite** | toute condition manquante → `REJETE` + motif. **v3 → `REJETE: v3_quoter_non_implemente`**, jamais ignoré silencieusement. |

## Définition de la persistance (FIGÉE avant tout run)
Mesurée à **taille observée FIXE** (figée à la 1ʳᵉ observation A_OBSERVER de la route, même taille à
chaque bloc pour comparabilité). On rapporte : **n blocs** observés, **% de blocs à PnL net > 0**,
**plus longue séquence consécutive** positive, **couverture** (blocs) et **abstentions**. C'est un
**proxy de compétition/MEV**, jamais une preuve de capturabilité (un gap qui dure peut être inexécutable ;
un gap mort en 1 bloc = course MEV perdue par un solo).

## Tableau de décision (sortie)
`paire | venue_a→venue_b | taille optimale | PnL net | capacité (USD) | persistance | risque | statut`

**Statut** (un seul bloc ⟹ jamais FORWARD) :
- **REJETÉ** — une porte échoue (v3, identité non certifiée, pas de quote, `pnl_net ≤ 0`).
- **À OBSERVER** — `pnl_net > 0` ce bloc, en attente de persistance.
- **CANDIDAT FORWARD** — À OBSERVER **+** persistance (`% ≥ p_min`, streak ≥ s_min, n ≥ min_blocks)
  **+** `net ≥ marge` **+** `capacité ≥ cap_min`. Attribué par le runner, **multi-blocs**.

## Conservatisme (exigé)
- Identité = **univers certifié par adresse** ([`../config/universe_base.json`](../config/universe_base.json),
  versionné : adresse, decimals, source, date), jamais un ticker, jamais un seuil. Même adresse
  cross-chain **≠** preuve d'identité économique → cross-chain **gelé** (registre de bridge officiel +
  coût de rééquilibrage requis d'abord).
- Le classement d'un PnL marginal est en **math entière EVM** (#2).
- **Couverture toujours rapportée** : routes v2 évaluées, **routes v3 abstenues**, pools rejetés + motifs.
  **Un tableau vide est une mesure de couverture, PAS une absence d'alpha DeFi.**
- **Funding = benchmark secondaire**, hors mission.

## Calibration
L'univers Base {WETH, USDC, cbETH, cbBTC, AERO} est un **univers de calibration du moteur**, pas une
conclusion. Le 1ᵉʳ run sert à valider le moteur et mesurer la couverture (en particulier : combien de
liquidité Base vit en **v3**, donc abstenue tant que le quoter v3 n'est pas instrumenté).

---

# Phase v3 — quoteur historique exact (gel des ajustements, AVANT de coder)

Brique : quote v3 **exacte au bloc** via le **QuoterV2 canonique** Uniswap (Base `0x3d4e44Eb…76a`,
vérifié on-chain : code présent, prix qui baisse avec la taille + ticks croisés = vrai swap, jamais un
mid/slot0). Code : [`../sim/quote_v3.py`](../sim/quote_v3.py), [`../sim/route_quoted.py`](../sim/route_quoted.py),
[`../backfill_v3.py`](../backfill_v3.py). Périmètre figé validé : Base · univers certifié · UniV3 {500, 3000} ·
routes **v3↔v3 et v3↔v2** · grille USD **{1k, 5k, 25k, 100k, 250k}** · cadence **horaire** · 1ʳᵉ fenêtre **2 jours**.

**1. Le run de 2 jours est strictement de la CALIBRATION TECHNIQUE.** Il **NE PEUT PAS** produire le statut
`CANDIDAT_FORWARD`, même si un PnL positif apparaît. Il valide UNIQUEMENT : quotes historiques, couverture,
coût, courbe de taille, qualité des abstentions. **Toute conclusion économique exige ensuite une fenêtre
PRÉFIXÉE de 7–14 jours.**

**2. `baseFee` seul n'est PAS le coût du gas sur Base.** Le coût est nommé **`gas_estime_conservateur`**
(jamais « exact » tant qu'un executor n'existe pas), et **séparé en 3** :
- `gas_exec` — gas d'exécution estimé **par type de route** (le `gasEstimate` du QuoterV2 par jambe pour v3,
  forfait par type pour v2) × `baseFee` du bloc ;
- `gas_l1_data` — coût L1/data de la transaction (OP-Stack) — estimé conservateur ;
- `gas_marge` — marge de sécurité.

**3. La persistance est un champ DESCRIPTIF et un classement, JAMAIS une condition qui rejette un PnL positif.**
Statuts (la cadence horaire ne mesure QUE les dislocations lentes visibles à notre cadence, pas les écarts de secondes) :
- `REJETE` — porte échoue / `pnl_net ≤ 0` ;
- `MEV_RACE` — `pnl_net > 0` mais isolé (1 bloc / streak ≈ 1) → course probable ;
- `A_OBSERVER_COURT` — `pnl_net > 0`, persistance présente mais **sous** le seuil long ;
- `A_OBSERVER` — `pnl_net > 0` **et** persistance mesurée suffisante ;
- `CANDIDAT_FORWARD` — **seulement** après la fenêtre longue (7–14 j) ET les autres portes (**jamais en calibration**).

**4. La conversion USD de chaque taille vient d'une ANCRE INDÉPENDANTE**, lue **au même bloc**, **jamais du pool
candidat lui-même** (WETH ⟵ pool WETH/USDC le plus profond hors-route ; stable = 1). **Ancre absente → abstention
explicite** (`ancre_independante_absente`), jamais une valeur de secours.

**5. Le rapport SÉPARE la couverture** en buckets distincts : routes v3 trouvées · quotes réussies · quotes
revert/illisibles · routes v2 · pools/tokens exclus · raisons d'abstention. **Un résultat vide sur cet univers
de calibration ne sera JAMAIS interprété comme « il n'existe pas d'alpha DeFi ».**

**Optimisations SÛRES (n'altèrent pas le résultat, seulement le coût)** :
- **Pré-filtre slot0/mid** : si l'écart de mid entre les 2 pools `< frais de pool`, la quote exacte (toujours
  `≤ mid` par l'impact) **ne peut pas** être profitable → route rejetée `sous_frais_mid_prefiltre` **sans quoter**.
  Aucun faux négatif (on ne saute qu'un profit mathématiquement impossible). Seules les routes au mid-gap `≥ frais`
  sont **exact-quotées**.
- **Monotonie de taille** : les tailles sont croissantes ; si une taille ne se remplit pas (quote revert), les
  tailles supérieures non plus → on cesse de quoter. Les tailles inférieures déjà remplies sont conservées.

> Rappel : la quote v3 (réserves + simulation de swap) est une **borne SUPÉRIEURE** — elle ne voit ni les
> transactions concurrentes intra-bloc ni le positionnement MEV. **Pas une preuve de PnL exécuté.**
