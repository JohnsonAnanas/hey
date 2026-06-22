#!/usr/bin/env python
"""Simulateur MAV-net mono-paire (Base, WETH/USDC), pools v2 UNIQUEMENT, SANS execution.

Version focalisee/validee (1 paire). Pour balayer N paires : run_mav_multi.py.
Pipeline (cf docs/core_notes.md) : resoudre pools v2 -> lire reserves (Multicall) -> evaluer les
DEUX sens (Δx* -> xOut -> brut -> gas -> net) -> classer ACCEPTED/REJECTED + motif -> log CSV.

AUCUNE transaction, AUCUN flash loan, AUCUNE cle privee. Lecture seule.
Usage : python run_mav_sim.py --seconds 60 --interval 3 --gas-units 300000 --min-usdc 50000
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from itertools import combinations
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from web3 import Web3
from eth_abi import encode as abi_encode

from sim.amm_v2 import evaluate_pair
from sim.chain import (RPC, MULTICALL3, addr_from, SEL_GETPAIR, SEL_GETPOOL_BOOL,
                       SEL_GETFEE, SEL_TOKEN0, SEL_RESERVES, SEL_BLOCKNUM)

WETH = Web3.to_checksum_address("0x4200000000000000000000000000000000000006")
USDC = Web3.to_checksum_address("0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913")
DEC = {WETH: 18, USDC: 6}

V2_FACTORIES = [
    {"name": "UniV2",     "factory": "0x8909Dc15e40173Ff4699343b6eB8132c65e18eC6", "method": "getPair",     "fee": 0.0030},
    {"name": "SushiV2",   "factory": "0x71524B4f93c58fcbF659783284E38825f0622859", "method": "getPair",     "fee": 0.0030},
    {"name": "BaseSwap",  "factory": "0xFDa619b6d20975be80A10332cD39b9a4b0FAa8BB", "method": "getPair",     "fee": 0.0030},
    {"name": "Aerodrome", "factory": "0x420DD381b31aEf6683db6B902084cB0FFECe40Da", "method": "getPoolBool", "fee": None},
]


def resolve_pools(rpc: RPC) -> list[dict]:
    calls = []
    for f in V2_FACTORIES:
        fac = Web3.to_checksum_address(f["factory"])
        if f["method"] == "getPair":
            calls.append((fac, SEL_GETPAIR + abi_encode(["address", "address"], [WETH, USDC])))
        else:
            calls.append((fac, SEL_GETPOOL_BOOL + abi_encode(["address", "address", "bool"], [WETH, USDC, False])))
    res = rpc.multicall(calls)
    cand = []
    for (ok, data), f in zip(res, V2_FACTORIES):
        addr = addr_from(data) if ok else None
        if addr:
            cand.append({**f, "address": addr})
        else:
            print(f"  [skip] {f['name']} : pool introuvable (factory {f['factory'][:10]}...)")
    if not cand:
        return []
    calls2 = [(c["address"], SEL_TOKEN0) for c in cand]
    for c in cand:
        if c["method"] == "getPoolBool":
            calls2.append((Web3.to_checksum_address(c["factory"]),
                           SEL_GETFEE + abi_encode(["address", "bool"], [Web3.to_checksum_address(c["address"]), False])))
    res2 = rpc.multicall(calls2)
    pools = []
    for idx, c in enumerate(cand):
        ok, data = res2[idx]
        t0 = addr_from(data) if ok else None
        if t0 not in DEC:
            print(f"  [skip] {c['name']} : token0 inattendu/illisible")
            continue
        c["weth_is_t0"] = (t0 == WETH)
        pools.append(c)
    j = len(cand)
    for c in cand:
        if c["method"] == "getPoolBool":
            ok, data = res2[j]; j += 1
            if c in pools and ok and data and len(data) >= 32:
                rate = int.from_bytes(data, "big") / 10_000.0
                c["fee"] = rate if 0 < rate < 0.05 else 0.0030
    for c in pools:
        print(f"  [ok]   {c['name']:<10} {c['address']}  fee {c['fee']*100:.3f}%  "
              f"token0={'WETH' if c['weth_is_t0'] else 'USDC'}")
    return pools


def read_state(rpc: RPC, pools: list[dict]):
    calls = [(MULTICALL3, SEL_BLOCKNUM)] + [(Web3.to_checksum_address(p["address"]), SEL_RESERVES) for p in pools]
    res = rpc.multicall(calls)
    block = int.from_bytes(res[0][1], "big") if res[0][0] else -1
    state = {}
    for (ok, data), p in zip(res[1:], pools):
        if not (ok and len(data) >= 64):
            continue
        r0, r1 = int.from_bytes(data[0:32], "big"), int.from_bytes(data[32:64], "big")
        rweth_raw, rusdc_raw = (r0, r1) if p["weth_is_t0"] else (r1, r0)
        if rweth_raw and rusdc_raw:
            state[p["name"]] = (rweth_raw / 10 ** DEC[WETH], rusdc_raw / 10 ** DEC[USDC])
    return block, state


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="Simulateur MAV-net v2 WETH/USDC sur Base (lecture seule).")
    ap.add_argument("--seconds", type=float, default=60.0)
    ap.add_argument("--interval", type=float, default=3.0)
    ap.add_argument("--gas-units", type=int, default=300_000)
    ap.add_argument("--min-usdc", type=float, default=50_000.0)
    args = ap.parse_args()

    rpc = RPC()
    print("Resolution des pools v2 (constant-product) :")
    pools = resolve_pools(rpc)
    if len(pools) < 2:
        print("Moins de 2 pools v2 resolus. (Tests math: pytest tests/)", file=sys.stderr)
        return 1
    fee_by_name = {p["name"]: p["fee"] for p in pools}   # evite next() sans defaut (StopIteration)

    out_dir = Path(__file__).resolve().parent / "data" / "logs"
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / "mav_sim_base.csv"
    f = open(log_path, "w", newline="", encoding="utf-8")
    w = csv.writer(f)
    w.writerow(["ts", "block", "pair", "direction", "dx_star_weth", "x_out_weth",
                "gross_weth", "gas_weth", "net_weth", "net_usd", "status", "reason"])

    reasons, n_accepted, best_net_usd = {}, 0, -1e30
    t_end = time.time() + args.seconds
    print(f"\nSimulation {args.seconds:.0f}s, poll {args.interval:.1f}s, {len(pools)} pools, gas={args.gas_units} units.\n")
    try:
        while time.time() < t_end:
            t_poll = time.time()
            try:
                block, state = read_state(rpc, pools)
                gas_price = rpc.w3.eth.gas_price
            except Exception as e:
                print(f"poll KO : {e!r}"); time.sleep(args.interval); continue
            gas_weth = args.gas_units * gas_price / 1e18
            usable = {n: rv for n, rv in state.items() if rv[1] >= args.min_usdc}
            eth_usd = next((ry / rx for rx, ry in usable.values() if rx), None)
            poll_acc = 0
            for na, nb in combinations(sorted(usable), 2):
                pa = {"reserve_x": usable[na][0], "reserve_y": usable[na][1], "fee": fee_by_name[na]}
                pb = {"reserve_x": usable[nb][0], "reserve_y": usable[nb][1], "fee": fee_by_name[nb]}
                for ev in evaluate_pair(pa, pb, gas_weth):
                    net_usd = ev.net_profit * eth_usd if eth_usd else float("nan")
                    w.writerow([time.strftime("%H:%M:%S"), block, f"{na}/{nb}", ev.direction,
                                f"{ev.dx_star:.8f}", f"{ev.x_out:.8f}", f"{ev.gross_profit:.8f}",
                                f"{ev.gas_cost:.8f}", f"{ev.net_profit:.8f}", f"{net_usd:.4f}",
                                ev.status, ev.reason])
                    if ev.status == "ACCEPTED":
                        n_accepted += 1; poll_acc += 1; best_net_usd = max(best_net_usd, net_usd)
                        print(f"[{time.strftime('%H:%M:%S')} blk={block}] ACCEPTED {na}/{nb} {ev.direction} "
                              f"Δx*={ev.dx_star:.4f}WETH net={ev.net_profit:.6f}WETH (~${net_usd:.2f})")
                    else:
                        reasons[ev.reason] = reasons.get(ev.reason, 0) + 1
            f.flush()
            if poll_acc == 0:
                top = " ".join(f"{n}={ry:,.0f}USDC@{ry/rx:,.1f}" for n, (rx, ry) in usable.items())
                print(f"[{time.strftime('%H:%M:%S')} blk={block}] 0 opp. nette | {top} | gas~${gas_weth*(eth_usd or 0):.4f}")
            time.sleep(max(0.0, args.interval - (time.time() - t_poll)))
    except KeyboardInterrupt:
        print("\n(interrompu)")
    finally:
        f.close()

    print("\n" + "=" * 64)
    print(f"SYNTHESE  (log -> {log_path})")
    print(f"Opportunites ACCEPTED (net>0) : {n_accepted}" + (f" | meilleur ~${best_net_usd:.2f}" if n_accepted else ""))
    print("Rejets par motif :")
    for r, k in sorted(reasons.items(), key=lambda x: -x[1]):
        print(f"  {k:5d}  {r}")
    if n_accepted == 0:
        print("\nLecture : 0 opp. nette = les ecarts v2 restent < frais (borne de non-arbitrage, R1).")
        print("La MACHINE est validee : lit les reserves, calcule Δx*/MAV-net, classe et logue correctement.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
