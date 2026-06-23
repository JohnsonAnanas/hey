# TIDY_PLAN — plan de rangement minimal (PROPOSITION, rien n'est déplacé)

> Réduire la complexité, rendre code + données + hypothèses lisibles. **AUCUN fichier déplacé ou
> supprimé tant que ce plan n'est pas validé.** Aucune logique économique modifiée.

## A. Classification de l'existant (la carte)

### `sim/` — devrait ne contenir QUE des briques PURES et testées
| Fichier | Pur+testé ? | Action proposée |
|---|---|---|
| `amm_v2.py`, `amm_v2_int.py`, `identity.py`, `route_eval.py`, `route_quoted.py`, `pricing.py`, `integrity.py` | **OUI** (couverts par `tests/`) | **rester dans `sim/`** |
| `validate.py` | mixte : `judge_pool` pur+testé, `validate_pools` fait du réseau | rester (le réseau y est isolé) |
| `chain.py` (RPC/Multicall), `quote_v3.py` (QuoterV2) | **NON — réseau** | candidats à sortir vers `infra/` (cf. C) |

### Scripts de LANCEMENT (produisent de la donnée / réseau)
- Scanners : `scan_dex_gaps.py`, `scan_cex.py`, `scan_crosschain.py`
- Collecteurs persistants : `collector.py`, `cex_monitor.py`
- Runners de mesure : `run_mav_sim.py`, `run_mav_multi.py`, `run_dex_cex.py`, `scan_dex_intrachain.py`
- Backfills on-chain : `backfill.py`, `backfill_intrachain.py`, `backfill_v3.py`
- Historique cross-chain / settle : `settle_dex_cex.py`, `settle_crosschain.py`
- Triage : `crosschain_triage.py`
- Portes d'intégrité : `verify_data.py`, `checks.py`

### Recherches PONCTUELLES / expérimentales / utilitaires
- Diagnostics one-off : `diag_pair.py`, `spot_check.py`, `capture_cost.py`, `verify_crosschain.py`
- Sondes / setup : `archive_probe.py`, `set_key.py`, `set_rpc.py`
- Infra transverse : `archive_rpc.py` (endpoints archive), `manifest.py` (manifeste obligatoire)

### Données — 4 niveaux (actuellement mélangés dans `data/logs/`)
| Niveau | Exemples | Où aujourd'hui |
|---|---|---|
| **BRUT** (live, indicatif) | `crosschain_obs.csv`, `scan_*`, `mav_*`, `dex_cex_*`, `intrachain_*`, `backtest_gap.csv` | `data/collected/`, `data/logs/` |
| **DÉRIVÉ FIABLE** (exact au bloc) | `backfill_intrachain_*.csv`, `backfill_v3_*.csv`, `settle_*.csv`, `funding_regime.csv` | `data/logs/`, `data/historical/` |
| **QUARANTAINE** (invalide, conservé) | `cex_monitor.csv`, `crosschain_cand.csv` | `data/logs/`, `data/collected/` + `QUARANTINE.md` |
| **MANIFESTES** (donnée↔conclusion↔code) | tous les `manifest.json/.md` | `runs/` |

## B. Recommandation : OPTION 1 (zéro risque) — documenter, ne rien déplacer

La carte ci-dessus + les `QUARANTINE.md` existants rendent déjà tout **distingable** sans casser un seul import. Action unique :
- ajouter un **`data/README.md`** : table « fichier → niveau (brut/dérivé/quarantaine) → fiabilité → produit par quel script ».
- garder ce `TIDY_PLAN.md` comme carte de référence du code.

→ Lisibilité atteinte, **zéro déplacement, zéro risque de régression.** C'est ma recommandation pour respecter « minimal, sans refactor massif ».

## C. OPTION 2 (alignée sur ta directive « sim/ = pur », sur validation) — déplacements légers

Si tu veux la séparation physique stricte, à valider d'abord (chaque point = son coût) :
1. `sim/chain.py` + `sim/quote_v3.py` → `infra/` (réseau hors de `sim/`). **Coût** : mettre à jour ~12 imports `from sim.chain import …` dans les runners + `conftest`/`tests`. Mécanique, mais touche beaucoup de fichiers.
2. `experiments/` : y ranger les one-off (`diag_pair`, `spot_check`, `capture_cost`, `verify_crosschain`, `archive_probe`). **Coût** : faible (peu/pas importés ailleurs).
3. `data/` en 4 sous-dossiers (`raw/`, `derived/`, `quarantine/`, et `runs/` déjà à part). **Coût** : mettre à jour les chemins de sortie dans ~8 runners + re-pointer le collecteur (qui tourne) → **risqué pour la collecte live**, à faire à froid.

→ Plus « propre » mais c'est un vrai chantier d'imports/chemins. **À ne lancer que si tu le valides explicitement**, point par point.

## D. Ce que je NE fais pas (gel confirmé)
Aucune Phase 2 cross-chain, aucun `basis_eval`, aucun executor, aucun élargissement d'univers, aucune suppression. Après validation de ce plan + lecture de `STATE.md`, on choisit **ensemble** l'unique test simple (un actif, deux venues, quotes $1k/$5k/$10k, une période, la formule de `STATE.md`).
