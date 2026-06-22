#!/usr/bin/env python
"""Reglement PRECIS du gap ETH DEX<->CEX — backfill on-chain (EXACT au bloc) vs Binance, aligne par minute.

On avait laisse ce gap FLOU ("entre 0,1% et 4,8%, sans doute pres du bas") car le backtest close-vs-close
mentait (timing, spread, wrapper). Ici, propre : prix DEX reconstruit EXACT au bloc (pool Base UniV3
WETH/USDC 0.05%) + prix CEX Binance ETHUSDC (MEME quote USDC -> pas de basis USDT), alignes par MINUTE.
On epingle la vraie distribution du gap, net de frais (DEX 5bps + CEX 10bps). Residu de timing < 60s
(vs des heures en close-vs-close). => repond enfin : y a-t-il un edge ETH DEX<->CEX, oui ou non ?

Usage : python settle_dex_cex.py --days 7 --cadence-min 30
"""
from __future__ import annotations

import argparse
import csv
import os
import statistics
import sys
import time

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backfill import Caller, read_meta, price_at, BLOCK_TIME, HIST

POOL = "0xd0b53d9277642d899df5c87a3966a349a798f224"   # Base UniV3 WETH/USDC 0.05%
CHAIN, PTYPE = "base", "v3"
DEX_FEE_BPS, CEX_FEE_BPS = 5.0, 10.0
BINANCE = "https://api.binance.com/api/v3/klines"


def binance_klines(symbol: str, start_ms: int, end_ms: int) -> dict:
    """{open_time_sec: close} pour des bougies 1m de [start, end]."""
    out, cur = {}, start_ms
    while cur < end_ms:
        try:
            r = requests.get(BINANCE, params={"symbol": symbol, "interval": "1m", "startTime": cur,
                                              "endTime": end_ms, "limit": 1000}, timeout=20)
            ks = r.json()
        except Exception:
            break
        if not isinstance(ks, list) or not ks:
            break
        for k in ks:
            out[int(k[0]) // 1000] = float(k[4])
        nxt = ks[-1][0] + 60000
        if nxt <= cur:
            break
        cur = nxt
        time.sleep(0.2)
    return out


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="Reglement precis du gap ETH DEX<->CEX.")
    ap.add_argument("--days", type=float, default=7.0)
    ap.add_argument("--cadence-min", type=float, default=30.0)
    args = ap.parse_args()

    c = Caller(CHAIN)
    tip = c.tip()
    meta = read_meta(c, POOL)
    if not tip or not meta:
        print("DEX init KO."); return 1
    a0, a1, d0, d1 = meta
    bt = BLOCK_TIME[CHAIN]
    step = max(1, int(args.cadence_min * 60 / bt))
    start = max(1, tip - int(args.days * 86400 / bt))
    print(f"DEX Base UniV3 WETH/USDC | token0={a0[:10]}(d{d0}) token1={a1[:10]}(d{d1}) | "
          f"{args.days:.0f}j cadence {args.cadence_min:.0f}min")

    # 1) echantillonnage DEX (prix exact au bloc + timestamp)
    samples, blk = [], start
    while blk <= tip:
        p = price_at(c, POOL, PTYPE, d0, d1, blk)
        ts = c.block_ts(blk)
        if p and ts:
            samples.append((ts, p))
        blk += step
    if len(samples) < 10:
        print(f"trop peu d'echantillons DEX ({len(samples)})."); return 1
    print(f"  DEX : {len(samples)} echantillons ({time.strftime('%m-%d', time.gmtime(samples[0][0]))} "
          f"-> {time.strftime('%m-%d', time.gmtime(samples[-1][0]))})")

    # 2) Binance ETHUSDC 1m sur la fenetre
    kl = binance_klines("ETHUSDC", samples[0][0] * 1000, (samples[-1][0] + 120) * 1000)
    print(f"  CEX : {len(kl)} bougies Binance ETHUSDC 1m")

    # 3) alignement + gap net
    rows = []
    for ts, dex in samples:
        cex = kl.get((ts // 60) * 60)
        if not cex:
            continue
        mid = (dex + cex) / 2
        gap = (dex - cex) / mid * 1e4                 # >0 = DEX plus cher que CEX
        net = abs(gap) - DEX_FEE_BPS - CEX_FEE_BPS     # net actionnable (meilleur sens), apres frais
        rows.append((ts, dex, cex, gap, net))
    if len(rows) < 10:
        print(f"alignement trop maigre ({len(rows)})."); return 1

    os.makedirs(HIST, exist_ok=True)
    path = os.path.join(HIST, "settle_dex_cex.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["ts_unix", "iso_utc", "dex_eth_usdc", "cex_eth_usdc", "gap_bps", "net_bps"])
        for ts, dex, cex, gap, net in rows:
            w.writerow([ts, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts)),
                        f"{dex:.4f}", f"{cex:.4f}", f"{gap:+.2f}", f"{net:+.2f}"])

    gaps = [r[3] for r in rows]
    absg = sorted(abs(g) for g in gaps)
    nets = [r[4] for r in rows]
    act = [r for r in rows if r[4] > 0]
    # plus longue serie consecutive actionnable -> persistance
    longest = run = 0
    for r in rows:
        run = run + 1 if r[4] > 0 else 0
        longest = max(longest, run)

    def pct(s, q):
        return s[min(len(s) - 1, int(q / 100 * len(s)))]

    print("\n" + "=" * 78)
    print(f"REGLEMENT GAP ETH DEX<->CEX — {len(rows)} points alignes (frais DEX {DEX_FEE_BPS:.0f} + "
          f"CEX {CEX_FEE_BPS:.0f} = {DEX_FEE_BPS+CEX_FEE_BPS:.0f}bps)")
    print(f"  |gap| brut : median {pct(absg,50):.1f}  p90 {pct(absg,90):.1f}  p99 {pct(absg,99):.1f}  "
          f"max {absg[-1]:.1f} bps")
    print(f"  biais DEX vs CEX : median {statistics.median(gaps):+.1f} bps (signe = DEX plus cher si >0)")
    print(f"  ACTIONNABLE (net>0 apres frais) : {len(act)}/{len(rows)} = {100*len(act)/len(rows):.1f}% des points")
    if act:
        bn = sorted(r[4] for r in act)
        print(f"     net actionnable : median {pct(bn,50):.1f}  max {bn[-1]:.1f} bps  | "
              f"plus longue serie {longest} points consecutifs (~{longest*args.cadence_min:.0f}min)")
    print(f"\n  VERDICT : ", end="")
    if 100 * len(act) / len(rows) < 5:
        print(f"gap ETH DEX<->CEX < frais quasi tout le temps -> PAS d'edge ({100*len(act)/len(rows):.1f}% actionnable).")
    else:
        print(f"{100*len(act)/len(rows):.0f}% des points actionnables -> a creuser (taille/persistance/execution).")
    print(f"  Donnees precises (exact au bloc, quote USDC, residu <60s) -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
