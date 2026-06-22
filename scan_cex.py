#!/usr/bin/env python
"""Filet large CEX<->CEX (ccxt) — chercher le meme actif a deux prix sur deux exchanges.

Pour BEAUCOUP d'exchanges x BEAUCOUP de coins (paires /USDT), on recupere les carnets (bid/ask) en
un appel par exchange (fetch_tickers, public, sans cle), on cross-compare chaque actif present sur
>=2 exchanges, et on classe les plus gros GAPS NETS (apres taker 2x). But : reperer "ce qui ne
devrait pas arriver".

STRUCTURE D'ABORD : filtre d'integrite pour ne PAS confondre une faille avec un artefact :
  - volume 24h >= MIN_VOL sur LES DEUX jambes (anti pair morte/stale/manipulable) ;
  - bid/ask (pas le 'last' qui peut etre vieux) ;
  - present sur >=2 exchanges reputes (anti meme-ticker-autre-actif).
Caveat assume : CEX<->CEX n'est pas atomique -> inventaire des deux cotes (ou transfert = frais+delai) ;
le gap net de frais de trading est NECESSAIRE, pas suffisant. Ceci SCREENE des candidats a verifier.

Usage : python scan_cex.py --min-vol 1000000 --top 30
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from collections import defaultdict

import ccxt
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))   # cles CEX, jamais committe

EXCHANGES = ["binance", "okx", "bybit", "kucoin", "gateio", "mexc", "bitget", "kraken", "htx", "cryptocom"]
TAKER = 0.0010   # ~10 bps par cote (ordre de grandeur ; varie par exchange/VIP)


def make_exchange(name: str):
    """Instancie un exchange ccxt avec les cles READ-ONLY de .env si presentes, sinon en public.

    Variables : <NAME>_API_KEY, <NAME>_SECRET, et <NAME>_PASSWORD si l'exchange l'exige.
    Les cles ne sont JAMAIS loggees ni affichees.
    """
    u = name.upper()
    cfg = {"enableRateLimit": True, "timeout": 20000}
    key, sec, pwd = os.environ.get(f"{u}_API_KEY"), os.environ.get(f"{u}_SECRET"), os.environ.get(f"{u}_PASSWORD")
    if key and sec:
        cfg["apiKey"], cfg["secret"] = key, sec
        if pwd:
            cfg["password"] = pwd
    cls = os.environ.get(f"{u}_CCXT", name)   # entite ccxt alternative (ex. OKX_CCXT=myokx pour OKX EEA/Europe)
    return getattr(ccxt, cls)(cfg)


def fetch_one(name: str) -> dict:
    """{base: (bid, ask, quoteVolume)} pour les paires /USDT d'un exchange. {} si echec."""
    try:
        ex = make_exchange(name)
        tickers = ex.fetch_tickers()
    except Exception as e:
        print(f"  [skip] {name} : {type(e).__name__}", file=sys.stderr)
        return {}
    out = {}
    for sym, t in tickers.items():
        if not sym.endswith("/USDT"):
            continue
        bid, ask, qv = t.get("bid"), t.get("ask"), t.get("quoteVolume")
        if bid and ask and ask > 0 and bid > 0:
            out[sym.split("/")[0]] = (float(bid), float(ask), float(qv or 0))
    return out


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="Filet large CEX<->CEX (ccxt).")
    ap.add_argument("--min-vol", type=float, default=1_000_000.0, help="volume 24h min (USDT) par jambe")
    ap.add_argument("--top", type=int, default=30)
    args = ap.parse_args()

    print(f"Scan CEX<->CEX | {len(EXCHANGES)} exchanges | filtre volume >= ${args.min_vol:,.0f}/24h | taker {TAKER*1e4:.0f}bps x2\n")
    books = {}
    for name in EXCHANGES:
        t0 = time.time()
        d = fetch_one(name)
        if d:
            books[name] = d
            print(f"  {name:<12} {len(d):>5} paires /USDT  ({time.time()-t0:.1f}s)")
    if len(books) < 2:
        print("Moins de 2 exchanges -> rien a comparer.", file=sys.stderr)
        return 1

    # base -> {exchange: (bid, ask, vol)}
    assets = defaultdict(dict)
    for ex, d in books.items():
        for base, v in d.items():
            assets[base][ex] = v

    results = []
    for base, exmap in assets.items():
        legs = [(ex, b, a, vol) for ex, (b, a, vol) in exmap.items() if vol >= args.min_vol]
        if len(legs) < 2:
            continue
        best = None
        for e1, b1, a1, v1 in legs:
            for e2, b2, a2, v2 in legs:
                if e1 == e2:
                    continue
                net = b2 * (1 - TAKER) - a1 * (1 + TAKER)        # acheter sur e1 (ask), vendre sur e2 (bid)
                mid = (a1 + b2) / 2
                bps = net / mid * 1e4
                if best is None or bps > best[0]:
                    best = (bps, e1, e2, a1, b2, min(v1, v2), len(legs))
        if best:
            results.append((base, *best))
    results.sort(key=lambda r: -r[1])

    print(f"\n{'='*86}\nTOP {args.top} GAPS NETS CEX<->CEX (apres taker 2x ; volume min ${args.min_vol/1e6:.1f}M/jambe)")
    print(f"{'actif':<12}{'net bps':>9}  {'acheter@':<10}{'vendre@':<10}{'vol min':>12}  {'#ex':>4}")
    pos = [r for r in results if r[1] > 0]
    for base, bps, e1, e2, a1, b2, vmin, nex in results[:args.top]:
        flag = "  <<" if bps > 0 else ""
        print(f"{base:<12}{bps:>9.1f}  {e1:<10}{e2:<10}{vmin/1e6:>10.1f}M  {nex:>4}{flag}")
    print(f"\n{len(pos)} actifs avec gap NET > 0 (apres frais de trading) sur {len(results)} comparables.")
    print("Lecture : NET>0 = candidat 'ne devrait pas arriver' -> A VERIFIER (volume reel, meme actif,")
    print("persistance, transfert/inventaire). Un gros gap sur un seul coin obscur = suspect (artefact).")
    print("CEX<->CEX non atomique : il faut de l'inventaire des deux cotes (ou transfert = frais+delai).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
