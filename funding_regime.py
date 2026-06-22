#!/usr/bin/env python
"""Observatoire de REGIME de funding — detecter la fenetre de RECOLTE (structure d'abord).

Le carry de funding est ~sans-risque en regime calme, GRAS seulement quand le regime chauffe
(euphorie : funding large + eleve + persistant). Cet outil CALIBRE le regime sur l'historique
(~1 an, pagine) : il construit un indicateur de regime market-wide JOUR par JOUR, identifie les
FENETRES CHAUDES passees (quand, combien de temps, quel carry on aurait recolte), et situe
MAINTENANT dans cette distribution -> verdict RECOLTE / CALME.

Indicateur de regime (par jour, sur le panier) :
  - best_carry(actif, jour) = max sur exchanges du funding moyen du jour, annualise (le cash-and-carry
    se fait la ou le funding est le plus haut : on short le perp, on recoit).
  - NIVEAU  = mediane des best_carry sur le panier (le carry "du milieu").
  - AMPLEUR = fraction d'actifs dont best_carry > HOT_PCT/an (combien de noms sont chauds).
  - P90     = 90e percentile des best_carry (ce que paient les noms les plus gras).
Seuil "chaud" AUTO-CALIBRE : 80e percentile du NIVEAU sur la fenetre (le regime est relatif a sa
propre histoire, pas a un chiffre code en dur).

Structure d'abord : on PROUVE que les regimes gras existent (frequence/duree/ampleur) AVANT de
pretendre les recolter. HONNETE : mesure l'opportunite (carry brut) ; le PnL capture (inventaire,
liquidation du short, basis, risque exchange) reste un test forward.

Usage : python funding_regime.py --days 365 --hot 15
"""
from __future__ import annotations

import argparse
import csv
import os
import statistics
import sys
import time
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scan_cex import make_exchange

EXCHANGES = ["binance", "okx"]
BASKET = ["BTC", "ETH", "SOL", "XRP", "DOGE", "LINK", "AVAX", "ADA", "SUI", "AAVE",
          "TIA", "APT", "NEAR", "LTC", "ARB", "OP", "INJ", "SEI", "DYDX", "PEPE", "WIF", "ENA"]


def interval_hours(ts_sorted: list) -> float:
    if len(ts_sorted) >= 3:
        diffs = sorted(ts_sorted[i + 1] - ts_sorted[i] for i in range(len(ts_sorted) - 1))
        h = diffs[len(diffs) // 2] / 3_600_000.0
        if 0.5 <= h <= 24:
            return round(h) or 1
    return 8.0


def fetch_history(c, sym: str, since: int, now_ms: int, max_pages: int = 80) -> list:
    """Pagine fetch_funding_rate_history depuis `since` jusqu'a maintenant. Dedup par timestamp."""
    seen = {}
    cur = since
    for _ in range(max_pages):
        try:
            batch = c.fetch_funding_rate_history(sym, since=cur, limit=1000)
        except Exception:
            break
        batch = [h for h in batch if h.get("timestamp") and h.get("fundingRate") is not None]
        new = [h for h in batch if h["timestamp"] >= cur and h["timestamp"] not in seen]
        if not new:
            break
        for h in new:
            seen[h["timestamp"]] = h
        last = max(h["timestamp"] for h in new)
        if last <= cur or last >= now_ms:
            break
        cur = last + 1
        time.sleep(0.1)
    return sorted(seen.values(), key=lambda h: h["timestamp"])


def percentile(sorted_vals: list, q: float) -> float:
    if not sorted_vals:
        return 0.0
    i = min(len(sorted_vals) - 1, max(0, int(round(q / 100.0 * (len(sorted_vals) - 1)))))
    return sorted_vals[i]


def day_of(ts_ms: int) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(ts_ms / 1000.0))


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="Observatoire de regime de funding (calibration historique).")
    ap.add_argument("--days", type=float, default=365.0)
    ap.add_argument("--hot", type=float, default=15.0, help="seuil 'actif chaud' en %%/an (pour l'ampleur)")
    args = ap.parse_args()
    now_ms = int(time.time() * 1000)
    since = int(now_ms - args.days * 86400 * 1000)

    # (asset, date) -> {ex: [annualized...]}  puis on prend la moyenne du jour par ex
    daily = defaultdict(lambda: defaultdict(list))   # asset -> date -> list (best-of-ex pris plus tard)
    perex = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))  # asset -> date -> ex -> [ann]
    for ex in EXCHANGES:
        try:
            c = make_exchange(ex); c.load_markets()
        except Exception as e:
            print(f"{ex} init KO: {e}"); continue
        got = 0
        for coin in BASKET:
            sym = f"{coin}/USDT:USDT"
            if sym not in c.markets:
                continue
            hist = fetch_history(c, sym, since, now_ms)
            if len(hist) < 20:
                continue
            ts = sorted(h["timestamp"] for h in hist)
            per_year = 8760.0 / interval_hours(ts)
            for h in hist:
                ann = h["fundingRate"] * per_year * 100
                perex[coin][day_of(h["timestamp"])][ex].append(ann)
            got += 1
        print(f"  {ex:<8} : {got}/{len(BASKET)} actifs, historique ~{args.days:.0f}j pagine")

    # best_carry(asset, day) = max sur ex de la moyenne du jour
    for coin, days in perex.items():
        for d, exmap in days.items():
            best = max(statistics.mean(v) for v in exmap.values() if v)
            daily[coin][d] = best

    # regime par jour : niveau (mediane), ampleur (frac > hot), p90 ; n actifs ce jour
    all_days = sorted({d for days in daily.values() for d in days})
    series = []  # (date, level, breadth, p90, n)
    for d in all_days:
        vals = sorted(daily[coin][d] for coin in daily if d in daily[coin])
        if len(vals) < 5:
            continue
        level = statistics.median(vals)
        breadth = sum(1 for x in vals if x > args.hot) / len(vals)
        series.append((d, level, breadth, percentile(vals, 90), len(vals)))

    if not series:
        print("Pas assez d'historique."); return 1

    levels = sorted(s[1] for s in series)
    hot_thr = percentile(levels, 80)   # seuil chaud auto-calibre (80e pct du niveau)

    # fenetres chaudes : jours contigus (tolerance 2 jours de trou) ou level >= hot_thr
    hot_days = [s for s in series if s[1] >= hot_thr]
    windows = []
    if hot_days:
        idx = {s[0]: i for i, s in enumerate(series)}
        cur = [hot_days[0]]
        for prev, nxt in zip(hot_days, hot_days[1:]):
            if idx[nxt[0]] - idx[prev[0]] <= 3:
                cur.append(nxt)
            else:
                windows.append(cur); cur = [nxt]
        windows.append(cur)

    # ecriture CSV de la serie (reutilisable par un moniteur live)
    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "logs")
    os.makedirs(out_dir, exist_ok=True)
    csv_path = os.path.join(out_dir, "funding_regime.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["date", "level_pct_an", "breadth", "p90_pct_an", "n_assets"])
        for d, lv, br, p9, n in series:
            w.writerow([d, f"{lv:.2f}", f"{br:.3f}", f"{p9:.2f}", n])

    # table mensuelle
    months = defaultdict(list)
    for d, lv, br, p9, n in series:
        months[d[:7]].append((lv, br, p9))
    print("\n" + "=" * 78)
    print(f"REGIME DE FUNDING — {len(series)} jours ({all_days[0]} -> {all_days[-1]}), "
          f"seuil chaud auto = niveau >= {hot_thr:.1f}%/an (80e pct)")
    print(f"\nPar mois : niveau median du carry (mediane/max), ampleur moy (frac actifs > {args.hot:.0f}%/an) :")
    print(f"  {'mois':<9}{'niveau med':>11}{'niveau max':>11}{'ampleur':>9}{'p90 max':>9}")
    for m in sorted(months):
        lvs = [x[0] for x in months[m]]; brs = [x[1] for x in months[m]]; p9s = [x[2] for x in months[m]]
        print(f"  {m:<9}{statistics.median(lvs):>+10.1f}%{max(lvs):>+10.1f}%{statistics.mean(brs):>8.0%}{max(p9s):>+8.0f}%")

    print(f"\nDistribution du NIVEAU (carry median, %/an) : "
          f"p50={percentile(levels,50):+.1f}  p75={percentile(levels,75):+.1f}  "
          f"p90={percentile(levels,90):+.1f}  p95={percentile(levels,95):+.1f}  max={levels[-1]:+.1f}")

    print(f"\nFENETRES CHAUDES passees (niveau >= {hot_thr:.1f}%/an) — la ou la recolte valait le coup :")
    if not windows:
        print("  Aucune. Le funding n'a jamais ete largement gras sur la fenetre -> these a revoir.")
    for win in sorted(windows, key=lambda wd: -max(s[1] for s in wd))[:8]:
        peak = max(s[1] for s in win); p90peak = max(s[3] for s in win)
        print(f"  {win[0][0]} -> {win[-1][0]}  ({len(win):>3}j)  niveau pic {peak:+.0f}%/an  "
              f"| meilleurs noms ~{p90peak:+.0f}%/an")

    # ou en est-on MAINTENANT (7 derniers jours)
    last7 = series[-7:]
    cur_level = statistics.mean(s[1] for s in last7)
    cur_breadth = statistics.mean(s[2] for s in last7)
    pct_now = 100 * sum(1 for x in levels if x <= cur_level) / len(levels)
    verdict = "RECOLTE (regime chaud)" if cur_level >= hot_thr else "CALME (rester en veille)"
    print(f"\nMAINTENANT (7 derniers jours) : niveau {cur_level:+.1f}%/an (percentile {pct_now:.0f} de l'annee), "
          f"ampleur {cur_breadth:.0%}")
    print(f"  -> VERDICT : {verdict}")
    print(f"\nSerie quotidienne -> {csv_path}")
    print("Lecture : des fenetres chaudes existent ET sont grasses -> la these 'recolter quand ca chauffe'")
    print("tient, et ce verdict dit quand. Aucune fenetre / toujours ~5% -> these morte, on acte.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
