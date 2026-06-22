#!/usr/bin/env python
"""Diagnostic anti-lissage : le funding a-t-il VRAIMENT ete gras quelque part cette annee ?

Le regime market-wide (mediane de panier) est reste ~baseline tout l'an -> SUSPECT : deux moyennages
(moyenne du jour + mediane du panier) ecrasent les spikes par actif. Or la strategie recolte un NOM
precis quand il chauffe, pas le panier. Ici on regarde PAR ACTIF, sans mediane de panier :
  - max funding sur UNE periode (annualise) — le spike brut (non harvestable seul, mais diagnostic) ;
  - meilleur carry SOUTENU : moyenne glissante 7j et 21j la plus haute (ca, c'est harvestable) ;
  - nb de jours ou le carry de l'actif a depasse 20/40 %%/an.
Si meme les fenetres soutenues restent < ~15%%/an -> l'annee fut maigre, these faible. Si des noms
ont tenu 30-60%%/an une semaine+ -> les fenetres existent, mais PAR ACTIF (le bon metrique).

Usage : python funding_extremes.py --days 365
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
from funding_regime import interval_hours, fetch_history, day_of

EXCHANGES = ["binance", "okx"]
BASKET = ["BTC", "ETH", "SOL", "XRP", "DOGE", "LINK", "AVAX", "ADA", "SUI", "AAVE",
          "TIA", "APT", "NEAR", "LTC", "ARB", "OP", "INJ", "SEI", "DYDX", "PEPE", "WIF", "ENA"]


def best_rolling(daily_sorted: list, win: int):
    """(meilleure moyenne glissante sur `win` jours, date de fin). daily_sorted = [(date, ann)...]."""
    if len(daily_sorted) < win:
        return (None, None)
    best, best_end = None, None
    vals = [v for _, v in daily_sorted]
    for i in range(len(vals) - win + 1):
        m = sum(vals[i:i + win]) / win
        if best is None or m > best:
            best, best_end = m, daily_sorted[i + win - 1][0]
    return (best, best_end)


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="Extremes de funding par actif (verif anti-lissage).")
    ap.add_argument("--days", type=float, default=365.0)
    args = ap.parse_args()
    now_ms = int(time.time() * 1000)
    since = int(now_ms - args.days * 86400 * 1000)

    rows = []          # (best7, best21, max_period, d20, d40, coin, ex, when7)
    global_spikes = [] # (ann, coin, ex, date) periode brute
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
            if len(hist) < 30:
                continue
            ts = sorted(h["timestamp"] for h in hist)
            per_year = 8760.0 / interval_hours(ts)
            # periodes brutes annualisees + serie quotidienne (moyenne du jour)
            byday = defaultdict(list)
            for h in hist:
                ann = h["fundingRate"] * per_year * 100
                byday[day_of(h["timestamp"])].append(ann)
                global_spikes.append((ann, coin, ex, day_of(h["timestamp"])))
            daily = sorted((d, statistics.mean(v)) for d, v in byday.items())
            b7, w7 = best_rolling(daily, 7)
            b21, _ = best_rolling(daily, 21)
            max_p = max(a for a, *_ in [(v,) for _, v in daily])
            d20 = sum(1 for _, v in daily if v > 20)
            d40 = sum(1 for _, v in daily if v > 40)
            rows.append((b7 or 0, b21 or 0, max_p, d20, d40, coin, ex, w7))
            got += 1
        print(f"  {ex:<8} : {got} actifs analyses")

    rows.sort(reverse=True)
    global_spikes.sort(reverse=True)
    print("\n" + "=" * 84)
    print(f"EXTREMES DE FUNDING PAR ACTIF — {args.days:.0f}j. 'soutenu' = meilleure moyenne glissante.")
    print("Le carry HARVESTABLE = le soutenu (7j/21j), pas le spike d'une periode.\n")
    print(f"  {'actif':<7}{'exch':<9}{'best 7j':>9}{'best 21j':>10}{'max 1per':>10}{'j>20%':>7}{'j>40%':>7}  fin 7j")
    for b7, b21, mx, d20, d40, coin, ex, w7 in rows[:18]:
        print(f"  {coin:<7}{ex:<9}{b7:>+8.0f}%{b21:>+9.0f}%{mx:>+9.0f}%{d20:>7}{d40:>7}  {w7 or '-'}")

    print("\nTop 10 spikes BRUTS (une periode, annualise — non harvestable seul, juste pour l'ampleur) :")
    for ann, coin, ex, d in global_spikes[:10]:
        print(f"  {coin:<7}{ex:<9}{ann:>+8.0f}%/an  {d}")

    best7_overall = max(r[0] for r in rows) if rows else 0
    print(f"\nVERDICT : meilleur carry SOUTENU 7j de l'annee, tous noms confondus = {best7_overall:+.0f}%/an.")
    print("  > ~30%/an -> des fenetres grasses par actif existent (cibler le nom, pas le panier).")
    print("  < ~15%/an -> meme les extremes furent maigres : l'edge funding est structurellement faible")
    print("  sur cette periode, la these 'recolter quand ca chauffe' ne paie pas assez. On acte.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
