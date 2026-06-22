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
