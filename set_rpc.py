#!/usr/bin/env python
"""Saisie SECURISEE de la cle ALCHEMY -> arb/.env, avec VERIFICATION. Valeur jamais affichee/loggee.

A lancer dans TON terminal (PAS via Claude / PAS via '!') :
    cd "C:\\Users\\admin\\Desktop\\PROJECT\\Mercor\\arb"
    .venv\\Scripts\\python.exe set_rpc.py

Colle ta cle Alchemy en entree MASQUEE ; il TESTE l'archive (etat au bloc 1,000,000) sur chaque
chaine, puis ecrit ALCHEMY_KEY dans .env (gitignore). Une seule cle -> toutes les chaines (le code
construit les URL par sous-domaine). La cle ne transite JAMAIS par le chat.
"""
import getpass
import sys
from pathlib import Path

import requests

ENV = Path(__file__).resolve().parent / ".env"
# chaine -> sous-domaine Alchemy
NETS = {"eth": "eth-mainnet", "base": "base-mainnet", "arbitrum": "arb-mainnet",
        "optimism": "opt-mainnet", "polygon": "polygon-mainnet", "bsc": "bnb-mainnet"}
DEEP = hex(1_000_000)

if not sys.stdin.isatty():
    print("STOP : lance-moi dans TON terminal (cmd/PowerShell), pas via Claude :")
    print('   cd "C:\\Users\\admin\\Desktop\\PROJECT\\Mercor\\arb"')
    print("   .venv\\Scripts\\python.exe set_rpc.py")
    raise SystemExit(1)


def rpc(url, method, params):
    try:
        r = requests.post(url, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
                          timeout=15)
        j = r.json()
        return j.get("result"), j.get("error")
    except Exception as e:
        return None, f"{type(e).__name__}: {str(e)[:50]}"


key = getpass.getpass("Colle ta cle Alchemy (masque) : ").strip()
if not key:
    print("vide -> abandon (rien ecrit)."); raise SystemExit(1)

print("Verification (archive a l'etat du bloc 1,000,000)...")
ok = []
for name, sub in NETS.items():
    url = f"https://{sub}.g.alchemy.com/v2/{key}"
    cid, e1 = rpc(url, "eth_chainId", [])
    if cid is None:
        print(f"  {name:<9} [KO]      {e1}"); continue
    bal, e2 = rpc(url, "eth_getBalance", ["0x0000000000000000000000000000000000000000", DEEP])
    if bal is not None:
        print(f"  {name:<9} [ARCHIVE OK]"); ok.append(name)
    else:
        print(f"  {name:<9} [vivant mais archive KO] {(e2 or {}).get('message', e2) if isinstance(e2, dict) else e2}")

if not ok:
    print("\nAucune chaine ne repond -> cle invalide/mal copiee ? (RIEN ecrit). Recopie-la et relance.")
    raise SystemExit(1)

# preserver le reste de .env, ne (re)mettre que ALCHEMY_KEY
vals = {}
if ENV.exists():
    for line in ENV.read_text(encoding="utf-8-sig").splitlines():
        s = line.strip()
        if s and not s.startswith("#") and "=" in s:
            k, v = s.split("=", 1)
            vals[k.strip()] = v.strip()
vals["ALCHEMY_KEY"] = key
out = ["# arb/.env — gitignore. Ne jamais committer ni coller dans le chat."]
out.append(f"RPC_URL_BASE={vals.get('RPC_URL_BASE', '')}")
for k in sorted(x for x in vals if x != "RPC_URL_BASE"):
    out.append(f"{k}={vals[k]}")
ENV.write_text("\n".join(out) + "\n", encoding="utf-8")

print(f"\nOK -> ALCHEMY_KEY ecrite dans .env. Archive confirmee sur : {', '.join(ok)}")
print("Reviens dire 'c'est fait' a Claude.")
