#!/usr/bin/env python
"""Observatoire DEX<->CEX MULTI-ACTIFS, continu (Base <-> Binance), LECTURE SEULE.

Pour chaque actif (ETH, BTC via cbBTC, AERO...) : lit le prix DEX (Uniswap-v3 5/30 bps via
sqrtPriceX96 + Aerodrome v2) et le carnet Binance (bid/ask), calcule le GAP ACTIONNABLE net des
frais (DEX + CEX), et caracterise sa DISTRIBUTION + sa PERSISTANCE dans le TEMPS (le "decay time"
de R3). Synthese periodique pour un run LONG. Sur la couche d'integrite (fraicheur RPC + quorum,
bloc = reference temps, abstain sur reorg / carnet indispo, couverture). AUCUNE execution.

Anti-basis : on compare au pair Binance en **USDC** quand il existe (meme devise que le DEX) pour
isoler le vrai gap de l'actif ; sinon USDT et on FLAGGE le basis (transparence d'integrite).
Rappel : DEX<->CEX n'est PAS atomique -> le gap net de frais est NECESSAIRE mais pas suffisant
(cout d'inventaire + risque d'execution a ajouter). Optimal-sizing (MAV USD) = raffinement suivant.
"""
from __future__ import annotations

import argparse
import csv
import os
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import requests
from web3 import Web3
from eth_abi import encode as abi_encode

from sim.chain import (RPC, addr_from, uint_from, SEL_GETPOOL_BOOL, SEL_GETPOOL_V3, SEL_SLOT0,
                       SEL_RESERVES, SEL_GETFEE)
from sim.integrity import poll_meta, poll_should_abstain

USDC = Web3.to_checksum_address("0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913")
USDC_DEC = 6
UNIV3_FACTORY = Web3.to_checksum_address("0x33128a8fC17869897dcE68Ed026d694621f6FDfD")
AERO_FACTORY = Web3.to_checksum_address("0x420DD381b31aEf6683db6B902084cB0FFECe40Da")
CEX_FEE = 0.0010   # Binance taker ~10 bps (un cote)

ASSETS = [
    {"sym": "ETH",  "token": "0x4200000000000000000000000000000000000006", "dec": 18, "binance": "ETHUSDC",  "basis": False},
    {"sym": "BTC",  "token": "0xcbB7C0000aB88B473b1f5aFd9ef808440eed33Bf", "dec": 8,  "binance": "BTCUSDC",  "basis": False},
    {"sym": "VIRTUAL", "token": "0x0b3e328455c4059EEb9e3f84b5543F74E24e7E1b", "dec": 18, "binance": "VIRTUALUSDC", "basis": False},
]
# (venue, kind, tier_v3, fee) ; fee Aerodrome = lu on-chain ; fee v3 = fee-tier (defini par le contrat)
DEX_TIERS = [("UniV3-5", "v3", 500, 0.0005), ("UniV3-30", "v3", 3000, 0.0030), ("Aerodrome", "v2", None, None)]


def resolve(rpc: RPC) -> list[dict]:
    specs, calls = [], []
    for a in ASSETS:
        tok = Web3.to_checksum_address(a["token"])
        asset_is_t0 = int(tok, 16) < int(USDC, 16)
        for (name, kind, tier, fee) in DEX_TIERS:
            if kind == "v3":
                cd = SEL_GETPOOL_V3 + abi_encode(["address", "address", "uint24"], [tok, USDC, tier])
                fac = UNIV3_FACTORY
            else:
                cd = SEL_GETPOOL_BOOL + abi_encode(["address", "address", "bool"], [tok, USDC, False])
                fac = AERO_FACTORY
            specs.append({"asset": a["sym"], "venue": name, "kind": kind, "fee": fee,
                          "asset_dec": a["dec"], "asset_is_t0": asset_is_t0, "binance": a["binance"], "basis": a["basis"]})
            calls.append((fac, cd))
    res = rpc.multicall(calls)
    pools = [{**s, "address": addr_from(d)} for s, (ok, d) in zip(specs, res) if ok and addr_from(d)]
    # frais Aerodrome on-chain (pas de fallback muet)
    aero = [p for p in pools if p["kind"] == "v2"]
    if aero:
        rf = rpc.multicall([(AERO_FACTORY, SEL_GETFEE + abi_encode(["address", "bool"], [Web3.to_checksum_address(p["address"]), False])) for p in aero])
        for p, (ok, d) in zip(aero, rf):
            rate = (uint_from(d) or 0) / 10_000.0 if ok else None
            p["fee"] = rate if (rate and 0 < rate < 0.05) else None
    pools = [p for p in pools if p["fee"] is not None]
    by_asset = {}
    for p in pools:
        by_asset.setdefault(p["asset"], []).append(p)
    for a in ASSETS:
        ps = by_asset.get(a["sym"], [])
        tag = f" [BASIS {a['binance']} = USDT, pas USDC]" if a["basis"] else ""
        print(f"  {a['sym']:<4} vs Binance {a['binance']}{tag} : " +
              (", ".join(f"{p['venue']}({p['fee']*1e4:.0f}bps)" for p in ps) or "aucun pool"))
    return pools


def dex_price(kind: str, data: bytes, asset_dec: int, asset_is_t0: bool) -> float | None:
    """Prix USDC par ACTIF, orientation generique (token0 = adresse la plus basse)."""
    if not data or len(data) < 32:
        return None
    if kind == "v3":
        sqrtP = uint_from(data[0:32])
        if not sqrtP:
            return None
        raw = (sqrtP / (2 ** 96)) ** 2                       # token1 par token0 (brut)
        dec0, dec1 = (asset_dec, USDC_DEC) if asset_is_t0 else (USDC_DEC, asset_dec)
        h = raw * (10 ** (dec0 - dec1))                      # token1 par token0 (humain)
        return h if asset_is_t0 else (1.0 / h if h else None)
    if len(data) < 64:
        return None
    r0, r1 = uint_from(data[0:32]), uint_from(data[32:64])
    asset_raw, usdc_raw = (r0, r1) if asset_is_t0 else (r1, r0)
    return (usdc_raw / 10 ** USDC_DEC) / (asset_raw / 10 ** asset_dec) if asset_raw else None


def binance_book(symbol: str):
    try:
        j = requests.get(f"https://api.binance.com/api/v3/ticker/bookTicker?symbol={symbol}", timeout=6).json()
        return float(j["bidPrice"]), float(j["askPrice"])
    except Exception:
        return None


def net_gap_bps(dex_mid: float, bid: float, ask: float, fee_dex: float):
    sell = dex_mid * (1 - fee_dex) - ask * (1 + CEX_FEE)
    buy = bid * (1 - CEX_FEE) - dex_mid * (1 + fee_dex)
    best, direction = (sell, "sell_DEX->CEX") if sell >= buy else (buy, "buy_DEX<-CEX")
    return best / dex_mid * 1e4, direction


def synth(gaps, best_streak, pools, blocks_seen, n_abstain, interval, final=False):
    print("\n" + "=" * 72)
    head = "SYNTHESE FINALE" if final else "SYNTHESE PARTIELLE"
    if blocks_seen:
        lo, hi = min(blocks_seen), max(blocks_seen)
        court = "  — encore court" if len(blocks_seen) < 30 else ""
        print(f"{head} | COUVERTURE {len(blocks_seen)} blocs (~{(hi-lo)*2}s){court} | abstentions {n_abstain}")
    seen = set()
    for p in pools:
        key = (p["asset"], p["venue"])
        if key in seen:
            continue
        seen.add(key)
        g = gaps.get(key, [])
        if not g:
            continue
        gs = sorted(g)
        p90 = gs[int(0.9 * (len(g) - 1))]
        pct = 100.0 * sum(1 for x in g if x > 0) / len(g)
        flag = " [basis USDT]" if p["basis"] else ""
        print(f"  {p['asset']:<4} {p['venue']:<10} (fee {p['fee']*1e4:.0f}bps){flag} : med {statistics.median(g):+6.1f} | "
              f"p90 {p90:+6.1f} | max {max(g):+6.1f} bps | actionable {pct:4.0f}% | persist max {best_streak.get(key,0)}")


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="Observatoire DEX<->CEX multi-actifs continu (lecture seule).")
    ap.add_argument("--seconds", type=float, default=7200.0, help="duree (defaut 2h ; mettre grand pour du continu)")
    ap.add_argument("--interval", type=float, default=5.0)
    ap.add_argument("--synth-every", type=int, default=75, help="synthese partielle tous les N polls (~5min)")
    args = ap.parse_args()

    rpc = RPC()
    print("Resolution des pools DEX par actif :")
    pools = resolve(rpc)
    if not pools:
        print("Aucun pool DEX exploitable.", file=sys.stderr)
        return 1

    # Validation du carnet CEX : ecarter tout actif sans reference Binance (sinon abstention polluante).
    bin_by_asset = {a["sym"]: a["binance"] for a in ASSETS}
    ok_assets = set()
    for sym in {p["asset"] for p in pools}:
        if binance_book(bin_by_asset[sym]) is not None:
            ok_assets.add(sym)
        else:
            print(f"  [ecarte] {sym} : pas de carnet Binance {bin_by_asset[sym]} (aucune reference CEX)")
    pools = [p for p in pools if p["asset"] in ok_assets]
    if not pools:
        print("Aucun actif avec reference CEX exploitable.", file=sys.stderr)
        return 1

    out_dir = Path(__file__).resolve().parent / "data" / "logs"
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / "dex_cex_multi.csv"
    f = open(log_path, "w", newline="", encoding="utf-8")
    w = csv.writer(f)
    w.writerow(["ts", "block", "block_ts", "fresh_ok", "n_sources", "asset", "binance_sym", "basis_usdt",
                "venue", "dex_mid", "bin_bid", "bin_ask", "raw_bps", "net_bps", "direction", "status"])

    gaps, streak, best_streak = {}, {}, {}
    blocks_seen, n_abstain, n_poll = set(), 0, 0
    t_end = time.time() + args.seconds
    print(f"\nCollecteur continu : {args.seconds:.0f}s, poll {args.interval:.1f}s, {len(pools)} pools / {len(ASSETS)} actifs. "
          f"Synthese tous les {args.synth_every} polls. Ctrl-C pour stopper.\n")
    try:
        while time.time() < t_end:
            t_poll = time.time()
            calls = [(Web3.to_checksum_address(p["address"]), SEL_SLOT0 if p["kind"] == "v3" else SEL_RESERVES) for p in pools]
            try:
                block, block_ts, res, fresh = rpc.read_block(calls)
            except Exception as e:
                print(f"poll KO : {e!r}"); time.sleep(args.interval); continue
            meta = poll_meta(fresh)
            ab = poll_should_abstain(fresh)
            if ab:
                n_abstain += 1
                print(f"[{time.strftime('%H:%M:%S')} blk={block}] ABSTAIN : {ab}")
                time.sleep(max(0.0, args.interval - (time.time() - t_poll))); continue
            books = {a["binance"]: binance_book(a["binance"]) for a in ASSETS}
            if block:
                blocks_seen.add(block)
            n_poll += 1
            best_by_asset = {}
            for p, (ok, data) in zip(pools, res):
                book = books.get(p["binance"])
                mid = dex_price(p["kind"], data, p["asset_dec"], p["asset_is_t0"]) if ok else None
                if mid is None or book is None:
                    w.writerow([time.strftime("%H:%M:%S"), block, block_ts, meta["fresh_ok"], meta["n_sources"],
                                p["asset"], p["binance"], p["basis"], p["venue"], "", "", "", "", "", "", "ABSTAIN_data"])
                    continue
                bid, ask = book
                raw_bps = (mid / ((bid + ask) / 2) - 1) * 1e4
                net_bps, direction = net_gap_bps(mid, bid, ask, p["fee"])
                key = (p["asset"], p["venue"])
                gaps.setdefault(key, []).append(net_bps)
                if net_bps > 0:
                    streak[key] = streak.get(key, 0) + 1
                    best_streak[key] = max(best_streak.get(key, 0), streak[key])
                else:
                    streak[key] = 0
                status = "ACTIONABLE" if net_bps > 0 else "no_arb"
                w.writerow([time.strftime("%H:%M:%S"), block, block_ts, meta["fresh_ok"], meta["n_sources"],
                            p["asset"], p["binance"], p["basis"], p["venue"], f"{mid:.4f}", bid, ask,
                            f"{raw_bps:.2f}", f"{net_bps:.2f}", direction, status])
                if net_bps > best_by_asset.get(p["asset"], (-1e9, ""))[0]:
                    best_by_asset[p["asset"]] = (net_bps, p["venue"])
            f.flush()
            summary = "  ".join(f"{a}:{v[1]}={v[0]:+.1f}" for a, v in best_by_asset.items())
            print(f"[{time.strftime('%H:%M:%S')} blk={block}] meilleur net gap/actif: {summary}")
            if n_poll % args.synth_every == 0:
                synth(gaps, best_streak, pools, blocks_seen, n_abstain, args.interval)
            time.sleep(max(0.0, args.interval - (time.time() - t_poll)))
    except KeyboardInterrupt:
        print("\n(interrompu)")
    finally:
        f.close()
    synth(gaps, best_streak, pools, blocks_seen, n_abstain, args.interval, final=True)
    print("\nLecture : net gap > 0 = divergence DEX/CEX au-dela des frais (reste le risque inventaire/execution,")
    print("non atomique). Le signal vit dans la DISTRIBUTION + la PERSISTANCE en volatilite, pas dans le calme.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
