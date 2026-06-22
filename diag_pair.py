#!/usr/bin/env python
"""Diagnostic d'une paire : prix mid / TVL / frais par venue + gap pairwise vs frais (lecture seule).

Sert a comprendre POURQUOI un ecart mid large ne donne pas d'arbitrage (frais d'une venue, pool
fin/stale, mauvais sens...). Reutilise sim/chain.py et la config de run_mav_multi.py.

Usage : python diag_pair.py VIRTUAL WETH
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from web3 import Web3
from eth_abi import encode as abi_encode

from sim.chain import (RPC, addr_from, uint_from, SEL_GETPAIR, SEL_GETPOOL_BOOL,
                       SEL_GETFEE, SEL_RESERVES, SEL_DECIMALS)
from sim.amm_v2 import evaluate_pair
from run_mav_multi import A, V2_FACTORIES, usd_price


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("sym_a"); ap.add_argument("sym_b")
    args = ap.parse_args()
    s0, s1 = (args.sym_a, args.sym_b) if int(A[args.sym_a], 16) < int(A[args.sym_b], 16) else (args.sym_b, args.sym_a)

    rpc = RPC()
    dd = rpc.multicall([(A[s0], SEL_DECIMALS), (A[s1], SEL_DECIMALS)])
    d0, d1 = uint_from(dd[0][1]), uint_from(dd[1][1])

    # eth_usd via le pool WETH/USDC Aerodrome
    WETH, USDC = A["WETH"], A["USDC"]
    e0, e1 = (WETH, USDC) if int(WETH, 16) < int(USDC, 16) else (USDC, WETH)
    aero_fac = Web3.to_checksum_address(V2_FACTORIES[-1]["factory"])
    eu = addr_from(rpc.multicall([(aero_fac, SEL_GETPOOL_BOOL + abi_encode(["address", "address", "bool"], [e0, e1, False]))])[0][1])
    eur = rpc.multicall([(eu, SEL_RESERVES)])[0][1]
    w_raw, u_raw = (int.from_bytes(eur[0:32], "big"), int.from_bytes(eur[32:64], "big")) if e0 == WETH \
        else (int.from_bytes(eur[32:64], "big"), int.from_bytes(eur[0:32], "big"))
    eth_usd = (u_raw / 1e6) / (w_raw / 1e18)

    # resoudre les pools de la paire
    calls = []
    for f in V2_FACTORIES:
        fac = Web3.to_checksum_address(f["factory"])
        cd = (SEL_GETPAIR + abi_encode(["address", "address"], [A[s0], A[s1]])) if f["method"] == "getPair" \
            else (SEL_GETPOOL_BOOL + abi_encode(["address", "address", "bool"], [A[s0], A[s1], False]))
        calls.append((fac, cd))
    pools = [(f["name"], addr_from(d) if ok else None, f) for f, (ok, d) in zip(V2_FACTORIES, rpc.multicall(calls))]
    pools = [(n, a, f) for (n, a, f) in pools if a]

    rr = rpc.multicall([(a, SEL_RESERVES) for (n, a, f) in pools])
    fees = {}
    aero = [(n, a, f) for (n, a, f) in pools if f["method"] == "getPoolBool"]
    if aero:
        fr = rpc.multicall([(Web3.to_checksum_address(f["factory"]),
                             SEL_GETFEE + abi_encode(["address", "bool"], [Web3.to_checksum_address(a), False]))
                            for (n, a, f) in aero])
        for (n, a, f), (ok, d) in zip(aero, fr):
            rate = (uint_from(d) or 0) / 10_000.0 if ok else 0
            fees[n] = rate if 0 < rate < 0.05 else 0.0030

    print(f"\n{s0}/{s1}   token0={s0}  (eth_usd~{eth_usd:.0f})")
    venues = []
    for (n, a, f), (ok, d) in zip(pools, rr):
        if not (ok and len(d) >= 64):
            continue
        r0 = int.from_bytes(d[0:32], "big") / 10 ** d0
        r1 = int.from_bytes(d[32:64], "big") / 10 ** d1
        if r0 <= 0 or r1 <= 0:
            continue
        fee = fees.get(n, f["fee"] if f["fee"] else 0.0030)
        u0 = usd_price(s0, s0, s1, r0, r1, eth_usd)
        u1 = usd_price(s1, s0, s1, r0, r1, eth_usd)
        tvl = (u0 * r0 if u0 else 0) + (u1 * r1 if u1 else 0)
        venues.append({"n": n, "r0": r0, "r1": r1, "fee": fee, "tvl": tvl, "price": r1 / r0, "u0": u0})
        print(f"  {n:<10} prix(t1/t0)={r1/r0:.8g}  TVL~${tvl:,.0f}  fee={fee*100:.2f}%")

    print("  --- gap pairwise vs frais ---")
    for i in range(len(venues)):
        for j in range(i + 1, len(venues)):
            va, vb = venues[i], venues[j]
            gap = (max(va["price"], vb["price"]) / min(va["price"], vb["price"]) - 1) * 1e4
            fsum = (va["fee"] + vb["fee"]) * 1e4
            evs = evaluate_pair({"reserve_x": va["r0"], "reserve_y": va["r1"], "fee": va["fee"]},
                                {"reserve_x": vb["r0"], "reserve_y": vb["r1"], "fee": vb["fee"]}, 0.0)
            acc = [e for e in evs if e.status == "ACCEPTED"]
            tag = f"ARB brut~${acc[0].gross_profit*va['u0']:.2f}" if acc else "pas d'arb (gap<frais)"
            print(f"    {va['n']:<10}<->{vb['n']:<10} gap={gap:7.1f}bps  frais={fsum:5.0f}bps  -> {tag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
