#!/usr/bin/env python
"""Moteur de BACKFILL historique on-chain — reconstruit le prix d'un pool a des blocs PASSES.

Lit l'ETAT a des blocs anciens (archive) : reserves (v2) ou sqrtPriceX96 (v3) + timestamp du bloc.
Pas besoin de getLogs -> marche sur toute chaine avec archive (eth via Alchemy ; base/arbitrum/
optimism/polygon via endpoints gratuits ; bsc en attente d'activation Alchemy). Rotation d'endpoints
(archive_rpc), cle Alchemy jamais imprimee. Cadence configurable (defaut horaire) = budget maitrise.

Le prix est EXACT au bloc (meme source que le live, lue dans le passe) -> zero biais close-vs-close.
Introspection du pool (token0/token1 + decimales) -> prix oriente correctement. Stockage append-only
data/historical/{chain}_{pool8}.csv : block, ts_unix, iso_utc, price_t0_in_t1.

Usage : python backfill.py --chain base --pool 0x... --type v3 --days 7 --cadence-min 60
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from archive_rpc import endpoints, rpc, redact

# selecteurs (4 bytes)
SEL = {"token0": "0x0dfe1681", "token1": "0xd21220a7", "decimals": "0x313ce567",
       "getReserves": "0x0902f1ac", "slot0": "0x3850c7bd"}
BLOCK_TIME = {"eth": 12.0, "base": 2.0, "arbitrum": 0.25, "optimism": 2.0, "polygon": 2.0, "bsc": 3.0}
HIST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "historical")


class Caller:
    """eth_call / lectures, avec rotation d'endpoints archive par chaine (garde le 1er qui marche)."""

    def __init__(self, chain: str):
        self.chain = chain
        self.urls = endpoints(chain)
        self.i = 0
        if not self.urls:
            raise SystemExit(f"Aucun endpoint archive pour {chain} (active le reseau sur Alchemy).")

    def _try(self, method, params):
        n = len(self.urls)
        for k in range(n):
            url = self.urls[(self.i + k) % n]
            res, err = rpc(url, method, params, timeout=25)
            if res is not None:
                self.i = (self.i + k) % n
                return res
        return None

    def call(self, to, data, block="latest"):
        blk = block if isinstance(block, str) else hex(block)
        return self._try("eth_call", [{"to": to, "data": data}, blk])

    def block_ts(self, block):
        r = self._try("eth_getBlockByNumber", [hex(block), False])
        return int(r["timestamp"], 16) if r and r.get("timestamp") else None

    def tip(self):
        r = self._try("eth_blockNumber", [])
        return int(r, 16) if r else None


def est_block_time(c: "Caller", tip: int, span: int = 20000) -> float | None:
    """Temps de bloc (s) DERIVE de 2 timestamps reels -> robuste a tout chain/upgrade (vs constante figee)."""
    t1 = c.block_ts(tip)
    t0 = c.block_ts(max(1, tip - span))
    if t1 and t0 and t1 > t0:
        return (t1 - t0) / min(span, tip - 1)
    return None


def block_at_time(c: "Caller", target_ts: int, tip: int, tip_ts: int, bt: float):
    """Bloc le plus proche de `target_ts` (estimation via temps de bloc + 3 raffinages). (block, ts) ou (None,None).
    Permet d'aligner DEUX chaines au MEME instant (sinon le gap cross-chain est pollue par le lag)."""
    blk = max(1, min(tip, int(tip - (tip_ts - target_ts) / bt)))
    ts = None
    for _ in range(4):
        ts = c.block_ts(blk)
        if ts is None:
            return None, None
        err = target_ts - ts
        if abs(err) <= bt * 2:
            break
        blk = max(1, min(tip, int(blk + err / bt)))
    return blk, ts


def _word(hexstr, i):
    h = hexstr[2:] if hexstr.startswith("0x") else hexstr
    return h[i * 64:(i + 1) * 64]


def read_meta(c: Caller, pool: str):
    """(token0, token1, dec0, dec1) ou None."""
    t0 = c.call(pool, SEL["token0"]); t1 = c.call(pool, SEL["token1"])
    if not t0 or not t1:
        return None
    a0 = "0x" + _word(t0, 0)[24:]; a1 = "0x" + _word(t1, 0)[24:]
    d0 = c.call(a0, SEL["decimals"]); d1 = c.call(a1, SEL["decimals"])
    if not d0 or not d1:
        return None
    return a0, a1, int(d0, 16), int(d1, 16)


def price_at(c: Caller, pool: str, ptype: str, d0: int, d1: int, block):
    """Prix de token0 en token1 au bloc, ou None."""
    if ptype == "v2":
        r = c.call(pool, SEL["getReserves"], block)
        if not r:
            return None
        r0 = int(_word(r, 0), 16); r1 = int(_word(r, 1), 16)
        if r0 == 0:
            return None
        return (r1 / 10 ** d1) / (r0 / 10 ** d0)
    else:  # v3 : sqrtPriceX96 = 1er mot de slot0
        r = c.call(pool, SEL["slot0"], block)
        if not r:
            return None
        sp = int(_word(r, 0), 16)
        if sp == 0:
            return None
        raw = (sp / 2 ** 96) ** 2          # token1_raw / token0_raw
        return raw * 10 ** (d0 - d1)        # token0 en token1 (humain)


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="Backfill historique on-chain d'un pool.")
    ap.add_argument("--chain", required=True)
    ap.add_argument("--pool", required=True)
    ap.add_argument("--type", choices=["v2", "v3"], required=True)
    ap.add_argument("--days", type=float, default=7.0)
    ap.add_argument("--cadence-min", type=float, default=60.0)
    args = ap.parse_args()

    c = Caller(args.chain)
    tip = c.tip()
    if not tip:
        print("tip introuvable (endpoints KO)."); return 1
    meta = read_meta(c, args.pool)
    if not meta:
        print("introspection du pool impossible (mauvaise adresse/chaine/type ?)."); return 1
    a0, a1, d0, d1 = meta
    bt = est_block_time(c, tip) or BLOCK_TIME.get(args.chain, 2.0)
    step = max(1, int(args.cadence_min * 60 / bt))
    n_blocks = int(args.days * 86400 / bt)
    start = max(1, tip - n_blocks)
    print(f"{args.chain} pool {args.pool[:10]} type {args.type} | token0={a0[:10]}(d{d0}) token1={a1[:10]}(d{d1})")
    print(f"tip={tip} start={start} step={step} blocs (~{args.cadence_min:.0f}min) -> ~{(tip-start)//step} points")

    os.makedirs(HIST, exist_ok=True)
    path = os.path.join(HIST, f"{args.chain}_{args.pool[2:10]}.csv")
    new = not os.path.exists(path)
    f = open(path, "a", newline="", encoding="utf-8")
    w = csv.writer(f)
    if new:
        w.writerow(["block", "ts_unix", "iso_utc", "price_t0_in_t1", "token0", "token1", "dec0", "dec1"])

    n, first_iso, last_iso, pmin, pmax = 0, None, None, None, None
    blk = start
    t_start = time.time()
    while blk <= tip:
        p = price_at(c, args.pool, args.type, d0, d1, blk)
        ts = c.block_ts(blk)
        if p is not None and ts:
            iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))
            w.writerow([blk, ts, iso, f"{p:.10g}", a0, a1, d0, d1]); n += 1
            first_iso = first_iso or iso; last_iso = iso
            pmin = p if pmin is None else min(pmin, p); pmax = p if pmax is None else max(pmax, p)
            if n % 25 == 0:
                f.flush(); print(f"  {n} points... {iso} prix={p:.6g}")
        blk += step
    f.flush(); f.close()
    print(f"\nFAIT : {n} points stockes -> {path}")
    if n:
        print(f"  periode {first_iso} -> {last_iso} | prix {pmin:.6g}..{pmax:.6g} | {time.time()-t_start:.0f}s")
        print("  (prix de token0 en token1, exact au bloc -> serie historique precise, reutilisable)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
