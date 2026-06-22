#!/usr/bin/env python
"""Backtest du GAP DEX<->CEX (historique, 1 minute) — sources gratuites, sans cle.

Prix DEX = OHLCV 1m du pool Uniswap-v3 5bps (GeckoTerminal, token = adresse de l'actif) ;
prix CEX = klines 1m Binance (paire USDC). On aligne par minute et on caracterise le GAP NET.

STRUCTURE D'ABORD (cf [[feedback-infrastructure-solid-first]]) — on ne fait confiance qu'a ce qui
passe une PORTE structurelle, et on mesure avec DEUX BORNES honnetes :
  1. Porte d'eligibilite par actif :
     - wrapper 1:1 trustless (WETH=ETH ok ; cbBTC != BTC = wrapper custodial -> ECARTE) ;
     - liquidite/fraicheur : couverture de bougies DEX >= seuil (sinon staleness -> ECARTE).
  2. Double borne :
     - net OPTIMISTE = close-vs-close, apres frais DEX+CEX et un spread CEX assume (borne HAUTE) ;
     - net PLANCHER = optimiste MOINS l'incertitude de timing intra-minute (range high-low des deux
       cotes) -> ce que le gap vaut AU PIRE une fois retire l'artefact "dernier trade non simultane".
  La verite est ENTRE les deux. %actionnable PLANCHER = le chiffre credible.

HONNETETE : mesure l'OPPORTUNITE, pas le PnL capture (exec non-atomique -> test forward/live).
Le LIVE (lecture des 2 prix au MEME instant) reste plus precis pour le gap ; le backtest sert au
SCREENING de la distribution sur des semaines.

Usage : python backtest_gap.py --days 7
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

from sim.chain import RPC, addr_from, SEL_GETPOOL_V3

USDC = Web3.to_checksum_address("0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913")
UNIV3_FACTORY = Web3.to_checksum_address("0x33128a8fC17869897dcE68Ed026d694621f6FDfD")
CEX_FEE = 0.0010          # Binance taker ~10 bps (un cote)
CEX_SPREAD_BPS = 2.0      # spread bid/ask CEX assume (croise une fois) — klines n'ont pas le carnet
FEE_DEX = 0.0005          # UniV3 5bps (meilleure venue d'execution)
MIN_COVERAGE = 0.50       # couverture de bougies DEX minimale pour juger un actif "liquide/frais"
GT = "https://api.geckoterminal.com/api/v2/networks/base/pools"
HEAD = {"User-Agent": "mercor-arb/0", "Accept": "application/json"}

# clean = le token DEX est-il trustless 1:1 avec l'actif CEX ? (WETH=ETH oui ; cbBTC=BTC wrappe custodial non)
ASSETS = [
    {"sym": "ETH",     "token": "0x4200000000000000000000000000000000000006", "binance": "ETHUSDC",     "clean": True},
    {"sym": "BTC",     "token": "0xcbB7C0000aB88B473b1f5aFd9ef808440eed33Bf", "binance": "BTCUSDC",     "clean": False},  # cbBTC = wrapper
    {"sym": "VIRTUAL", "token": "0x0b3e328455c4059EEb9e3f84b5543F74E24e7E1b", "binance": "VIRTUALUSDC", "clean": True},
]


def resolve_pool(rpc: RPC, token: str) -> str | None:
    cd = SEL_GETPOOL_V3 + abi_encode(["address", "address", "uint24"], [Web3.to_checksum_address(token), USDC, 500])
    ok, data = rpc.multicall([(UNIV3_FACTORY, cd)])[0]
    return addr_from(data) if ok else None


def gecko_ohlcv(pool: str, token: str, start_ts: int) -> dict:
    """OHLCV 1m du pool (prix de `token` en USD), remonte jusqu'a start_ts. Retry+backoff sur 429."""
    out, cursor, calls = {}, None, 0
    while calls < 80:
        url = f"{GT}/{pool}/ohlcv/minute?aggregate=1&limit=1000&token={token}"
        if cursor:
            url += f"&before_timestamp={cursor}"
        rows = None
        for attempt in range(5):
            try:
                rows = requests.get(url, headers=HEAD, timeout=20).json()["data"]["attributes"]["ohlcv_list"]
                break
            except Exception:
                time.sleep(12 + attempt * 8)
        if not rows:
            print("    GeckoTerminal : abandon (rate-limit persistant)"); break
        for row in rows:
            out[int(row[0])] = (float(row[1]), float(row[2]), float(row[3]), float(row[4]))
        cursor = min(int(row[0]) for row in rows)
        calls += 1
        if cursor <= start_ts:
            break
        time.sleep(3.2)
    return {t: v for t, v in out.items() if t >= start_ts}


def binance_klines(symbol: str, start_ts: int) -> dict:
    out, cur, calls = {}, start_ts * 1000, 0
    now_ms = int(time.time()) * 1000
    while cur < now_ms and calls < 80:
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=1m&startTime={cur}&limit=1000"
        try:
            ks = requests.get(url, timeout=15).json()
        except Exception as e:
            print(f"    Binance KO: {e!r}"); break
        if not ks:
            break
        for k in ks:
            out[k[0] // 1000] = (float(k[1]), float(k[2]), float(k[3]), float(k[4]))
        cur = ks[-1][0] + 60_000
        calls += 1
    return out


def gaps(dex: tuple, cex: tuple) -> tuple[float, float]:
    """(net_optimiste, net_plancher) en bps. dex/cex = (o,h,l,c)."""
    dc, cc = dex[3], cex[3]
    sell = dc * (1 - FEE_DEX) - cc * (1 + CEX_FEE)
    buy = cc * (1 - CEX_FEE) - dc * (1 + FEE_DEX)
    opt = max(sell, buy) / dc * 1e4 - CEX_SPREAD_BPS                 # borne HAUTE (close-vs-close)
    timing = ((dex[1] - dex[2]) + (cex[1] - cex[2])) / cc * 1e4      # incertitude intra-minute (range)
    return opt, opt - timing                                         # plancher = opt - timing


def episodes(flags: list) -> tuple[int, int]:
    n, run, mx = 0, 0, 0
    for a in flags:
        if a:
            if run == 0:
                n += 1
            run += 1; mx = max(mx, run)
        else:
            run = 0
    return n, mx


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="Backtest du gap DEX<->CEX (1m, historique, porte structurelle).")
    ap.add_argument("--days", type=float, default=7.0)
    args = ap.parse_args()
    start_ts = int(time.time()) - int(args.days * 86400)
    window_min = args.days * 1440

    rpc = RPC()
    out_dir = Path(__file__).resolve().parent / "data" / "logs"
    out_dir.mkdir(parents=True, exist_ok=True)
    log = out_dir / "backtest_gap.csv"
    f = open(log, "w", newline="", encoding="utf-8")
    w = csv.writer(f)
    w.writerow(["minute_ts", "asset", "clean", "dex_close", "cex_close", "raw_bps", "net_opt_bps", "net_floor_bps", "act_floor"])

    print(f"\nBacktest gap DEX<->CEX | {args.days:.0f}j | frais DEX {FEE_DEX*1e4:.0f}+CEX {CEX_FEE*1e4:.0f}bps + spread {CEX_SPREAD_BPS:.0f}bps")
    rows_out = []
    for i, a in enumerate(ASSETS):
        if i:
            time.sleep(8)
        pool = resolve_pool(rpc, a["token"])
        if not pool:
            print(f"  {a['sym']:<8} : pas de pool UniV3-5 -> saute"); continue
        print(f"  {a['sym']:<8} pool {pool[:12]}… DEX+CEX…")
        dex = gecko_ohlcv(pool, Web3.to_checksum_address(a["token"]), start_ts)
        cex = binance_klines(a["binance"], start_ts)
        common = sorted(set(dex) & set(cex))
        coverage = len(common) / window_min if window_min else 0
        if not common:
            print(f"    aucune minute commune"); continue
        opt_l, flo_l, act_l = [], [], []
        for t in common:
            o, fl = gaps(dex[t], cex[t])
            opt_l.append(o); flo_l.append(fl); act_l.append(fl > 0)
            w.writerow([t, a["sym"], int(a["clean"]), f"{dex[t][3]:.6f}", f"{cex[t][3]:.6f}",
                        f"{(dex[t][3]/cex[t][3]-1)*1e4:.2f}", f"{o:.2f}", f"{fl:.2f}", int(fl > 0)])
        f.flush()
        # porte structurelle
        reasons = []
        if not a["clean"]:
            reasons.append("wrapper custodial (token DEX != actif CEX)")
        if coverage < MIN_COVERAGE:
            reasons.append(f"couverture {coverage*100:.0f}% < {MIN_COVERAGE*100:.0f}% (staleness/pool fin)")
        n_ep, max_dur = episodes(act_l)
        os_ = sorted(opt_l)
        pct_opt = 100 * sum(1 for x in opt_l if x > 0) / len(opt_l)
        pct_flo = 100 * sum(act_l) / len(act_l)
        rows_out.append({"sym": a["sym"], "n": len(common), "cov": coverage, "clean": not reasons, "reasons": reasons,
                         "med": statistics.median(opt_l), "p90": os_[int(0.9*(len(os_)-1))], "max": max(opt_l),
                         "pct_opt": pct_opt, "pct_flo": pct_flo, "floor_max": max(flo_l), "ep": n_ep, "dur": max_dur})
        print(f"    {len(common)} min (couverture {coverage*100:.0f}%).")
    f.close()

    def show(r):
        return (f"  {r['sym']:<8} {r['n']:>6}min cov{r['cov']*100:>3.0f}% | net OPT med {r['med']:+5.1f} p90 {r['p90']:+5.1f} "
                f"max {r['max']:+5.1f} | actionnable OPT {r['pct_opt']:.1f}% / PLANCHER {r['pct_flo']:.1f}% "
                f"| floor_max {r['floor_max']:+.0f} | epis {r['ep']} dur {r['dur']}m")

    clean = [r for r in rows_out if r["clean"]]
    flagged = [r for r in rows_out if not r["clean"]]
    print("\n" + "=" * 80)
    print(f"SYNTHESE — porte structurelle + double borne  (log -> {log})")
    print("\nACTIFS PROPRES (wrapper 1:1 + liquides) — le seul signal credible :")
    for r in clean:
        print(show(r))
    if not clean:
        print("  (aucun actif propre sur ce panier)")
    print("\nECARTES (artefact — NE PAS prendre les chiffres au pied de la lettre) :")
    for r in flagged:
        print(show(r) + "  <<")
        print(f"           raison : {', '.join(r['reasons'])}")
    print("\nLecture : 'OPT' = borne HAUTE (close-vs-close, optimiste). 'PLANCHER' = apres retrait de")
    print("l'incertitude de timing intra-minute = le %actionnable CREDIBLE. La verite est entre les deux.")
    print("Rappel : opportunite, pas PnL capture. Le LIVE (meme instant) reste plus precis pour le gap.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
