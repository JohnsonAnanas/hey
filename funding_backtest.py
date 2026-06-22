#!/usr/bin/env python
"""Backtest du CARRY de funding (HISTORIQUE) — la seule vraie piste solo (structurel, inventaire).

Pour un panier d'actifs x {binance, okx} : recupere l'HISTORIQUE des funding rates (perp) sur N
jours (`fetch_funding_rate_history`), **annualise correctement** (intervalle reel deduit des
timestamps), et caracterise le carry PERSISTANT (moyenne, mediane, %positif, stabilite). Deux jeux :

  - CASH-AND-CARRY : long spot + short perp -> on encaisse le funding POSITIF (delta-neutre).
    Carry annualise = funding moyen (on est SHORT le perp -> on recoit quand funding > 0).
  - ECART CROSS-EXCHANGE : long le perp ou le funding est BAS / short ou il est HAUT (delta-neutre)
    -> on encaisse le DIFFERENTIEL moyen.

Structure d'abord : on mesure DANS LE TEMPS (un snapshot annualise ment : le funding revient a la
moyenne chaque periode). HONNETE : ceci mesure l'OPPORTUNITE (le carry brut), pas le PnL capture
(inventaire, liquidation du leg short, basis, risque d'exchange -> test forward/live).

Usage : python funding_backtest.py --days 30
"""
from __future__ import annotations

import argparse
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
ROUND_TRIP_FEE_BPS = 8.0   # entree+sortie (spot+perp, taker) ~ one-time, amorti sur la duree de hold


def interval_hours(hist: list) -> float:
    """Intervalle de funding (h) deduit de l'espacement median des timestamps. Defaut 8h."""
    ts = sorted(h["timestamp"] for h in hist if h.get("timestamp"))
    if len(ts) >= 3:
        diffs = sorted(ts[i + 1] - ts[i] for i in range(len(ts) - 1))
        med = diffs[len(diffs) // 2]
        h = med / 3_600_000.0
        if 0.5 <= h <= 24:
            return round(h) or 1
    return 8.0


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="Backtest du carry de funding (historique).")
    ap.add_argument("--days", type=float, default=30.0)
    args = ap.parse_args()
    since = int((time.time() - args.days * 86400) * 1000)

    # asset -> ex -> list[annualized %]
    ann = defaultdict(dict)
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
            try:
                hist = c.fetch_funding_rate_history(sym, since=since, limit=500)
            except Exception:
                continue
            hist = [h for h in hist if h.get("fundingRate") is not None]
            if len(hist) < 5:
                continue
            per_year = 8760.0 / interval_hours(hist)
            ann[coin][ex] = [h["fundingRate"] * per_year * 100 for h in hist]
            got += 1
            time.sleep(0.15)
        print(f"  {ex:<8} : {got} actifs avec historique funding")

    # CASH-AND-CARRY : par actif, meilleur exchange (funding moyen le plus haut = on short le perp la)
    cc = []
    for coin, exmap in ann.items():
        for ex, vals in exmap.items():
            m = statistics.mean(vals)
            pos = 100 * sum(1 for x in vals if x > 0) / len(vals)
            sd = statistics.pstdev(vals) if len(vals) > 1 else 0.0
            cc.append((m, coin, ex, pos, sd, len(vals)))
    cc.sort(reverse=True)

    # ECART CROSS-EXCHANGE : actifs presents sur les 2 -> differentiel des moyennes
    xx = []
    for coin, exmap in ann.items():
        if len(exmap) < 2:
            continue
        means = {ex: statistics.mean(v) for ex, v in exmap.items()}
        hi = max(means, key=means.get); lo = min(means, key=means.get)
        xx.append((means[hi] - means[lo], coin, hi, lo, means[hi], means[lo]))
    xx.sort(reverse=True)

    fee_drag = ROUND_TRIP_FEE_BPS / 100.0 * (365.0 / args.days)   # frais one-time amortis sur la fenetre, en %/an
    print("\n" + "=" * 84)
    print(f"BACKTEST CARRY DE FUNDING — {args.days:.0f} jours (frais one-time ~{ROUND_TRIP_FEE_BPS:.0f}bps "
          f"-> drag ~{fee_drag:.1f}%/an si tenu {args.days:.0f}j)")
    print("\nCASH-AND-CARRY (long spot + short perp ; carry = funding moyen annualise) — top 12 :")
    print(f"  {'actif':<7}{'exch':<9}{'carry brut':>11}{'net frais':>11}{'%positif':>9}{'stabilite(sd)':>14}{'n':>5}")
    for m, coin, ex, pos, sd, n in cc[:12]:
        print(f"  {coin:<7}{ex:<9}{m:>+10.1f}%{m - fee_drag:>+10.1f}%{pos:>8.0f}%{sd:>13.0f}{n:>5}")
    print("\nECART CROSS-EXCHANGE (long le bas / short le haut ; carry = differentiel moyen) — top 10 :")
    print(f"  {'actif':<7}{'short@':<9}{'long@':<9}{'differentiel':>13}")
    for diff, coin, hi, lo, mhi, mlo in xx[:10]:
        print(f"  {coin:<7}{hi:<9}{lo:<9}{diff:>+12.1f}%/an")
    print("\nLecture : carry PERSISTANT (moyenne sur la fenetre) + '%positif' eleve + 'sd' faible = vrai")
    print("candidat. Snapshot enorme mais sd enorme = transitoire (revient a la moyenne). Net = carry -")
    print("drag de frais ; RESTE a soustraire le cout d'inventaire/capital et le risque (liquidation/basis/")
    print("exchange) -> ca, c'est le test FORWARD. Opportunite, pas PnL capture.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
