#!/usr/bin/env python
"""Filet LARGE cross-chain / cross-protocole — la ou vit "differences de liquidite enormes d'un
protocole a l'autre" (axe jamais explore : on n'avait teste que Base / majors / v2).

Via GeckoTerminal (gratuit, sans cle, ~150 chaines) : tire les TOP pools par liquidite sur plusieurs
chaines, extrait le prix USD de CHAQUE token (base ET quote) + la profondeur du pool, garde par
(token, chaine) le pool le plus profond, puis mesure la DISLOCATION du MEME token entre chaines,
net de 2 swaps (+gas). Classe par gap x min-liquidite (esprit MAV : liquidite x ecart).

Le jeu cross-chain = INVENTAIRE/BRIDGE (un solo PATIENT absorbe la friction du bridge ; on tient du
stock des 2 cotes, on capte le gap quand il s'ouvre, on reequilibre par bridge de temps en temps ->
cout du bridge AMORTI). Pas une course de vitesse. C'est l'angle accessible solo.

Integrite (anti-mirage, lecons accumulees) :
- min-liq REQUISE des deux cotes (tue les prix stale de pools fins) ;
- match par SYMBOLE -> risque de collision (memes lettres, tokens differents) : un gap absurde
  (>--collision-bps) est liste A PART comme SUSPECT, pas comme opportunite ; on montre noms+adresses ;
- prix GeckoTerminal = oracle agrege -> un vrai trade exige une QUOTE executable (1inch/0x par
  chaine) ; ceci SCREENE les candidats, ne prouve pas la capture.

Usage : python scan_crosschain.py --pages 8 --min-liq 200000 --cost-bps 60
"""
from __future__ import annotations

import argparse
import sys
import time
from collections import defaultdict

import requests

BASE = "https://api.geckoterminal.com/api/v2"
# slugs GeckoTerminal
CHAINS = ["eth", "arbitrum", "base", "optimism", "bsc", "polygon_pos", "avax"]
HEADERS = {"Accept": "application/json", "User-Agent": "arb-research/1.0"}


def get(url: str, tries: int = 5):
    for i in range(tries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=25)
            if r.status_code == 429:
                time.sleep(3 + 2 * i); continue
            r.raise_for_status()
            return r.json()
        except Exception:
            time.sleep(2 + i)
    return None


def collect_chain(net: str, pages: int, min_liq: float, min_vol: float) -> dict:
    """token -> (price, liq, addr, name) du pool le plus profond ACTIF (vol24h>=min_vol) sur `net`.
    Filtre volume = anti prix STALE : un pool profond mais NON-trade cote un prix perime (lecon CTM/VELVET :
    pool eth $29M / solana $170M avec vol24h=$0 -> faux gap geant). Un prix de confiance = profond ET frais."""
    best = {}
    for p in range(1, pages + 1):
        url = f"{BASE}/networks/{net}/pools?include=base_token,quote_token&page={p}"
        j = get(url)
        if not j or "data" not in j:
            break
        # index des tokens inclus : id -> (symbol, name, address)
        inc = {}
        for it in j.get("included", []):
            a = it.get("attributes", {})
            inc[it.get("id")] = (a.get("symbol"), a.get("name"), a.get("address"))
        for pool in j["data"]:
            a = pool.get("attributes", {})
            rel = pool.get("relationships", {})
            liq = float(a.get("reserve_in_usd") or 0)
            vol = float((a.get("volume_usd") or {}).get("h24") or 0)
            if liq < min_liq or vol < min_vol:        # profond ET actif, sinon le prix ment
                continue
            for side, price_key in (("base_token", "base_token_price_usd"),
                                    ("quote_token", "quote_token_price_usd")):
                tid = rel.get(side, {}).get("data", {}).get("id")
                sym, name, addr = inc.get(tid, (None, None, None))
                price = a.get(price_key)
                if not sym or price is None:
                    continue
                try:
                    price = float(price)
                except (TypeError, ValueError):
                    continue
                if price <= 0:
                    continue
                key = sym.upper()
                if key not in best or liq > best[key][1]:
                    best[key] = (price, liq, vol, addr, name)
        time.sleep(2.2)   # free tier ~30/min
    return best


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="Scan large cross-chain des dislocations de prix.")
    ap.add_argument("--pages", type=int, default=8, help="pages de pools/chaine (20/pool)")
    ap.add_argument("--min-liq", type=float, default=200_000.0, help="liquidite pool min (USD) des 2 cotes")
    ap.add_argument("--min-vol", type=float, default=50_000.0, help="volume 24h min du pool (anti prix stale)")
    ap.add_argument("--cost-bps", type=float, default=60.0, help="cout aller (2 swaps) en bps a retrancher")
    ap.add_argument("--collision-bps", type=float, default=2500.0, help="au-dela = collision de symbole probable")
    ap.add_argument("--chains", default=",".join(CHAINS))
    args = ap.parse_args()
    chains = [c.strip() for c in args.chains.split(",") if c.strip()]

    per_chain = {}
    for net in chains:
        d = collect_chain(net, args.pages, args.min_liq, args.min_vol)
        per_chain[net] = d
        print(f"  {net:<12} : {len(d)} tokens (liq >= ${args.min_liq/1e3:.0f}k ET vol24h >= ${args.min_vol/1e3:.0f}k)")

    # token -> {chain: (price, liq, vol, addr, name)}
    tok = defaultdict(dict)
    for net, d in per_chain.items():
        for sym, v in d.items():
            tok[sym][net] = v

    cands, suspects = [], []
    for sym, chmap in tok.items():
        if len(chmap) < 2:
            continue
        items = [(net, *v) for net, v in chmap.items()]              # (net, price, liq, vol, addr, name)
        hi = max(items, key=lambda x: x[1]); lo = min(items, key=lambda x: x[1])
        if lo[1] <= 0:
            continue
        gap_bps = (hi[1] - lo[1]) / lo[1] * 1e4
        net_bps = gap_bps - args.cost_bps
        min_liq = min(hi[2], lo[2])
        row = (net_bps, gap_bps, sym, lo[0], lo[1], hi[0], hi[1], min_liq, lo[5], hi[5], lo[4], hi[4])
        if gap_bps >= args.collision_bps:
            suspects.append(row)
        elif net_bps > 0:
            cands.append(row)

    cands.sort(key=lambda r: -(r[0] * r[7]))   # net_bps x min_liq (MAV-like)
    suspects.sort(reverse=True)
    print("\n" + "=" * 96)
    print(f"DISLOCATIONS CROSS-CHAIN (meme symbole, net de {args.cost_bps:.0f}bps de swaps) — "
          f"classees par net_bps x min-liq")
    print(f"  {'token':<10}{'achat@':<10}{'vente@':<10}{'gap':>8}{'net':>8}{'min-liq':>11}  (prix bas -> haut)")
    if not cands:
        print("  Aucun candidat net>0 avec liq suffisante des 2 cotes.")
    for net_bps, gap, sym, lc, lp, hc, hp, mliq, ln, hn, la, ha in cands[:25]:
        print(f"  {sym:<10}{lc:<10}{hc:<10}{gap:>+7.0f}b{net_bps:>+7.0f}b{mliq/1e3:>9.0f}k  "
              f"${lp:.4g} -> ${hp:.4g}")

    print(f"\nSUSPECTS (gap > {args.collision_bps:.0f}bps = collision de symbole / token different PROBABLE "
          f"-> a verifier, PAS une opportunite) : {len(suspects)}")
    for net_bps, gap, sym, lc, lp, hc, hp, mliq, ln, hn, la, ha in suspects[:8]:
        print(f"  {sym:<10}{lc}:{ln or '?'} (${lp:.4g}, {la}) vs {hc}:{hn or '?'} (${hp:.4g}, {ha})")

    print("\nLecture : un candidat RECURRENT a gap net>0 ET liq solide des 2 cotes = a confirmer en QUOTE")
    print("executable (1inch/0x par chaine) puis en PERSISTANCE (re-scan). Rappel du theoreme empirique :")
    print("plus le gap est gros, plus il est probablement VERROUILLE (bridge lent/risque = pourquoi il")
    print("persiste). Le vrai filon = gap modere, liquide des 2 cotes, tenable en INVENTAIRE.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
