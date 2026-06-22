#!/usr/bin/env python
"""Saisie SECURISEE des cles CEX -> arb/.env, avec VERIFICATION immediate. Valeurs jamais affichees.

A lancer dans TON terminal (PAS via Claude / PAS via '!') :
    cd "C:\\Users\\admin\\Desktop\\PROJECT\\Mercor\\arb"
    .venv\\Scripts\\python.exe set_key.py

Tu choisis un exchange, tu colles API key / secret (/ passphrase) en entree MASQUEE ; il TESTE
l'authentification tout de suite ([OK]/[ECHEC]) puis ecrit dans .env (gitignore). Relance pour
ajouter d'autres exchanges. Les valeurs existantes sont conservees.
"""
import getpass
import sys
from pathlib import Path

import ccxt

ENV = Path(__file__).resolve().parent / ".env"
NEED_PW = {"OKX", "KUCOIN", "BITGET"}
VALID = ["binance", "okx", "bybit", "kucoin", "gateio", "mexc", "bitget", "kraken", "htx", "cryptocom"]

if not sys.stdin.isatty():
    print("STOP : lance-moi dans TON terminal (cmd/PowerShell), pas via Claude :")
    print('   cd "C:\\Users\\admin\\Desktop\\PROJECT\\Mercor\\arb"')
    print("   .venv\\Scripts\\python.exe set_key.py")
    raise SystemExit(1)


ALT_CLASSES = {                                    # entites regionales (Europe) — on essaie chaque variante
    "okx": ["okx", "myokx", "okxus"],              # OKX global / EEA (Europe-MiCA) / US
    "bybit": ["bybit", "bybiteu"],                 # Bybit global / EU
}
AUTH_ERR = ("50119", "doesn't exist", "Invalid API", "Invalid Api", "signature", "Signature", "apikey", "API-key")


def verify(name, key, sec, pw):
    """(status, message, classe_qui_marche). Essaie les entites alternatives (ex. OKX global puis EEA).

    status: True=authentifiee ; False=cle NON reconnue partout ; None=reconnue mais autre souci.
    """
    classes = [c for c in ALT_CLASSES.get(name, [name]) if c in ccxt.exchanges]
    last = "?"
    for cls in classes:
        cfg = {"apiKey": key, "secret": sec, "enableRateLimit": True, "timeout": 20000}
        if pw:
            cfg["password"] = pw
        try:
            getattr(ccxt, cls)(cfg).fetch_balance()        # test d'auth strict
            return True, "authentifiee" + (f" (entite {cls})" if cls != name else ""), cls
        except Exception as e:
            last = f"{type(e).__name__} {str(e)[:80]}"
            if not any(s in str(e) for s in AUTH_ERR):     # erreur non-auth -> cle reconnue sur cette entite
                return None, f"reconnue ({cls}) mais : {last}", cls
    return False, f"cle NON reconnue ({last}) -> recopie ou recree la cle sur l'exchange", None


vals = {}
if ENV.exists():
    for line in ENV.read_text(encoding="utf-8-sig").splitlines():
        s = line.strip()
        if s and not s.startswith("#") and "=" in s:
            k, v = s.split("=", 1)
            vals[k.strip()] = v.strip()


def save():
    out = ["# arb/.env — gitignore. Ne jamais committer ni coller dans le chat."]
    out.append(f"RPC_URL_BASE={vals.get('RPC_URL_BASE', '')}")
    for kk in sorted(k for k in vals if k != "RPC_URL_BASE"):
        out.append(f"{kk}={vals[kk]}")
    ENV.write_text("\n".join(out) + "\n", encoding="utf-8")


print("Saisie des cles CEX. Entree MASQUEE ; verification immediate.\n")
while True:
    name = input(f"Exchange ({'/'.join(VALID)}) — ou Entree pour terminer : ").strip().lower()
    if not name:
        break
    if name not in VALID:
        print("  exchange inconnu, reessaie.\n"); continue
    u = name.upper()
    key = getpass.getpass(f"  colle {u}_API_KEY (masque) : ").strip()
    if not key:
        print("  vide -> ignore.\n"); continue
    sec = getpass.getpass(f"  colle {u}_SECRET (masque) : ").strip()
    pw = getpass.getpass(f"  colle {u}_PASSWORD / passphrase (masque) : ").strip() if u in NEED_PW else None

    status, msg, cls = verify(name, key, sec, pw)
    tag = "OK" if status else ("ECHEC" if status is False else "?")
    print(f"  [{tag}] {u} : {msg}")
    if status is False:
        if input("  -> garder quand meme ? (o/N) : ").strip().lower() != "o":
            print("  ignore. Recree/recopie la cle puis relance.\n"); continue
    vals[f"{u}_API_KEY"] = key
    vals[f"{u}_SECRET"] = sec
    if pw is not None:
        vals[f"{u}_PASSWORD"] = pw
    if cls and cls != name:
        vals[f"{u}_CCXT"] = cls          # entite alternative retenue (ex. OKX_CCXT=myokx)
    elif f"{u}_CCXT" in vals:
        del vals[f"{u}_CCXT"]
    save()
    print(f"  -> {u} enregistre dans .env.\n")

print("Termine. Reviens dire 'c'est fait' a Claude.")
