# arb — observatoire d'arbitrage crypto (sous-projet)

Sous-projet **isolé** de Mercor (venv propre, dépendances propres). Rupture assumée avec
l'ADN Mercor : ici on est en **live / exécution / microstructure**, pas en backtest
no-lookahead. La discipline transférée reste la même : **brut ≠ net**, *quel risque suis-je
payé pour absorber*, et on **mesure avant de croire**.

## État : phase 0 — OBSERVATOIRE (lecture seule, zéro capital, zéro clé privée)

Avant tout bot qui exécute, on mesure la surface d'opportunité. `scan_dex_gaps.py` lit
le prix mid de **WETH/USDC** sur plusieurs DEX d'une même chaîne (**Base**) et logue :

- le **gap brut** entre venues (bps) ;
- le **gap net des frais de pool** (condition *nécessaire*, pré-slippage / pré-gas) ;
- surtout la **persistance** du gap (combien de temps il survit) — le chiffre qui tranche
  entre « capturable par un solo » et « déjà mangé par les bots MEV » (mort en 1 bloc).

Aucune transaction, aucune clé privée, aucun capital engagé. RPC public en lecture seule.

## Usage
```bash
.venv/Scripts/python.exe scan_dex_gaps.py --seconds 90 --interval 2.5
```

## Ce que ça ne fait PAS (encore)
- Pas de slippage-pour-taille (prix mid seulement ; le quoter on-chain viendra après).
- Pas de proxy de concurrence MEV fin (mempool/bundles) — la persistance sert de proxy v1.
- Pas d'exécution. C'est un capteur.

## Structure (rangement Option 1 — documenter, ne **rien** déplacer)

Actuel (à plat, voir [`docs/TIDY_PLAN.md`](docs/TIDY_PLAN.md)) :

- `sim/` — modules **purs/testables** : math AMM (`amm_v2*`), routing (`route_*`), identité
  (`identity.py`, `economic_identity.py`), **contrats de données** (`contracts.py`), RPC/chaîne (`chain.py`).
- `*.py` (racine) — runners CLI : `scan_*`, `backfill_*`, `settle_*`, `run_*`, `verify_*`, `manifest.py`.
- `config/` — univers certifié par adresse (`universe_base.json`), **registre d'identité économique**
  (`economic_identity.json`).
- `data/` — `raw`/`logs`/`historical`/`collected` (brut non versionné) ; `runs/` — manifests ;
  `docs/` — état & doctrine ; `tests/` — pytest.

Cible **aspirationnelle** (`core/ infra/ research/ runners/ …`, MISSION RESET §1) : **non mise en
place** — migration fichier par fichier, tests verts à chaque pas, jamais avant un état de référence
testé (§1.10). Boussole de vérité : [`docs/EVIDENCE_LEDGER.md`](docs/EVIDENCE_LEDGER.md) ·
mécanismes : [`docs/MECHANISM_MAP.md`](docs/MECHANISM_MAP.md) · décisions : [`docs/DECISIONS.md`](docs/DECISIONS.md).
