#!/usr/bin/env python
"""Spot-check capturabilite cross-chain — plusieurs tokens, quotes EXECUTABLES Kyber (sans cle).

But : VELVET est non capturable. Est-ce une CLASSE ? On teste l'aller-retour (acheter sur la chaine
PAS CHERE, vendre sur la chaine CHERE) sur quelques candidats recurrents du collecteur. net>0 a taille
utile = exception a creuser ; net<0 partout = la classe entiere est reelle-mais-pas-capturable.

Adresses lues du collecteur (data/collected). Hypothese : meme nb de decimales du token sur les 2
chaines (vrai pour la quasi-totalite ; un resultat absurde le revelerait).

Usage : python spot_check.py
"""
from __future__ import annotations

import sys
import time

import requests

KY = "https://aggregator-api.kyberswap.com/{slug}/api/v1/routes"
HDR = {"Accept": "application/json", "x-client-id": "arb-research"}
SLUG = {"eth": "ethereum", "bsc": "bsc", "arbitrum": "arbitrum", "optimism": "optimism",
        "base": "base", "polygon_pos": "polygon"}
# chaine -> (stable addr, decimales)
STABLE = {
    "eth":         ("0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48", 6),
    "base":        ("0x833589fcd6edb6e08f4c7c32d4f71b54bda02913", 6),
    "arbitrum":    ("0xaf88d065e77c8cc2239327c5edb3a432268e5831", 6),
    "optimism":    ("0x0b2c639c533813f4aa9d7837caf62653d097ff85", 6),
    "polygon_pos": ("0x3c499c542cef5e3811e1192ce70d8cc03d5c3359", 6),
    "bsc":         ("0x55d398326f99059ff775485246999027b3197955", 18),
}
SIZES = [500, 2000]

# (token, lo_chain=pas cher, lo_addr, hi_chain=cher, hi_addr) — recurrents du collecteur
CANDS = [
    ("RDNT", "arbitrum", "0x3082cc23568ea640225c2467653db90e9250aaa0", "bsc", "0xf7de7e8a6bd59ed41a4b5fe50278b3b7f31384df"),
    ("AAVE", "arbitrum", "0xba5ddd1f9d7f570dc94a51479a000e3bce967196", "polygon_pos", "0xd6df932a45c0f255f85145f286ea0b292b21c90b"),
    ("CRVUSD", "eth", "0xf939e0a03fb07f59a73314e73794be0e57ac1b4e", "arbitrum", "0x498bf2b1e120fed3ad3d42ea2165e9b73f99c1e5"),
    ("CTM", "bsc", "0xc8fb80fcc03f699c70ff0cc08c09106288888888", "eth", "0xc8fb80fcc03f699c70ff0cc08c09106288888888"),
]


def route(slug, tin, tout, amount_in_raw):
    try:
        r = requests.get(KY.format(slug=slug),
                         params={"tokenIn": tin, "tokenOut": tout, "amountIn": str(amount_in_raw)},
                         headers=HDR, timeout=25)
        rs = (r.json().get("data") or {}).get("routeSummary")
        return (int(rs["amountOut"]), float(rs.get("amountOutUsd") or 0)) if rs else None
    except Exception:
        return None


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    print("Spot-check capturabilite cross-chain (acheter chaine pas chere -> vendre chaine chere, Kyber)\n")
    print(f"{'token':<8}{'route':<22}{'taille':>8}{'$ recu':>10}{'net':>8}")
    results = []
    for tok, lo, loa, hi, hia in CANDS:
        slo, slo_d = STABLE[lo]; shi, shi_d = STABLE[hi]
        for usd in SIZES:
            leg1 = route(SLUG[lo], slo, loa, usd * 10 ** slo_d)        # stable_lo -> token (achat)
            time.sleep(1.2)
            if not leg1:
                print(f"{tok:<8}{lo+'->'+hi:<22}{'$'+str(usd):>8}  leg1 KO"); continue
            tok_raw, _ = leg1
            leg2 = route(SLUG[hi], hia, shi, tok_raw)                  # token -> stable_hi (vente)
            time.sleep(1.2)
            if not leg2:
                print(f"{tok:<8}{lo+'->'+hi:<22}{'$'+str(usd):>8}  leg2 KO"); continue
            _, y_usd = leg2
            net = (y_usd - usd) / usd * 1e4
            print(f"{tok:<8}{lo+'->'+hi:<22}{'$'+format(usd,','):>8}{y_usd:>9.2f}${net:>+7.0f}b")
            results.append((tok, usd, net))
    pos = [r for r in results if r[2] > 0]
    print("\n" + "=" * 60)
    if not pos:
        print("AUCUN candidat capturable a aucune taille.")
        print("-> CONFIRME : les gaps cross-chain sont une CLASSE reelle-mais-pas-capturable (le gap")
        print("   existe PARCE QUE les pools sont minces ; le slippage le mange). Verdict definitif.")
    else:
        print("EXCEPTION(S) a net>0 :", ", ".join(f"{t} ${s:,} ({n:+.0f}b)" for t, s, n in pos))
        print("-> a creuser : persistance + sens (directionnel vs oscillant) + taille soutenable.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
