#!/usr/bin/env python
"""Test PRECIS de la these CROSS-CHAIN — VELVET base vs bsc, backfill on-chain a TIMESTAMPS APPARIES.

Reconstruit le prix USD de VELVET sur 2 chaines, lues au MEME instant (bloc le plus proche d'une
grille de temps commune, tolerance serree) :
  base : VELVET/USDC                 (USDC ~ USD)
  bsc  : VELVET/WBNB x WBNB/USDT      (conversion via WBNB)
-> distribution de l'ecart cross-chain DANS LE TEMPS + PERSISTANCE, SANS pollution de lag (le piege
de l'alignement par heure : un pool mince retarde sur les mouvements -> faux gap).

HONNETE : meme un gap reel = capturer en inventaire VELVET sur 2 chaines (risque prix small-cap, pas
de perp pour hedger) + cout des legs. On mesure l'OPPORTUNITE, pas le PnL.

Usage : python settle_crosschain.py --days 14 --cadence-min 60 --tol-sec 120
"""
from __future__ import annotations

import argparse
import csv
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backfill import Caller, read_meta, price_at, est_block_time, block_at_time, BLOCK_TIME, HIST

# (chain, pool, type, token-cible dont on veut le prix). adresses lowercase.
BASE_VELVET = ("base", "0x6b0f53cbd9272d8117e9535fe25371dedf39a1be", "v3", "0xbf927b841994731c573bdf09ceb0c6b0aa887cdd")
BSC_VELVET  = ("bsc",  "0x5d2913a8ea284e486000177852c87ea4d64d03d6", "v3", "0x8b194370825e37b33373e74a41009161808c1488")
BSC_WBNB    = ("bsc",  "0x172fcd41e0913e95784454622d1c3724f546f849", "v3", "0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c")
COST_BPS = 20.0


def oriented(c: Caller, pool: str, ptype: str, meta, target: str, block):
    a0, a1, d0, d1 = meta
    p = price_at(c, pool, ptype, d0, d1, block)
    if p is None or p <= 0:
        return None
    return p if a0.lower() == target.lower() else 1.0 / p


class ChainCtx:
    def __init__(self, chain: str, cfgs: list):
        self.chain = chain
        self.cfgs = cfgs                       # [(pool, type, target)]
        self.c = Caller(chain)
        self.tip = self.c.tip()
        self.tip_ts = self.c.block_ts(self.tip) if self.tip else None
        self.bt = est_block_time(self.c, self.tip) or BLOCK_TIME[chain]
        self.metas = [read_meta(self.c, pool) for pool, _, _ in cfgs]
        if not self.tip or not self.tip_ts or any(m is None for m in self.metas):
            raise SystemExit(f"init/meta KO sur {chain}")

    def read_at(self, target_ts: int):
        """([prix orientes], ts du bloc lu) au plus proche de target_ts ; (None, ts) si une lecture echoue."""
        blk, ts = block_at_time(self.c, target_ts, self.tip, self.tip_ts, self.bt)
        if blk is None:
            return None, None
        vals = [oriented(self.c, pool, ptype, self.metas[i], tgt, blk)
                for i, (pool, ptype, tgt) in enumerate(self.cfgs)]
        return (None if any(v is None for v in vals) else vals), ts


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="Test precis cross-chain VELVET base<->bsc (timestamps apparies).")
    ap.add_argument("--days", type=float, default=14.0)
    ap.add_argument("--cadence-min", type=float, default=60.0)
    ap.add_argument("--tol-sec", type=float, default=120.0, help="ecart max entre la lecture et l'heure cible")
    args = ap.parse_args()

    print(f"Backfill VELVET base vs bsc (timestamps apparies) — {args.days:.0f}j cadence {args.cadence_min:.0f}min "
          f"tol +-{args.tol_sec:.0f}s")
    base = ChainCtx("base", [(BASE_VELVET[1], BASE_VELVET[2], BASE_VELVET[3])])
    bsc = ChainCtx("bsc", [(BSC_VELVET[1], BSC_VELVET[2], BSC_VELVET[3]),
                           (BSC_WBNB[1], BSC_WBNB[2], BSC_WBNB[3])])
    print(f"  base bt~{base.bt:.2f}s  bsc bt~{bsc.bt:.2f}s")

    now = min(base.tip_ts, bsc.tip_ts)
    n_targets = int(args.days * 24 * 60 / args.cadence_min)
    targets = sorted(int(now - i * args.cadence_min * 60) for i in range(n_targets))

    rows, n, max_skew = [], 0, 0.0
    for T in targets:
        bvals, bts = base.read_at(T)
        xvals, xts = bsc.read_at(T)
        n += 1
        if n % 50 == 0:
            print(f"  {n}/{len(targets)} cibles... ({len(rows)} retenues)", flush=True)
        if bvals is None or xvals is None or bts is None or xts is None:
            continue
        if abs(bts - T) > args.tol_sec or abs(xts - T) > args.tol_sec:
            continue                                      # une lecture trop loin de l'instant cible
        vb = bvals[0]
        vx = xvals[0] * xvals[1]
        mid = (vb + vx) / 2
        if mid <= 0:
            continue
        gap = (vb - vx) / mid * 1e4                        # >0 = VELVET plus cher sur base
        rows.append((T, bts, xts, vb, vx, gap))
        max_skew = max(max_skew, abs(bts - xts))
    if len(rows) < 10:
        print(f"trop peu de points apparies ({len(rows)})."); return 1

    os.makedirs(HIST, exist_ok=True)
    path = os.path.join(HIST, "settle_crosschain_velvet.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["target_unix", "iso_utc", "base_ts", "bsc_ts", "velvet_usd_base",
                                       "velvet_usd_bsc", "gap_bps"])
        for T, bts, xts, vb, vx, gap in rows:
            w.writerow([T, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(T)), bts, xts,
                        f"{vb:.6f}", f"{vx:.6f}", f"{gap:+.2f}"])

    gaps = [r[5] for r in rows]
    absg = sorted(abs(g) for g in gaps)
    signed_share = 100 * sum(1 for g in gaps if g > 0) / len(gaps)
    act = [r for r in rows if abs(r[5]) - COST_BPS > 0]
    longest = run = 0
    for r in rows:
        run = run + 1 if abs(r[5]) - COST_BPS > 0 else 0
        longest = max(longest, run)

    def pct(s, q):
        return s[min(len(s) - 1, int(q / 100 * len(s)))]

    print("\n" + "=" * 80)
    print(f"TEST CROSS-CHAIN VELVET base<->bsc — {len(rows)} points APPARIES "
          f"({time.strftime('%m-%d', time.gmtime(rows[0][0]))} -> {time.strftime('%m-%d', time.gmtime(rows[-1][0]))}, "
          f"skew base/bsc max {max_skew:.0f}s)")
    print(f"  |gap| : median {pct(absg,50):.0f}  p75 {pct(absg,75):.0f}  p90 {pct(absg,90):.0f}  "
          f"p99 {pct(absg,99):.0f}  max {absg[-1]:.0f} bps")
    print(f"  signe : {signed_share:.0f}% du temps base>bsc, {100-signed_share:.0f}% bsc>base  "
          f"(median {statistics.median(gaps):+.0f} bps) -> ~50/50 = OSCILLE (bruit) ; unilateral = dislocation")
    print(f"  au-dessus des couts (~{COST_BPS:.0f}bps) : {len(act)}/{len(rows)} = {100*len(act)/len(rows):.0f}%")
    print(f"  PERSISTANCE : plus longue serie au-dessus des couts = {longest} points consecutifs "
          f"(~{longest*args.cadence_min/60:.0f}h)")
    print(f"\n  Lecture : maintenant les 2 chaines sont lues au MEME instant (skew max {max_skew:.0f}s). Si le")
    print(f"  gap reste GROS et UNILATERAL -> vraie dislocation. S'il s'effondre / oscille ~50-50 -> le '36bps'")
    print(f"  d'avant etait bien du lag. Donnees exactes -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
