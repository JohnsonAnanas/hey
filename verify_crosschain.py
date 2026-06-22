#!/usr/bin/env python
"""Verification CIBLEE d'un candidat cross-chain (avant toute excitation).

Pour chaque symbole : via GeckoTerminal search, liste par CHAINE le pool le plus profond, et imprime
de quoi TRANCHER les 3 questions :
  1. MEME token ? -> nom + adresse par chaine (si noms/adresses sans lien -> COLLISION de symbole) ;
  2. prix FRAIS ? -> volume 24h + nb tx 24h (si le cote 'cher' ne trade ~pas -> prix STALE, mirage) ;
  3. capturable ? -> a juger ensuite (pont canonique = inventaire ; sinon verrouille).

Usage : python verify_crosschain.py CTM VELVET LINK
"""
from __future__ import annotations

import sys
import time
from collections import defaultdict

import requests

BASE = "https://api.geckoterminal.com/api/v2"
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


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    syms = [s.upper() for s in sys.argv[1:]] or ["CTM"]
    for sym in syms:
        j = get(f"{BASE}/search/pools?query={sym}&page=1")
        print("\n" + "=" * 92)
        print(f"VERIFICATION : {sym}")
        if not j or "data" not in j:
            print("  (pas de reponse)"); continue
        # search ne remplit ni 'included' ni la rel network -> tout est dans l'id (prefixe reseau) et
        # le nom du pool ("BASE / QUOTE"). On parse a la main.
        bychain = defaultdict(list)
        for pool in j["data"]:
            a = pool.get("attributes", {})
            rel = pool.get("relationships", {})
            pid = pool.get("id", "")
            net = pid.split("_", 1)[0] if "_" in pid else "?"
            dex = (rel.get("dex", {}).get("data", {}) or {}).get("id", "?")
            pname = a.get("name") or ""
            parts = [x.strip() for x in pname.split("/")]
            liq = float(a.get("reserve_in_usd") or 0)
            vol = float((a.get("volume_usd") or {}).get("h24") or 0)
            tx = (a.get("transactions") or {}).get("h24") or {}
            ntx = (tx.get("buys") or 0) + (tx.get("sells") or 0)
            sides = [("base_token", "base_token_price_usd", 0), ("quote_token", "quote_token_price_usd", 1)]
            for side, pk, pos in sides:
                if pos >= len(parts) or parts[pos].upper() != sym:
                    continue
                tid = (rel.get(side, {}).get("data", {}) or {}).get("id", "")
                addr = tid.split("_", 1)[1] if "_" in tid else tid
                price = a.get(pk)
                try:
                    price = float(price) if price is not None else None
                except (TypeError, ValueError):
                    price = None
                if price and price > 0:
                    bychain[net].append((liq, price, vol, ntx, sym, addr, dex, pname))
        if len(bychain) < 1:
            print("  (aucun pool exploitable)"); continue
        rows = []
        for net, lst in bychain.items():
            liq, price, vol, ntx, name, addr, dex, pname = max(lst, key=lambda x: x[0])
            rows.append((net, price, liq, vol, ntx, name, addr, dex, pname))
        rows.sort(key=lambda r: r[1])  # par prix
        for net, price, liq, vol, ntx, name, addr, dex, pname in rows:
            print(f"  {net:<13} ${price:<12.6g} liq ${liq/1e3:>8.0f}k  vol24h ${vol/1e3:>8.0f}k  tx24h {ntx:>5}  "
                  f"[{dex}] {pname}")
            print(f"                name='{name}'  addr={addr}")
        if len(rows) >= 2:
            lo, hi = rows[0], rows[-1]
            gap = (hi[1] - lo[1]) / lo[1] * 1e4
            same_addr = lo[6] and hi[6] and lo[6].lower() == hi[6].lower()
            print(f"  -> gap {gap:+.0f}bps ({lo[0]} -> {hi[0]}). "
                  f"meme adresse ? {'OUI' if same_addr else 'NON (chaines differentes -> normal si pont)'} ; "
                  f"noms identiques ? {'OUI' if lo[5] == hi[5] else 'NON -> COLLISION PROBABLE'}")
            if hi[3] < 1 or hi[4] < 5:
                print(f"  -> cote CHER ({hi[0]}) ~PAS DE VOLUME 24h -> prix STALE = mirage probable.")
        time.sleep(1.5)
    print("\nVerdict a tirer : noms differents = collision (rejeter) ; cote cher sans volume = stale")
    print("(rejeter) ; meme projet + 2 cotes actifs + gap qui PERSISTE = vrai candidat (puis quote 1inch).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
