#!/usr/bin/env python
"""Cout de CAPTURE du gap cross-chain VELVET — via quotes EXECUTABLES KyberSwap (sans cle).

Le gap median ~23bps oscille. Reste-t-il quelque chose net du slippage REEL ? On simule la capture
exacte avec l'agregateur Kyber (route a travers TOUTE la liquidite reelle, pas un seul pool) :
  1) ACHETER $X de VELVET sur base (USDC -> VELVET)  -> on recoit V VELVET
  2) VENDRE ces V VELVET sur bsc (VELVET -> USDT)     -> on recoit $Y
P&L = $Y - $X = (gap) - (slippage+frais des 2 legs). net_bps = (Y-X)/X*1e4. >0 = capturable a cette
taille. C'est le vrai test executable (modele inventaire : on tient V VELVET des 2 cotes).

Usage : python capture_cost.py
"""
from __future__ import annotations

import sys
import time

import requests

KY = "https://aggregator-api.kyberswap.com/{chain}/api/v1/routes"
HDR = {"Accept": "application/json", "x-client-id": "arb-research"}

USDC_BASE = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"   # d6
VELVET_BASE = "0xbf927b841994731c573bdf09ceb0c6b0aa887cdd"  # d18
VELVET_BSC = "0x8b194370825e37b33373e74a41009161808c1488"   # d18
USDT_BSC = "0x55d398326f99059ff775485246999027b3197955"     # d18

SIZES = [200, 500, 2000, 10000]
GAP_MEDIAN, GAP_P75, GAP_P90 = 23.0, 39.0, 78.0


def route(chain, tin, tout, amount_in_raw):
    """(amountOut_raw, amountInUsd, amountOutUsd) ou None."""
    try:
        r = requests.get(KY.format(chain=chain),
                         params={"tokenIn": tin, "tokenOut": tout, "amountIn": str(amount_in_raw)},
                         headers=HDR, timeout=25)
        j = r.json()
        rs = (j.get("data") or {}).get("routeSummary")
        if not rs:
            return None
        return int(rs["amountOut"]), float(rs.get("amountInUsd") or 0), float(rs.get("amountOutUsd") or 0)
    except Exception as e:
        print("  route KO:", str(e)[:70]); return None


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    print("Cout de capture VELVET via quotes EXECUTABLES Kyber (base buy + bsc sell)\n")
    print(f"{'taille':>9} | {'VELVET recu':>12} {'$ recu bsc':>11} {'P&L brut':>9} | "
          f"{'net@med':>8} {'net@p75':>8} {'net@p90':>8}  (gap median 23 / 39 / 78)")
    any_ok = False
    for usd in SIZES:
        leg1 = route("base", USDC_BASE, VELVET_BASE, usd * 10 ** 6)     # USDC d6 in
        if not leg1:
            print(f"${usd:>8,} | leg base KO"); time.sleep(1.5); continue
        v_raw, in_usd_b, out_usd_b = leg1
        time.sleep(1.2)
        leg2 = route("bsc", VELVET_BSC, USDT_BSC, v_raw)               # VELVET d18 in
        if not leg2:
            print(f"${usd:>8,} | leg bsc KO (V={v_raw/1e18:.1f})"); time.sleep(1.5); continue
        y_raw, in_usd_x, out_usd_x = leg2
        x = in_usd_b or usd                 # $ depense (USDC ~ $usd)
        y = out_usd_x                        # $ recu cote bsc
        pnl = y - x
        net_bps = pnl / x * 1e4
        # net@gap = ce que tu gagnes si le gap vaut GAP_X (le P&L Kyber inclut DEJA le gap instantane,
        # donc net_bps EST deja le net au gap actuel ; on montre aussi vs les quantiles pour reference)
        print(f"${usd:>8,} | {v_raw/1e18:>11.1f}V {y:>10.2f}$ {pnl:>+8.2f}$ | "
              f"{net_bps:>+7.0f}b", end="")
        print(f" {'(net actuel)':>20}")
        if net_bps > 0:
            any_ok = True
        time.sleep(1.2)

    print("\nLecture : 'net actuel' = P&L reel (en bps) de l'aller-retour acheter-base/vendre-bsc a cette")
    print("taille, MAINTENANT (inclut le gap instantane + tout le slippage + frais, route Kyber reelle).")
    print(">0 = capturable a cette taille ; <0 = le slippage mange le gap. Le gap oscille (median 23bps) :")
    print("un net positif a taille utile = vraie piste ; negatif partout = reel mais pas capturable solo.")
    if not any_ok:
        print("\n-> Aucune taille rentable : VELVET est un gap REEL mais NON capturable (slippage > gap).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
