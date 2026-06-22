#!/usr/bin/env python
"""Observatoire de gaps de prix DEX (lecture seule, zero capital, zero cle privee).

Mesure, poll par poll (~1 par bloc Base), le prix mid de WETH/USDC sur plusieurs DEX
d'une meme chaine (Base), calcule les ecarts inter-venues BRUTS et NETS DES FRAIS de pool,
et leur PERSISTANCE -- le chiffre qui tranche entre "capturable par un solo" et "deja
mange par les bots MEV" (gap mort en 1 bloc).

Robustesse RPC : toutes les lectures d'un poll sont batchees en UN SEUL appel via
Multicall3 (meme adresse sur toutes les chaines) -> ~1 requete/poll, pas de 429.

Discipline Mercor transferee : on mesure le NET avant de croire au brut.
- gap brut (bps)            = (max-min)/min des prix mid entre venues.
- gap net des frais (bps)   = gap brut - (frais_pool_achat + frais_pool_vente).
                              Condition NECESSAIRE (pas suffisante) : pre-slippage, pre-gas.
- persistance               = duree pendant laquelle le gap net reste > 0.

AUCUNE transaction, AUCUNE cle privee, AUCUN capital. RPC public en lecture seule.

Usage : python scan_dex_gaps.py --seconds 90 --interval 2.5
"""
from __future__ import annotations

import argparse
import csv
import os
import statistics
import sys
import time
from pathlib import Path

from web3 import Web3
from eth_abi import encode as abi_encode

CHAIN_ID = 8453
RPC_CANDIDATES = [
    os.environ.get("RPC_URL_BASE", "").strip(),
    "https://base.publicnode.com",
    "https://base.llamarpc.com",
    "https://base.drpc.org",
    "https://mainnet.base.org",
    "https://1rpc.io/base",
]

WETH = Web3.to_checksum_address("0x4200000000000000000000000000000000000006")
USDC = Web3.to_checksum_address("0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913")
DEC = {WETH: 18, USDC: 6}
SYMBOL = {WETH: "WETH", USDC: "USDC"}

UNIV3_FACTORY = Web3.to_checksum_address("0x33128a8fC17869897dcE68Ed026d694621f6FDfD")
PANCV3_FACTORY = Web3.to_checksum_address("0x0BFbCF9fa4f9C56B0F40a671Ad40E0805A091865")
AERO_FACTORY = Web3.to_checksum_address("0x420DD381b31aEf6683db6B902084cB0FFECe40Da")
MULTICALL3 = Web3.to_checksum_address("0xcA11bde05977b3631167028862bE2a173976CA11")

VENUES = [
    {"name": "UniV3-5",   "kind": "v3",   "factory": UNIV3_FACTORY,  "fee": 500,  "fee_bps": 5.0},
    {"name": "UniV3-30",  "kind": "v3",   "factory": UNIV3_FACTORY,  "fee": 3000, "fee_bps": 30.0},
    {"name": "PancV3-5",  "kind": "v3",   "factory": PANCV3_FACTORY, "fee": 500,  "fee_bps": 5.0},
    {"name": "PancV3-25", "kind": "v3",   "factory": PANCV3_FACTORY, "fee": 2500, "fee_bps": 25.0},
    {"name": "Aerodrome", "kind": "aero", "factory": AERO_FACTORY,   "stable": False, "fee_bps": 30.0},
]

ABI_MC3 = [{"inputs": [{"components": [{"type": "address", "name": "target"},
                                       {"type": "bool", "name": "allowFailure"},
                                       {"type": "bytes", "name": "callData"}],
                        "type": "tuple[]", "name": "calls"}],
            "name": "aggregate3",
            "outputs": [{"components": [{"type": "bool", "name": "success"},
                                        {"type": "bytes", "name": "returnData"}],
                         "type": "tuple[]", "name": "returnData"}],
            "stateMutability": "payable", "type": "function"}]


def sel(sig: str) -> bytes:
    return Web3.keccak(text=sig)[:4]


SEL_SLOT0 = sel("slot0()")
SEL_RESERVES = sel("getReserves()")
SEL_TOKEN0 = sel("token0()")
SEL_BLOCKNUM = sel("getBlockNumber()")
SEL_GETPOOL_V3 = sel("getPool(address,address,uint24)")
SEL_GETPOOL_AERO = sel("getPool(address,address,bool)")
ZERO = "0x0000000000000000000000000000000000000000"


class RPC:
    """Connexion Base avec rotation sur panne, et batch via Multicall3."""

    def __init__(self):
        self.urls = [u for u in RPC_CANDIDATES if u]
        self.i = 0
        self._connect()

    def _connect(self):
        for _ in range(len(self.urls)):
            url = self.urls[self.i % len(self.urls)]
            try:
                w3 = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 12}))
                if w3.is_connected() and w3.eth.chain_id == CHAIN_ID:
                    self.w3, self.url = w3, url
                    self.mc = w3.eth.contract(address=MULTICALL3, abi=ABI_MC3)
                    print(f"RPC connecte : {url}  (block {w3.eth.block_number})")
                    return
            except Exception as e:
                print(f"RPC KO {url} : {e!r}")
            self.i += 1
        raise SystemExit("Aucun RPC Base disponible.")

    def multicall(self, calls: list[tuple[str, bytes]]) -> list[tuple[bool, bytes]]:
        payload = [(t, True, d) for (t, d) in calls]
        for _ in range(3):
            try:
                return self.mc.functions.aggregate3(payload).call()
            except Exception as e:
                print(f"  multicall KO ({self.url}) : {e!r} -> rotation")
                self.i += 1
                time.sleep(0.8)
                self._connect()
        raise RuntimeError("multicall : echec apres rotation")


def resolve_all(rpc: RPC) -> list[dict]:
    """Resout adresses (getPool) + orientation (token0) en 2 multicalls."""
    calls = []
    for v in VENUES:
        if v["kind"] == "v3":
            cd = SEL_GETPOOL_V3 + abi_encode(["address", "address", "uint24"], [WETH, USDC, v["fee"]])
        else:
            cd = SEL_GETPOOL_AERO + abi_encode(["address", "address", "bool"], [WETH, USDC, v["stable"]])
        calls.append((v["factory"], cd))
    res = rpc.multicall(calls)
    cand = []
    for (ok, data), v in zip(res, VENUES):
        if ok and len(data) >= 32 and int.from_bytes(data, "big") != 0:
            cand.append({**v, "address": Web3.to_checksum_address("0x" + data[-20:].hex())})
        else:
            print(f"  [skip] {v['name']} : pool inexistant")
    if not cand:
        return []
    res2 = rpc.multicall([(c["address"], SEL_TOKEN0) for c in cand])
    venues = []
    for (ok, data), c in zip(res2, cand):
        if not (ok and len(data) >= 32):
            print(f"  [skip] {c['name']} : token0 illisible"); continue
        t0 = Web3.to_checksum_address("0x" + data[-20:].hex())
        if t0 not in DEC:
            print(f"  [skip] {c['name']} : token0 inattendu {t0}"); continue
        c["t0"], c["weth_is_t0"] = t0, (t0 == WETH)
        c["read_sel"] = SEL_SLOT0 if c["kind"] == "v3" else SEL_RESERVES
        print(f"  [ok]   {c['name']:<10} {c['address']}  token0={SYMBOL[t0]}")
        venues.append(c)
    return venues


def price_from(v: dict, data: bytes) -> float | None:
    """Prix mid USDC par WETH depuis le returnData brut (slot0 ou getReserves)."""
    if not data or len(data) < 32:
        return None
    t0 = v["t0"]
    t1 = USDC if t0 == WETH else WETH
    dec0, dec1 = DEC[t0], DEC[t1]
    if v["kind"] == "v3":
        sqrtP = int.from_bytes(data[0:32], "big")
        if sqrtP == 0:
            return None
        raw = (sqrtP / (2 ** 96)) ** 2                    # token1 par token0 (brut)
    else:
        r0 = int.from_bytes(data[0:32], "big")
        r1 = int.from_bytes(data[32:64], "big")
        if r0 == 0:
            return None
        raw = r1 / r0
    p_t1_per_t0 = raw * (10 ** (dec0 - dec1))             # token1(humain) par token0(humain)
    if v["weth_is_t0"]:
        return p_t1_per_t0                                # = USDC par WETH
    return 1.0 / p_t1_per_t0 if p_t1_per_t0 else None     # inverser si USDC=token0


def main() -> int:
    ap = argparse.ArgumentParser(description="Observatoire de gaps DEX WETH/USDC sur Base (lecture seule).")
    ap.add_argument("--seconds", type=float, default=90.0)
    ap.add_argument("--interval", type=float, default=2.5)
    args = ap.parse_args()

    rpc = RPC()
    print("Resolution des pools (via factory, batchee) :")
    venues = resolve_all(rpc)
    if len(venues) < 2:
        print("Moins de 2 venues resolues -> pas de gap a mesurer.", file=sys.stderr)
        return 1

    out_dir = Path(__file__).resolve().parent / "data" / "logs"
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / "scan_weth_usdc_base.csv"
    cols = ["ts", "block"] + [v["name"] for v in venues] + ["gross_bps", "net_bps", "cheap", "rich"]
    f = open(log_path, "w", newline="", encoding="utf-8")
    writer = csv.writer(f); writer.writerow(cols)

    gross_list, net_list, streaks, streak, n_actionable = [], [], [], 0, 0
    t_end = time.time() + args.seconds
    print(f"\nObservation {args.seconds:.0f}s, poll {args.interval:.1f}s, {len(venues)} venues, 1 requete/poll. Ctrl-C pour stopper.\n")
    try:
        while time.time() < t_end:
            t_poll = time.time()
            calls = [(MULTICALL3, SEL_BLOCKNUM)] + [(v["address"], v["read_sel"]) for v in venues]
            try:
                res = rpc.multicall(calls)
            except Exception as e:
                print(f"poll KO : {e!r}"); time.sleep(args.interval); continue
            block = int.from_bytes(res[0][1], "big") if res[0][0] else -1
            prices = {}
            for (ok, data), v in zip(res[1:], venues):
                prices[v["name"]] = price_from(v, data) if ok else None
            ok = {k: p for k, p in prices.items() if p and p > 0}
            row = [time.strftime("%H:%M:%S"), block] + [f"{prices[v['name']]:.4f}" if prices[v["name"]] else "" for v in venues]
            if len(ok) >= 2:
                cheap = min(ok, key=ok.get); rich = max(ok, key=ok.get)
                gross = (ok[rich] / ok[cheap] - 1.0) * 1e4
                fee_pair = next(v["fee_bps"] for v in venues if v["name"] == cheap) + \
                           next(v["fee_bps"] for v in venues if v["name"] == rich)
                net = gross - fee_pair
                gross_list.append(gross); net_list.append(net)
                if net > 0:
                    streak += 1; n_actionable += 1
                else:
                    if streak: streaks.append(streak)
                    streak = 0
                row += [f"{gross:.2f}", f"{net:.2f}", cheap, rich]
                pr = "  ".join(f"{k}={ok[k]:.2f}" for k in ok)
                flag = "  <<< NET>0" if net > 0 else ""
                print(f"[{row[0]} blk={block}] {pr} | gap {gross:5.2f}bps net {net:7.2f}bps ({cheap}->{rich}){flag}")
            else:
                row += ["", "", "", ""]
                print(f"[{row[0]} blk={block}] lectures insuffisantes ({len(ok)} venues)")
            writer.writerow(row); f.flush()
            time.sleep(max(0.0, args.interval - (time.time() - t_poll)))
    except KeyboardInterrupt:
        print("\n(interrompu)")
    finally:
        if streak: streaks.append(streak)
        f.close()

    print("\n" + "=" * 64)
    print(f"SYNTHESE  ({len(gross_list)} polls valides, log -> {log_path})")
    if gross_list:
        def pct(lst, thr): return 100.0 * sum(1 for x in lst if x > thr) / len(lst)
        p90 = sorted(gross_list)[int(0.9 * (len(gross_list) - 1))]
        print(f"Gap BRUT (bps)         : med {statistics.median(gross_list):.2f} | p90 {p90:.2f} | max {max(gross_list):.2f}")
        print(f"  %temps brut > 5/10/20bps : {pct(gross_list,5):.0f}% / {pct(gross_list,10):.0f}% / {pct(gross_list,20):.0f}%")
        print(f"Gap NET des frais (bps): med {statistics.median(net_list):.2f} | max {max(net_list):.2f}")
        print(f"  polls NET>0 (gross-profitable pre-slippage/gas) : {n_actionable}/{len(net_list)} "
              f"({100.0*n_actionable/len(net_list):.1f}%)")
        if streaks:
            longest = max(streaks)
            print(f"  PERSISTANCE max d'un gap NET>0 : {longest} polls ~ {longest*args.interval:.0f}s "
                  f"(>=2 polls = pas une simple course 1-bloc)")
        else:
            print("  PERSISTANCE : aucun gap NET>0 -> gaps < frais (deja arbitres a la tolerance des frais).")
        print("\nLecture : NET<=0 quasi tout le temps = les ecarts existent mais < frais de pool")
        print("-> deja arbitres, rien a capturer pour un solo a ce niveau (prix mid).")
        print("Un gap NET>0 qui ne dure qu'1 poll = course MEV (perdue par un solo non colocalise).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
