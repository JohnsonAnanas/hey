#!/usr/bin/env python
"""Scanner MAV-net MULTI-PAIRES (Base), pools v2 UNIQUEMENT, SANS execution.

Balaye un panier de tokens x {WETH, USDC} sur tous les DEX v2-like, garde les paires presentes
sur >=2 venues, et pour chacune :
  - valorise la liquidite de chaque pool au prix de REFERENCE (anti dust-mirage, cf sim/pricing.py) ;
  - ne garde que les pools reellement profonds (>= --min-usd par jambe) ;
  - calcule le MAV-net (Δx* -> xOut -> brut -> gas -> net) dans les deux sens ;
  - SIGNAL DE CHASSE = le MAV net reellement extractible (classe), PAS l'ecart mid affiche.

AUCUNE execution, lecture seule. Usage : python run_mav_multi.py --seconds 90 --min-usd 50000
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

import requests
from web3 import Web3
from eth_abi import encode as abi_encode

from sim.amm_v2 import evaluate_pair
from sim.pricing import reference_usd, pool_liquidity_usd
from sim.validate import validate_pools
from sim.integrity import poll_meta, poll_should_abstain
from sim.chain import (RPC, MULTICALL3, addr_from, uint_from, SEL_GETPAIR, SEL_GETPOOL_BOOL,
                       SEL_GETFEE, SEL_RESERVES, SEL_DECIMALS, SEL_BLOCKNUM)

TOKENS = {
    "WETH":  "0x4200000000000000000000000000000000000006",
    "USDC":  "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
    "USDbC": "0xd9aAEc86B65D86f6A7B5B1b0c42FFA531710b6CA",
    "DAI":   "0x50c5725949A6F0c72E6C4a641F24049A917DB0Cb",
    "cbETH": "0x2Ae3F1Ec7F1F5012CFEab0185bfc7aa3cf0DEc22",
    "cbBTC": "0xcbB7C0000aB88B473b1f5aFd9ef808440eed33Bf",
    "AERO":  "0x940181a94A35A4569E4529A3CDfB74e38FD98631",
    "DEGEN": "0x4ed4E862860beD51a9570b96d89aF5E1B0Efefed",
    "BRETT": "0x532f27101965dd16442E59d40670FaF5eBB142E4",
    "TOSHI": "0xAC1Bd2486aAf3B5C0fc3Fd868558b082a531B2B4",
    "VIRTUAL": "0x0b3e328455c4059EEb9e3f84b5543F74E24e7E1b",
}
QUOTES = ["WETH", "USDC"]
STABLES = {"USDC", "USDbC", "DAI"}
EXTRA_PAIRS = [("WETH", "USDC"), ("WETH", "USDbC"), ("USDC", "USDbC"), ("DAI", "USDC"), ("WETH", "cbETH")]

V2_FACTORIES = [
    {"name": "UniV2",     "factory": "0x8909Dc15e40173Ff4699343b6eB8132c65e18eC6", "method": "getPair",     "fee": 0.0030},
    {"name": "SushiV2",   "factory": "0x71524B4f93c58fcbF659783284E38825f0622859", "method": "getPair",     "fee": 0.0030},
    {"name": "BaseSwap",  "factory": "0xFDa619b6d20975be80A10332cD39b9a4b0FAa8BB", "method": "getPair",     "fee": 0.0030},
    {"name": "Aerodrome", "factory": "0x420DD381b31aEf6683db6B902084cB0FFECe40Da", "method": "getPoolBool", "fee": None},
]

A = {s: Web3.to_checksum_address(a) for s, a in TOKENS.items()}


def usd_price(sym, s0, s1, r0, r1, eth_usd):
    """Prix USD d'un token via la jambe quote du POOL (mid local). Conserve pour diag_pair.py."""
    if sym in STABLES:
        return 1.0
    if sym == "WETH":
        return eth_usd
    other = s1 if sym == s0 else s0
    other_usd = 1.0 if other in STABLES else (eth_usd if other == "WETH" else None)
    if other_usd is None:
        return None
    r_sym, r_other = (r0, r1) if sym == s0 else (r1, r0)
    return (r_other / r_sym) * other_usd if r_sym else None


def derive_eth_usd(all_pools):
    """eth_usd = USDC par WETH du pool WETH/USDC le PLUS PROFOND (jamais le premier venu). None sinon."""
    best_usdc, price = -1.0, None
    for p in all_pools:
        if set(p["pair"]) == {"WETH", "USDC"} and p.get("_r"):
            s0, s1 = p["pair"]; r0, r1 = p["_r"]
            usdc = r1 if s1 == "USDC" else r0
            if usdc > best_usdc:
                best_usdc, price = usdc, ((r1 / r0) if s0 == "WETH" else (r0 / r1))
    return price


def binance_eth_usd():
    """Prix de recoupement externe (best-effort, non bloquant)."""
    try:
        return float(requests.get("https://api.binance.com/api/v3/ticker/price?symbol=ETHUSDT",
                                  timeout=6).json()["price"])
    except Exception:
        return None


def build_pairs() -> list[tuple[str, str]]:
    seen, pairs = set(), []
    for s in TOKENS:
        if s in QUOTES:
            continue
        for q in QUOTES:
            key = frozenset((s, q))
            if len(key) == 2 and key not in seen:
                seen.add(key); pairs.append((s, q))
    for a, b in EXTRA_PAIRS:
        key = frozenset((a, b))
        if key not in seen:
            seen.add(key); pairs.append((a, b))
    return [(a, b) if int(A[a], 16) < int(A[b], 16) else (b, a) for a, b in pairs]


def resolve(rpc: RPC):
    syms = list(TOKENS)
    res_dec = rpc.multicall([(A[s], SEL_DECIMALS) for s in syms])
    dec = {}
    for (ok, data), s in zip(res_dec, syms):
        v = uint_from(data) if ok else None
        if v is not None and 0 < v <= 36:
            dec[s] = v
    pairs = [(s0, s1) for (s0, s1) in build_pairs() if s0 in dec and s1 in dec]

    specs, calls = [], []
    for (s0, s1) in pairs:
        for f in V2_FACTORIES:
            fac = Web3.to_checksum_address(f["factory"])
            cd = (SEL_GETPAIR + abi_encode(["address", "address"], [A[s0], A[s1]])) if f["method"] == "getPair" \
                else (SEL_GETPOOL_BOOL + abi_encode(["address", "address", "bool"], [A[s0], A[s1], False]))
            specs.append({"pair": (s0, s1), "venue": f["name"], "factory": fac, "method": f["method"], "fee": f["fee"]})
            calls.append((fac, cd))
    res = rpc.multicall(calls)
    pools = [{**spec, "address": addr_from(data)} for spec, (ok, data) in zip(specs, res) if ok and addr_from(data)]

    aero = [p for p in pools if p["method"] == "getPoolBool"]
    if aero:
        res_fee = rpc.multicall([(p["factory"], SEL_GETFEE +
                                  abi_encode(["address", "bool"], [Web3.to_checksum_address(p["address"]), False])) for p in aero])
        for p, (ok, data) in zip(aero, res_fee):
            rate = (uint_from(data) or 0) / 10_000.0 if ok else 0
            p["fee"] = rate if 0 < rate < 0.05 else None      # PAS de fallback muet -> quarantaine si illisible

    n_resolved = len(pools)
    pools, quarantined = validate_pools(rpc, pools, A)        # Phase 2 : porte d'integrite pool/token
    for p, reasons in quarantined:
        s0, s1 = p["pair"]
        print(f"  [quarantaine] {p['venue']:<10} {s0}/{s1:<7} : {', '.join(reasons)}")

    by_pair = {}
    for p in pools:
        by_pair.setdefault(p["pair"], []).append(p)
    kept = {pk: ps for pk, ps in by_pair.items() if len(ps) >= 2}
    print(f"decimals: {len(dec)}/{len(syms)} | paires testees: {len(pairs)} | "
          f"pools resolus: {n_resolved} | valides: {len(pools)} | quarantaine: {len(quarantined)} | "
          f"paires a >=2 venues: {len(kept)}")
    return dec, kept


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="Scanner MAV-net multi-paires v2 sur Base (lecture seule).")
    ap.add_argument("--seconds", type=float, default=90.0)
    ap.add_argument("--interval", type=float, default=4.0)
    ap.add_argument("--gas-units", type=int, default=300_000)
    ap.add_argument("--min-usd", type=float, default=50_000.0, help="liquidite USD min PAR JAMBE (prix de reference)")
    args = ap.parse_args()

    rpc = RPC()
    print("Resolution (decimals + pools v2 multi-paires) :")
    dec, kept = resolve(rpc)
    if not kept:
        print("Aucune paire a >=2 venues v2. (Tests: pytest tests/)", file=sys.stderr)
        return 1
    all_pools = [p for ps in kept.values() for p in ps]

    out_dir = Path(__file__).resolve().parent / "data" / "logs"
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / "mav_multi_base.csv"
    f = open(log_path, "w", newline="", encoding="utf-8")
    w = csv.writer(f)
    w.writerow(["ts", "block", "block_ts", "fresh_ok", "n_sources", "pair", "venueA", "venueB",
                "gap_bps_liquid", "direction", "dx_star_t0", "gross_t0", "gas_t0", "net_t0",
                "net_usd", "status", "reason"])

    # SIGNAL DE CHASSE = MAV net reellement extractible (pas l'ecart mid).
    best_net = {pk: float("-inf") for pk in kept}
    liq_gap = {pk: 0.0 for pk in kept}
    n_liq = {pk: 0 for pk in kept}
    n_accepted, best_net_usd_global, reasons = 0, float("-inf"), {}
    xcheck_done = [False]
    blocks_seen = set()
    t_end = time.time() + args.seconds
    print(f"\nScan {args.seconds:.0f}s, poll {args.interval:.1f}s, {len(kept)} paires, {len(all_pools)} pools, "
          f"liquidite min ${args.min_usd:,.0f}/jambe.\n")
    try:
        while time.time() < t_end:
            t_poll = time.time()
            reserve_calls = [(Web3.to_checksum_address(p["address"]), SEL_RESERVES) for p in all_pools]
            try:
                block, block_ts, res, fresh = rpc.read_block(reserve_calls)   # bloc = reference temps + fraicheur
                gas_price = rpc.w3.eth.gas_price
            except Exception as e:
                print(f"poll KO : {e!r}"); time.sleep(args.interval); continue
            meta = poll_meta(fresh)
            ab = poll_should_abstain(fresh)
            if ab:                                                            # invariant non tenu -> on s'abstient
                print(f"[{time.strftime('%H:%M:%S')} blk={block}] ABSTAIN poll : {ab}")
                time.sleep(max(0.0, args.interval - (time.time() - t_poll))); continue
            if block:
                blocks_seen.add(block)
            for p, (ok, data) in zip(all_pools, res):
                p["_r"] = None
                if ok and len(data) >= 64:
                    s0, s1 = p["pair"]
                    r0 = int.from_bytes(data[0:32], "big") / 10 ** dec[s0]
                    r1 = int.from_bytes(data[32:64], "big") / 10 ** dec[s1]
                    if r0 > 0 and r1 > 0:
                        p["_r"] = (r0, r1)
            eth_usd = derive_eth_usd(all_pools)
            if eth_usd is None:
                print(f"[{time.strftime('%H:%M:%S')} blk={block}] ABSTAIN poll : pas d'ancre WETH/USDC "
                      f"liquide -> aucune valorisation fiable")
                time.sleep(max(0.0, args.interval - (time.time() - t_poll))); continue
            if not xcheck_done[0]:
                xcheck_done[0] = True
                be = binance_eth_usd()
                if be:
                    dbps = (eth_usd / be - 1) * 1e4
                    print(f"  cross-check prix DEX vs Binance : {eth_usd:.2f} vs {be:.2f} = {dbps:+.1f} bps"
                          + ("  !! ECART SUSPECT (>300bps)" if abs(dbps) > 300 else ""))
                else:
                    print("  cross-check prix : Binance indisponible (non bloquant)")
            gas_eth = args.gas_units * gas_price / 1e18
            gas_usd = gas_eth * eth_usd

            poll_acc = 0
            for (s0, s1), ps in kept.items():
                reserves = [p["_r"] for p in ps if p["_r"]]
                refs = reference_usd(s0, s1, reserves, eth_usd, STABLES) if reserves else None
                if not refs:
                    continue
                usd0, usd1 = refs
                # filtre liquidite AU PRIX DE REFERENCE (anti dust-mirage)
                live = [(p, *p["_r"]) for p in ps if p["_r"] and pool_liquidity_usd(p["_r"][0], p["_r"][1], usd0, usd1) >= args.min_usd]
                n_liq[(s0, s1)] = len(live)
                if len(live) < 2:
                    continue
                mids = [r1 / r0 for (_, r0, r1) in live]
                liq_gap[(s0, s1)] = max(liq_gap[(s0, s1)], (max(mids) / min(mids) - 1.0) * 1e4)
                gas_t0 = gas_usd / usd0 if usd0 else 0.0
                for (pa, ra0, ra1), (pb, rb0, rb1) in combinations(live, 2):
                    gp = (max(ra1 / ra0, rb1 / rb0) / min(ra1 / ra0, rb1 / rb0) - 1.0) * 1e4
                    for ev in evaluate_pair({"reserve_x": ra0, "reserve_y": ra1, "fee": pa["fee"]},
                                            {"reserve_x": rb0, "reserve_y": rb1, "fee": pb["fee"]}, gas_t0):
                        net_usd = ev.net_profit * usd0
                        best_net[(s0, s1)] = max(best_net[(s0, s1)], net_usd)
                        w.writerow([time.strftime("%H:%M:%S"), block, block_ts, meta["fresh_ok"], meta["n_sources"],
                                    f"{s0}/{s1}", pa["venue"], pb["venue"], f"{gp:.2f}", ev.direction,
                                    f"{ev.dx_star:.8f}", f"{ev.gross_profit:.8f}", f"{ev.gas_cost:.8f}",
                                    f"{ev.net_profit:.8f}", f"{net_usd:.4f}", ev.status, ev.reason])
                        if ev.status == "ACCEPTED":
                            n_accepted += 1; poll_acc += 1; best_net_usd_global = max(best_net_usd_global, net_usd)
                            print(f"[{time.strftime('%H:%M:%S')} blk={block}] *** ACCEPTED {s0}/{s1} "
                                  f"{pa['venue']}/{pb['venue']} {ev.direction} gap={gp:.1f}bps net~${net_usd:.2f}")
                        else:
                            reasons[ev.reason] = reasons.get(ev.reason, 0) + 1
            f.flush()
            if poll_acc == 0:
                top = sorted(((v, pk) for pk, v in best_net.items() if v > float("-inf")), reverse=True)[:3]
                sig = " | ".join(f"{s0}/{s1}: net~${v:.2f} (gap {liq_gap[(s0,s1)]:.1f}bps, {n_liq[(s0,s1)]}v)"
                                 for v, (s0, s1) in top)
                print(f"[{time.strftime('%H:%M:%S')} blk={block}] 0 opp. | top MAV-net: {sig or 'aucune paire liquide a >=2 venues'}")
            time.sleep(max(0.0, args.interval - (time.time() - t_poll)))
    except KeyboardInterrupt:
        print("\n(interrompu)")
    finally:
        f.close()

    print("\n" + "=" * 72)
    print(f"SYNTHESE  (log -> {log_path})")
    if blocks_seen:
        lo, hi = min(blocks_seen), max(blocks_seen)
        court = "  — echantillon TRES COURT, NE PAS generaliser" if len(blocks_seen) < 30 else ""
        print(f"COUVERTURE : {len(blocks_seen)} blocs distincts ({lo}..{hi} = {hi - lo} blocs ~ {(hi - lo) * 2}s){court}")
    print(f"Opportunites ACCEPTED (net>0) : {n_accepted}" + (f" | meilleur ~${best_net_usd_global:.2f}" if n_accepted else ""))
    print("SIGNAL DE CHASSE — paires classees par MAV-net extractible (le vrai signal, pas l'ecart mid) :")
    ranked = sorted(kept, key=lambda pk: best_net.get(pk, float("-inf")), reverse=True)
    for (s0, s1) in ranked:
        v = best_net[(s0, s1)]
        vs = f"{v:+.2f}$" if v > float("-inf") else "    —  "
        print(f"  net~{vs:>10}  gap_liquide {liq_gap[(s0, s1)]:6.1f}bps  ({n_liq[(s0, s1)]} venues liquides)  {s0}/{s1}")
    if reasons:
        print("Rejets par motif :")
        for r, k in sorted(reasons.items(), key=lambda x: -x[1]):
            print(f"  {k:6d}  {r}")
    if n_accepted == 0:
        print("\nLecture : 0 MAV-net en v2-v2 mono-chaine (apres filtre liquidite au prix de reference).")
        print("Le classement ci-dessus est honnete : il ne montre que des ecarts entre pools REELLEMENT")
        print("profonds. Prochain cran : DEX<->CEX (filon R3), ou la friction d'inventaire ouvre l'ecart.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
