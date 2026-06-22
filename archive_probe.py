#!/usr/bin/env python
"""Sonde d'ARCHIVE RPC — quels endpoints GRATUITS (sans cle) servent l'etat HISTORIQUE, jusqu'ou ?

Pour chaque (chaine, endpoint) : eth_chainId (vivant + bonne chaine), eth_blockNumber (tete), puis
test ARCHIVE = eth_getBalance(0x0) a un BLOC ANCIEN profond (un full node elague ~128 blocs -> erreur ;
un noeud d'archive repond). + test eth_getLogs sur une plage ancienne (faisabilite du backfill par
events Swap/Sync). But : trouver le MAX d'archive gratuite, de plusieurs sources, pour remonter loin.

Usage : python archive_probe.py
"""
import sys
import time

import requests

DEEP_BLOCK = 1_000_000          # bloc ancien (profond) -> requiert un vrai noeud d'archive
LOGS_RANGE = 200                # petite plage pour tester getLogs historique

# (chaine, chainId attendu, [endpoints publics sans cle])
TARGETS = [
    ("eth", 1, [
        "https://eth.llamarpc.com", "https://rpc.ankr.com/eth", "https://ethereum-rpc.publicnode.com",
        "https://eth.drpc.org", "https://1rpc.io/eth", "https://eth.meowrpc.com"]),
    ("base", 8453, [
        "https://mainnet.base.org", "https://base-rpc.publicnode.com", "https://base.drpc.org",
        "https://rpc.ankr.com/base", "https://base.llamarpc.com", "https://base.meowrpc.com"]),
    ("arbitrum", 42161, [
        "https://arb1.arbitrum.io/rpc", "https://arbitrum-one-rpc.publicnode.com",
        "https://rpc.ankr.com/arbitrum", "https://arbitrum.drpc.org"]),
    ("optimism", 10, [
        "https://mainnet.optimism.io", "https://optimism-rpc.publicnode.com",
        "https://rpc.ankr.com/optimism", "https://optimism.drpc.org"]),
    ("bsc", 56, [
        "https://bsc-dataseed.bnbchain.org", "https://bsc-rpc.publicnode.com",
        "https://rpc.ankr.com/bsc", "https://bsc.drpc.org"]),
    ("polygon", 137, [
        "https://polygon-rpc.com", "https://polygon-bor-rpc.publicnode.com",
        "https://rpc.ankr.com/polygon", "https://polygon.drpc.org"]),
]


def rpc(url, method, params, timeout=12):
    try:
        r = requests.post(url, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
                          headers={"Content-Type": "application/json"}, timeout=timeout)
        j = r.json()
        return j.get("result"), j.get("error")
    except Exception as e:
        return None, {"message": f"{type(e).__name__}: {str(e)[:50]}"}


def hexint(x):
    try:
        return int(x, 16)
    except (TypeError, ValueError):
        return None


def emsg(e):
    """Message d'erreur robuste : l'erreur JSON-RPC peut etre un dict {message} OU une string."""
    if isinstance(e, dict):
        return str(e.get("message", "?"))
    return str(e) if e else "?"


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    archive_found = {}
    for chain, want_cid, endpoints in TARGETS:
        print(f"\n{'=' * 90}\n{chain.upper()}  (chainId {want_cid}, test archive au bloc {DEEP_BLOCK:,})")
        archive_found[chain] = []
        for url in endpoints:
            cid, e1 = rpc(url, "eth_chainId", [])
            if cid is None:
                print(f"  [MORT  ] {url:<44} {emsg(e1)[:55]}"); continue
            if hexint(cid) != want_cid:
                print(f"  [MAUVAIS] {url:<44} chainId={hexint(cid)}"); continue
            tip = hexint(rpc(url, "eth_blockNumber", [])[0] or "")
            bal, e2 = rpc(url, "eth_getBalance",
                          ["0x0000000000000000000000000000000000000000", hex(DEEP_BLOCK)])
            archive = bal is not None
            logs, _ = rpc(url, "eth_getLogs",
                          [{"fromBlock": hex(DEEP_BLOCK), "toBlock": hex(DEEP_BLOCK + LOGS_RANGE - 1)}])
            glog = f"getLogs={'OK(' + str(len(logs)) + ')' if isinstance(logs, list) else 'KO'}"
            if archive:
                archive_found[chain].append(url)
                print(f"  [ARCHIVE] {url:<44} tip~{tip} {glog}")
            else:
                print(f"  [elague ] {url:<44} tip~{tip} {glog}  ({emsg(e2)[:38]})")
        time.sleep(0.3)

    print(f"\n{'=' * 90}\nBILAN — endpoints d'ARCHIVE gratuits trouves par chaine :")
    for chain, urls in archive_found.items():
        print(f"  {chain:<10} {len(urls)} archive : {', '.join(urls) if urls else '(aucun public -> compte gratuit requis)'}")
    print("\nLecture : [ARCHIVE] sert l'etat au bloc 1,000,000 -> backfill precis (reserves/events) possible")
    print("jusqu'a la profondeur du chain. Combiner plusieurs [ARCHIVE]/chaine = rotation (repartir le budget")
    print("gratuit, remonter loin). Si peu/pas d'archive public : compte gratuit Alchemy/dRPC (archive incluse,")
    print("URL avec cle -> .env). 'getLogs OK' = backfill par events Swap/Sync faisable a cette profondeur.")


if __name__ == "__main__":
    main()
