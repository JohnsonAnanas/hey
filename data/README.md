# data/ — carte des niveaux (rangement Option 1, lecture seule)

> Les données brutes ne sont PAS versionnées (.gitignore) ; seuls ce README et les `QUARANTINE.md` le
> sont. Niveaux : **BRUT** (live, indicatif) · **DÉRIVÉ FIABLE** (exact au bloc, archive, manifesté) ·
> **QUARANTAINE** (invalide, conservé pour re-test) · **MANIFESTE** (donnée↔conclusion↔code).
> Règle d'or (leçon CBBTC) : un chiffre BRUT/INDICATIF doit être **confirmé en live/exécutable** avant
> toute conclusion. Cf [`../docs/STATE.md`](../docs/STATE.md).
>
> **Lecture des colonnes (§3) :** *niveau de fiabilité* = la **section** (DÉRIVÉ FIABLE / BRUT /
> QUARANTAINE) ; *producteur* = colonne « Produit par » ; *période* = dans le run/manifest qui a
> produit le fichier (`runs/**`, champ `period`) ; *statut de la claim* = `../docs/EVIDENCE_LEDGER.md`
> (un fichier de données n'est pas une conclusion — l'Evidence Ledger fait foi pour le verdict).

## DÉRIVÉ FIABLE — exact au bloc, reproductible (à privilégier pour conclure)
| Fichier | Contenu | Produit par |
|---|---|---|
| `historical/settle_crosschain_velvet.csv` | basis VELVET base↔bsc, horaire 14j (aligné au bloc) — ⚠️ identité VELVET **non prouvée** (adresses ≠) | `settle_crosschain.py` |
| `historical/settle_dex_cex.csv` | basis ETH DEX↔CEX réglé (7j) | `settle_dex_cex.py` |
| `historical/base_d0b53d92.csv` | prix historique d'un pool Base | `backfill.py` |
| `logs/backfill_intrachain_*.csv` | MAV-net v2 intra-chaîne au bloc passé | `backfill_intrachain.py` |
| `logs/backfill_v3_*.csv` | routes v3 quotées exactes au bloc passé | `backfill_v3.py` |
| `logs/funding_regime.csv` | funding annualisé, 1 an quotidien — ⚠️ plafond suspect ~10,9 % à vérifier | `funding_regime.py` |

## BRUT / INDICATIF — live, court, agrégé ou mid (NE PAS conclure sans confirmation)
| Fichier | Contenu | Produit par |
|---|---|---|
| `collected/crosschain_obs.csv` | prix/liq/vol agrégés GeckoTerminal, ~20 min (append-only) | `collector.py` |
| `collected/crosschain_cand.v2.csv` | candidats cross-chain avec `lo_addr/hi_addr/identity` | `collector.py` |
| `logs/intrachain_*.csv` | snapshots live route v3/v2 (minutes) | `scan_dex_intrachain.py` |
| `logs/scan_weth_usdc_base.csv` | gaps mid WETH/USDC Base (live) | `scan_dex_gaps.py` |
| `logs/mav_multi_base.csv`, `logs/mav_sim_base.csv` | scans MAV live (courts) | `run_mav_multi.py`, `run_mav_sim.py` |
| `logs/dex_cex_eth.csv`, `logs/dex_cex_multi.csv` | basis DEX↔CEX live (mid) | `run_dex_cex.py` |
| `logs/backtest_gap.csv` | backtest gap minute (net opt/floor — dépend du modèle de coût) | `backtest_gap.py` |
| `collected/collector.log`, `collected/launcher.log`, `logs/dex_cex_run.log` | journaux | (runners) |

## QUARANTAINE — INVALIDE, conservé (ne RIEN conclure) — voir les `QUARANTINE.md`
| Fichier | Pourquoi invalide | Marqueur |
|---|---|---|
| `logs/cex_monitor.csv` | « $20M » fantômes = identité par ticker (HYPE 2-sens) | `logs/QUARANTINE.md` |
| `collected/crosschain_cand.csv` | ancien schéma identité-aveugle (sans adresse) | `collected/QUARANTINE.md` |

## MANIFESTES — donnée↔conclusion↔code (versionnés)
`../runs/<UTC>_<slug>/manifest.{json,md}` — un par run, avec hash de sortie, plage de blocs, params,
verdict scopé. Produits par `manifest.py` (`write_manifest`). Cf [`run_manifest_standard.md`](../docs/run_manifest_standard.md).

## Config (versionnée, hors data/)
`../config/universe_base.json` — univers certifié **par adresse** (decimals, source, date).
