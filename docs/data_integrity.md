# Charte d'intégrité des données — `arb/`

> **Principe.** Des données non fiables rendent les calculs *pires* qu'inutiles : ils cachent les
> vraies opportunités (faux négatifs) et nous égarent (faux positifs). Donc : **échouer fort /
> s'abstenir** — tout invariant non tenu produit **aucun chiffre** (abstention loggée + motif),
> jamais un skip muet ni une valeur peut-être fausse. On traite des **classes**, pas des instances.

Cette charte liste chaque invariant, la **garde** qui le tient, et les **limites assumées**.
À relancer après tout changement de couche données : `python checks.py` (tests + health-check).

## Invariants tenus (garde → fichier)

### Source / RPC / temps
| Invariant | Garde | Où |
| --- | --- | --- |
| Le RPC répond, bon `chainId`, et est **au tip** (≤ `FRESH_TOL` blocs du max) | health-gate au démarrage ; écarte non-répondant / en retard | `sim/chain.py` `RPC.__init__`, `choose_primary` |
| On lit sur le fournisseur **le plus frais**, recoupé sur ≥ 2 sources (quorum) | sonde de fraîcheur par lecture + rotation ; `fresh_ok` exposé | `sim/chain.py` `_ensure_fresh`, `choose_primary` |
| Pas de **régression de bloc** (reorg / RPC incohérent) | détection + **abstention du poll** | `sim/chain.py` `is_block_regression` ; `sim/integrity.py` `poll_should_abstain` |
| **Le bloc est la référence temporelle** (jamais l'horloge locale) | `read_block` renvoie `(block, block_ts)` ; loggés par ligne | `sim/chain.py` `read_block` ; runners |
| Lectures d'un poll **au même bloc** | Multicall3 `aggregate3` (1 eth_call atomique) | `sim/chain.py` |

### Pool / token
| Invariant | Garde | Où |
| --- | --- | --- |
| `token0` **et** `token1` == paire attendue triée (réserves non inversées) | porte de validation ; quarantaine sinon | `sim/validate.py` `judge_pool`/`validate_pools` |
| Pool **constant-product** (Aerodrome : `stable()==False`) | lecture `stable()` ; quarantaine si stable | idem |
| **Frais réels** : Aerodrome lus on-chain (`getFee`, **pas** de fallback muet) ; forks canoniques 0.30% marqués `fee_verified` | porte de validation ; `fee_verified` explicite | idem ; `run_mav_multi.py` (fallback → `None`) |
| Frais dans des bornes saines, réserves finies/positives/bornées | garde math → **abstain** | `sim/amm_v2.py` `_pool_sane`, `evaluate_pair` |
| Pas de **doublon** de pool | dédup par adresse | `sim/validate.py` |

### Référence de prix / calcul
| Invariant | Garde | Où |
| --- | --- | --- |
| `eth_usd` vient du pool WETH/USDC **le plus profond** (jamais le premier venu) | `derive_eth_usd` | `run_mav_multi.py` |
| `eth_usd` **recoupé vs source externe** (Binance) ; alerte si écart > 300 bps | cross-check au démarrage | `run_mav_multi.py` ; `verify_data.py` |
| Pas d'ancre WETH/USDC liquide → **abstention du poll** | garde | `run_mav_multi.py` |
| Math `Δx*` == argmax brute-force ; valorisation dust correcte | tests | `tests/test_amm_v2.py`, `tests/test_pricing.py` |

### Identité d'actif inter-venue (CEX↔CEX, cross-chain)
| Invariant | Garde | Où |
| --- | --- | --- |
| Un écart inter-venue n'est valide que si les deux jambes sont **le même actif à la même échelle** | abstention si non prouvé | `sim/identity.py` ; `tests/test_identity.py` |
| **Un vrai arbitrage est directionnel** : profitable dans les DEUX sens ⟹ identité/échelle incohérente | `directional_inconsistency` → abstain | `sim/identity.py` `cex_extractable_guarded` |
| Magnitude **plausible** : un walk de ~20 niveaux ne rend pas des millions (sinon carnet à réconcilier) | `implausible_magnitude` (>$1M) → abstain | idem ; `cex_monitor.py` (abstention loggée) |
| Cross-chain : candidat **porte les adresses** des 2 jambes ; identité par **adresse** (plus de ticker nu) | `crosschain_identity` → `VERIFIED`/`UNVERIFIED`/`COLLISION_SUSPECT` | `sim/identity.py` ; `collector.py` (col `identity`) |

> ⚠️ **Bug de classe corrigé (2026-06-22).** L'appariement par **ticker** produisait des fantômes :
> CEX↔CEX `HYPE` ~$20.6M dans les **2 sens** à 0.6 bps (3352/3363 lignes ≥ $1M) ; cross-chain candidat
> sans adresse. Sorties quarantinées (`data/logs/QUARANTINE.md`, `data/collected/QUARANTINE.md`).

### Traçabilité / abstention
| Invariant | Garde | Où |
| --- | --- | --- |
| Aucun **skip muet** : tout rejet/quarantaine est loggé avec motif | quarantaine loggée ; `next()` → table `fee_by_name` | runners, `sim/validate.py` |
| Chaque ligne loggée porte sa **provenance** : `block, block_ts, fresh_ok, n_sources` | colonnes d'intégrité | `run_mav_multi.py` |
| **Toute conclusion rapporte sa couverture** (n blocs, durée) | ligne `COUVERTURE` ; alerte si < 30 blocs | `run_mav_multi.py` synthèse |

## Limites ASSUMÉES (durcissements suivants, pas des angles morts cachés)

1. **Recoupement quoter universel** (router `getAmountsOut` == notre formule, par pool) : non
   généralisé (routers hétérogènes UniV2 vs Aerodrome). Aujourd'hui : frais Aerodrome lus on-chain,
   forks canoniques marqués `fee_verified=True`, **BaseSwap marqué `fee_verified=False`** (inclus mais
   signalé). À ajouter pour certifier les frais des forks non canoniques.
2. **Fee-on-transfer programmatique** : non auto-détecté (exige une simulation de swap avec
   state-override). Notre panier actuel (WETH, USDC, cbETH, cbBTC, AERO, DEGEN, BRETT, TOSHI, VIRTUAL)
   est de l'ERC-20 standard ; un token taxé casserait `x·y=k`. À ajouter (probe balance-diff).
3. **Reorgs** : on lit au `latest` et on logge le bloc ; lecture à **bloc confirmé** (`tip-k`) différée
   à la phase exécution (sans exécution, l'impact d'un reorg sur une mesure est borné).
4. **Aveugle au sub-bloc** : poll à l'échelle du bloc → les arbs MEV intra-bloc sont invisibles
   (limite structurelle d'un observateur ; couvert ailleurs par l'analyse, pas par une garde).
5. **Fraîcheur mono-source** : un fournisseur **seul** ne peut pas s'auto-déclarer périmé (pas de pair
   plus frais). D'où l'exigence de **quorum ≥ 2** ; en mode dégradé (1 source), `fresh_ok=False` est
   porté sur chaque ligne.

## Lancer le contrôle

```bash
python checks.py            # pytest (math/pricing/freshness/validate) + health-check live
python verify_data.py       # health-check seul (quorum RPC, same-block, prix vs Binance, log)
```

## Backlog

Les reports ci-dessus (limites assumées) sont suivis avec leurs **déclencheurs** dans
[`integrity_backlog.md`](integrity_backlog.md) — à relire avant tout élargissement de périmètre.
