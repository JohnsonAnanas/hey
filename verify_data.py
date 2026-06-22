#!/usr/bin/env python
"""Controle d'integrite des donnees (timing, fraicheur, precision) — lecture seule.

Repond aux questions : teste-t-on en instantane ou dans le temps ? les lectures sont-elles au
MEME bloc ? le RPC est-il a jour / coherent entre fournisseurs ? nos prix sont-ils justes (vs
source externe) ? l'horloge locale est-elle fiable pour horodater ? Analyse aussi le dernier log.
"""
from __future__ import annotations

import csv
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import requests
from web3 import Web3
from eth_abi import encode as abi_encode

from sim.chain import (RPC, addr_from, RPC_CANDIDATES, MULTICALL3,
                       SEL_GETPOOL_BOOL, SEL_RESERVES, SEL_BLOCKNUM)


def gmt(ts: int) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%SZ", time.gmtime(ts))


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    print("=== 1) Hauteur de bloc par RPC public (load-balancer / lag entre fournisseurs) ===")
    H = {}
    for u in [x for x in RPC_CANDIDATES if x]:
        try:
            r = requests.post(u, json={"jsonrpc": "2.0", "id": 1, "method": "eth_blockNumber", "params": []}, timeout=8)
            H[u] = int(r.json()["result"], 16)
            print(f"  {H[u]}  {u}")
        except Exception as e:
            print(f"  KO        {u}  {e!r}")
    if len(H) >= 2:
        print(f"  -> ecart max entre RPC : {max(H.values()) - min(H.values())} blocs "
              f"({'OK, coherents' if max(H.values())-min(H.values())<=2 else 'DIVERGENCE -> un RPC est en retard'})")

    rpc = RPC()
    blk = rpc.w3.eth.get_block("latest")
    now = int(time.time())
    print("\n=== 2) Fraicheur du tip & fiabilite de l'horloge LOCALE ===")
    print(f"  dernier bloc Base : #{blk['number']}  timestamp(chaine) {gmt(blk['timestamp'])}")
    print(f"  horloge LOCALE    :                      {gmt(now)}")
    print(f"  -> delta (local - chaine) : {now - blk['timestamp']:+d} s")
    if abs(now - blk["timestamp"]) > 120:
        print("  !! ALERTE : l'horloge locale ne correspond PAS au temps de la chaine.")
        print("     Consequence : NE JAMAIS horodater les donnees avec l'horloge locale -> utiliser le")
        print("     numero/timestamp de BLOC comme reference temporelle (seule verite point-in-time).")

    print("\n=== 3) Coherence MEME bloc (Multicall3) ===")
    WETH = Web3.to_checksum_address("0x4200000000000000000000000000000000000006")
    USDC = Web3.to_checksum_address("0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913")
    AF = Web3.to_checksum_address("0x420DD381b31aEf6683db6B902084cB0FFECe40Da")
    e0, e1 = (WETH, USDC) if int(WETH, 16) < int(USDC, 16) else (USDC, WETH)
    pool = addr_from(rpc.multicall([(AF, SEL_GETPOOL_BOOL + abi_encode(["address", "address", "bool"], [e0, e1, False]))])[0][1])
    res = rpc.multicall([(MULTICALL3, SEL_BLOCKNUM), (pool, SEL_RESERVES)])
    b = int.from_bytes(res[0][1], "big")
    print(f"  aggregate3 -> getBlockNumber={b} ET getReserves dans 1 SEUL eth_call.")
    print("  => toutes les lectures d'un poll sont au MEME bloc (gaps inter-pools non pollues par le timing). OK.")

    print("\n=== 4) Precision : notre prix DEX vs source externe (Binance) ===")
    d = res[1][1]
    r0, r1 = int.from_bytes(d[0:32], "big"), int.from_bytes(d[32:64], "big")
    our = (r1 / 1e6) / (r0 / 1e18) if e0 == WETH else (r0 / 1e6) / (r1 / 1e18)
    try:
        bz = float(requests.get("https://api.binance.com/api/v3/ticker/price?symbol=ETHUSDT", timeout=8).json()["price"])
        print(f"  notre WETH/USDC (Aerodrome, bloc {b}) : {our:.2f}")
        print(f"  Binance ETHUSDT (live)               : {bz:.2f}")
        print(f"  -> ecart : {(our / bz - 1) * 1e4:+.1f} bps  (= deja un APERCU du gap DEX<->CEX)")
    except Exception as ex:
        print("  Binance KO:", repr(ex))

    print("\n=== 5) Dernier scan : instantane ou periode ? (analyse du log) ===")
    p = Path(__file__).resolve().parent / "data" / "logs" / "mav_multi_base.csv"
    if p.exists():
        rows = list(csv.DictReader(open(p, encoding="utf-8")))
        if rows:
            ts = [r["ts"] for r in rows]
            blocks = sorted({int(r["block"]) for r in rows})
            span_blk = blocks[-1] - blocks[0]
            print(f"  lignes: {len(rows)} | horodatage {ts[0]}..{ts[-1]} | blocs distincts: {len(blocks)} "
                  f"({blocks[0]}..{blocks[-1]} = {span_blk} blocs ~ {span_blk*2}s d'historique reel)")
            moved = {}
            for r in rows:
                moved.setdefault(r["pair"], set()).add(r["gap_bps_liquid"])
            varying = sum(1 for v in moved.values() if len(v) > 1)
            print(f"  paires dont l'ecart a BOUGE pendant le scan : {varying}/{len(moved)}")
            print(f"  -> {'marche quasi STATIQUE : echantillon ~quelques obs, PAS une periode representative.' if varying <= 2 else 'un peu de mouvement, mais fenetre tres courte.'}")
    else:
        print("  (pas de log mav_multi_base.csv)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
