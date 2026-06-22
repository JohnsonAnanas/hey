# QUARANTAINE — sorties INVALIDES (ne RIEN conclure de ces fichiers)

> Marqueur loud (charte d'intégrité : *échouer fort / abstention loggée + motif*). La donnée brute
> est **conservée** (append-only, re-testable une fois l'identité câblée), mais elle est **INVALIDE**
> en l'état. Date : **2026-06-22**. Fix : [`../../sim/identity.py`](../../sim/identity.py) +
> [`../../tests/test_identity.py`](../../tests/test_identity.py).

## `cex_monitor.csv` — INVALIDE (profits CEX↔CEX fantômes)

**Bug de classe : appariement par TICKER.** `cex_monitor.py` groupait `assets[coin][ex]` par ticker
et marchait les carnets de deux venues comme si « HYPE » désignait le même actif/échelle partout.

Reçus (falsifiables en une ligne) :

- `HYPE htx→okx = $20 622 911` (net **5,6 bps**) **ET** `HYPE okx→htx = $20 600 813` (net **0,6 bps**).
  Le **même actif profitable dans les deux sens** est impossible ; 0,6 bps ne peut pas rendre $20M.
- **3352 lignes sur 3363** ont `extract_usd ≥ $1M`. Ce ne sont pas des outliers : *quasiment chaque
  candidat retenu* est une fantaisie (familles HYPE, MEGA, TRX, XAUT…).
- `net_bps` (tickers) restait sain (0–116 bps) ; c'est `extract_usd` (walk de carnet) qui explosait
  → défaut de **valorisation/identité**, pas de détection de spread.

**Remplacé par** : `cex_monitor.py` passe désormais par `sim.identity.cex_extractable_guarded`
(abstention si profitable 2-sens / divergence d'échelle / magnitude > $1M sur 20 niveaux). Les
abstentions sont loggées dans `cex_monitor_abstain_<stamp>.csv`. Les nouveaux runs écrivent
`cex_monitor_<stamp>.csv` (jamais ce fichier-ci).

## Non concernés (mono-actif, pas ce bug)

`dex_cex_eth.csv`, `dex_cex_multi.csv`, `backtest_gap.csv` = basis **même actif** (ETH/BTC/VIRTUAL
vs Binance) — pas d'appariement inter-actifs. Conclusion DEX↔CEX majors (med ~−11 bps, actionable 0%)
**reste valide**.
