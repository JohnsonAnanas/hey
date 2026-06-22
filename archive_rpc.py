#!/usr/bin/env python
"""Couche d'endpoints ARCHIVE par chaine : Alchemy (cle dans .env) + fallbacks GRATUITS sans cle.

Rotation = repartir le budget + robustesse (si un endpoint tombe/limite, on passe au suivant).
La cle ALCHEMY n'est JAMAIS imprimee ni loggee (redaction systematique).

Self-test : python archive_rpc.py   (montre, par chaine, quels endpoints repondent en archive)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import requests

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / ".env")
except Exception:
    pass

ALCHEMY_KEY = os.environ.get("ALCHEMY_KEY", "").strip()

# chaine -> (chainId, sous-domaine Alchemy, [fallbacks archive sans cle, valides par archive_probe])
CHAINS = {
    "eth":      (1,     "eth-mainnet",     ["https://eth.drpc.org"]),
    "base":     (8453,  "base-mainnet",    ["https://mainnet.base.org", "https://base.drpc.org"]),
    "arbitrum": (42161, "arb-mainnet",     ["https://arbitrum.drpc.org"]),
    "optimism": (10,    "opt-mainnet",     ["https://mainnet.optimism.io", "https://optimism.drpc.org"]),
    "polygon":  (137,   "polygon-mainnet", ["https://polygon.drpc.org"]),
    "bsc":      (56,    "bnb-mainnet",     []),
}


def endpoints(chain: str) -> list:
    """URL archive ordonnees pour `chain` : Alchemy d'abord (si cle), puis fallbacks gratuits."""
    _, sub, fb = CHAINS[chain]
    urls = []
    if ALCHEMY_KEY:
        urls.append(f"https://{sub}.g.alchemy.com/v2/{ALCHEMY_KEY}")
    urls.extend(fb)
    return urls


def redact(url: str) -> str:
    return url.replace(ALCHEMY_KEY, "***") if ALCHEMY_KEY and ALCHEMY_KEY in url else url


def rpc(url: str, method: str, params: list, timeout: int = 20):
    try:
        r = requests.post(url, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
                          timeout=timeout)
        j = r.json()
        return j.get("result"), j.get("error")
    except Exception as e:
        return None, f"{type(e).__name__}: {str(e)[:50]}"


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    print(f"ALCHEMY_KEY presente : {'OUI' if ALCHEMY_KEY else 'NON'}")
    deep = hex(1_000_000)
    for chain, (cid, _, _) in CHAINS.items():
        parts = []
        for url in endpoints(chain):
            src = "alchemy" if "alchemy" in url else redact(url).split("//")[-1].split("/")[0]
            r, e1 = rpc(url, "eth_chainId", [])
            if r is None:
                parts.append(f"{src}:MORT"); continue
            bal, _ = rpc(url, "eth_getBalance", ["0x0000000000000000000000000000000000000000", deep])
            parts.append(f"{src}:{'ARCHIVE' if bal is not None else 'elague'}")
        print(f"  {chain:<9} " + "  ".join(parts))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
