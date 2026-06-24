#!/usr/bin/env python
"""Runner D2A — registre de candidats cross-protocole Base (Uniswap v3 <-> SlipStream), READ-ONLY.

But UNIQUE : construire un REGISTRE de candidats, SANS mesurer ni classer aucun edge. Repond a la question
« quels marches comparables existent reellement ? » (D2B repondra ensuite « lesquels ont une borne atomique
positive ? »).

Sources CANONIQUES uniquement : evenements PoolCreated des deux factories, jusqu'a un bloc snapshot B fige
au demarrage.
  - Uniswap v3 Factory (Base)  : 0x33128a8fC17869897dcE68Ed026d694621f6FDfD
    PoolCreated(address indexed token0, address indexed token1, uint24 indexed fee, int24 tickSpacing, address pool)
  - SlipStream CLFactory (Base): 0x5e7BB104d84c7CB9B682AaC2F3d509f5F406809A
    PoolCreated(address indexed token0, address indexed token1, int24 indexed tickSpacing, address pool)

Candidat = MEME paire ORDONNEE de contrats ERC-20 (token0, token1) presente sur LES DEUX factories — jamais
ticker. On conserve TOUS les pools correspondants, leurs parametres (fee/tickSpacing) et leur bloc de
creation. AUCUNE selection/exclusion selon prix, spread, volume, TVL ou liquidite. On verifie decimals +
identite de contrat ; on documente les exclusions token special / comportement incompatible QUAND elles sont
demontrables read-only (pas de code, decimals illisible).

Gouvernance : lecture seule ; aucun contrat/cle/wallet/approbation/tx/capital. getLogs via RPC publics
(cap 10k blocs, archive) ; eth_call/getCode via Alchemy. Si l'enumeration canonique est techniquement
INCOMPLETE (un chunk echoue apres retries), verdict NON_CONCLUANT avec la LIMITE EXACTE (plages manquantes).

Sortie : manifeste, raw hashe (tous les logs), registre des paires candidates + pools + exclusions+motifs.
AUCUN quote de rendement, AUCUN verdict economique.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from datetime import datetime, timezone

import requests
from web3 import Web3

import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from archive_rpc import endpoints  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
CHAIN_ID = 8453
UNI_FACT = Web3.to_checksum_address("0x33128a8fC17869897dcE68Ed026d694621f6FDfD")
SLIP_FACT = Web3.to_checksum_address("0x5e7BB104d84c7CB9B682AaC2F3d509f5F406809A")
TOPIC_UNI = "0x" + Web3.keccak(text="PoolCreated(address,address,uint24,int24,address)").hex()
TOPIC_SLIP = "0x" + Web3.keccak(text="PoolCreated(address,address,int24,address)").hex()
LOG_RPCS = ["https://mainnet.base.org", "https://base.drpc.org"]  # getLogs 10k + archive (sonde D2A)
CHUNK = 10_000
SEL_DECIMALS = Web3.keccak(text="decimals()")[:4]


def _ca(hex40: str) -> str:
    return Web3.to_checksum_address("0x" + hex40[-40:])


def decode_uni_log(log: dict) -> dict:
    """PoolCreated Uniswap v3 : token0,token1,fee (indexes) ; data = tickSpacing(32)+pool(32)."""
    t = log["topics"]
    data = bytes.fromhex(log["data"][2:])
    return {"token0": _ca(t[1]), "token1": _ca(t[2]), "fee": int(t[3], 16),
            "tickSpacing": int.from_bytes(data[0:32], "big"), "pool": _ca("0x" + data[32:64].hex()),
            "block": int(log["blockNumber"], 16)}


def decode_slip_log(log: dict) -> dict:
    """PoolCreated SlipStream : token0,token1,tickSpacing (indexes) ; data = pool(32)."""
    t = log["topics"]
    data = bytes.fromhex(log["data"][2:])
    return {"token0": _ca(t[1]), "token1": _ca(t[2]), "tickSpacing": int(t[3], 16),
            "pool": _ca("0x" + data[-32:].hex()), "block": int(log["blockNumber"], 16)}


def candidates_from_maps(uni_map: dict, slip_map: dict) -> list:
    """Candidats = paires ordonnees (token0,token1) presentes sur LES DEUX factories."""
    return sorted(set(uni_map) & set(slip_map))


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _git(*a: str) -> str:
    try:
        return subprocess.run(["git", "-C", HERE, *a], capture_output=True, text=True).stdout.strip()
    except Exception:
        return ""


def provenance() -> dict:
    rel = os.path.relpath(os.path.abspath(__file__), HERE).replace("\\", "/")
    with open(os.path.abspath(__file__), "rb") as f:
        runner_sha = hashlib.sha256(f.read()).hexdigest()
    tracked = bool(_git("ls-files", "--", rel))
    file_status = _git("status", "--porcelain", "--", rel)
    code_versioned = tracked and not file_status
    tracked_dirty = bool(_git("status", "--porcelain", "--untracked-files=no"))
    return {"git_hash": _git("rev-parse", "HEAD") or "UNVERSIONED", "runner_path": rel,
            "runner_sha256": runner_sha, "runner_tracked": tracked, "runner_status": file_status or "clean",
            "code_versioned": bool(code_versioned), "git_dirty": bool(tracked_dirty or not code_versioned)}


def rpc(url: str, method: str, params: list, timeout: int = 30):
    try:
        j = requests.post(url, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
                          timeout=timeout).json()
        return j.get("result"), j.get("error")
    except Exception as e:
        return None, {"message": f"{type(e).__name__}: {str(e)[:60]}"}


def get_logs_chunk(frm: int, to: int, factory: str, topic: str):
    """getLogs sur [frm,to] (<=10k) avec rotation LOG_RPCS + retries. -> (logs|None)."""
    for attempt in range(4):
        url = LOG_RPCS[attempt % len(LOG_RPCS)]
        res, err = rpc(url, "eth_getLogs",
                       [{"address": factory, "topics": [topic], "fromBlock": hex(frm), "toBlock": hex(to)}])
        if err is None and res is not None:
            return res
        time.sleep(0.4 * (attempt + 1))
    return None


def enumerate_factory(factory: str, topic: str, deploy: int, snapshot: int, decode) -> tuple:
    """Enumere PoolCreated [deploy,snapshot] en chunks 10k. -> (pairs_map, n_logs, missing_ranges)."""
    pairs_map, n_logs, missing = {}, 0, []
    frm = deploy
    while frm <= snapshot:
        to = min(frm + CHUNK - 1, snapshot)
        logs = get_logs_chunk(frm, to, factory, topic)
        if logs is None:
            missing.append([frm, to])
        else:
            for lg in logs:
                d = decode(lg)
                pairs_map.setdefault((d["token0"], d["token1"]), []).append(d)
                n_logs += 1
        frm = to + 1
    return pairs_map, n_logs, missing


def find_deploy_block(alchemy: str, factory: str, snapshot: int) -> int:
    """Plus petit bloc ou le factory a du code (binary search getCode)."""
    lo, hi = 0, snapshot
    while lo < hi:
        mid = (lo + hi) // 2
        code, _ = rpc(alchemy, "eth_getCode", [factory, hex(mid)])
        if code and code != "0x":
            hi = mid
        else:
            lo = mid + 1
    return lo


def main() -> int:
    prov = provenance()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    raw_dir = os.path.join(HERE, "data", "raw", "defi", "d2a")
    run_dir = os.path.join(HERE, "runs", f"{stamp}_d2a-crossprotocol-registry-base")
    os.makedirs(raw_dir, exist_ok=True)
    os.makedirs(run_dir, exist_ok=True)
    manifest = {
        "phase": "D2A", "track": "defi-samechain-mev-boundary", "chain": "base",
        "objective": "registre de candidats cross-protocole Uni v3 <-> SlipStream (SANS mesurer aucun edge)",
        "read_only": True, "no_contract_key_wallet_tx_capital": True,
        "sources": {"uni_factory": UNI_FACT, "uni_topic": TOPIC_UNI,
                    "slip_factory": SLIP_FACT, "slip_topic": TOPIC_SLIP,
                    "log_rpcs": LOG_RPCS, "getlogs_chunk_blocks": CHUNK},
        "candidate_rule": "meme paire ordonnee (token0,token1) sur LES DEUX factories ; jamais ticker ; "
                          "aucune selection par prix/spread/volume/TVL/liquidite",
        "created_utc": now_utc(), **prov,
    }

    alchemy = endpoints("base")[0]
    res, err = rpc(alchemy, "eth_blockNumber", [])
    if err or not res:
        return _abort(run_dir, manifest, "RPC Alchemy (eth_call) indisponible")
    B = int(res, 16)
    manifest["snapshot_block_B"] = B
    # vérifier que les RPC getLogs répondent (sinon limite exacte)
    for u in LOG_RPCS:
        _, e = rpc(u, "eth_chainId", [])
        if e:
            return _abort(run_dir, manifest, f"RPC getLogs {u} indisponible -> enumeration impossible")

    uni_deploy = find_deploy_block(alchemy, UNI_FACT, B)
    slip_deploy = find_deploy_block(alchemy, SLIP_FACT, B)
    manifest["deploy_blocks"] = {"uni": uni_deploy, "slip": slip_deploy}
    print(f"snapshot B={B} ; deploy uni={uni_deploy} slip={slip_deploy}")
    print(f"chunks ~ uni={(B-uni_deploy)//CHUNK+1} slip={(B-slip_deploy)//CHUNK+1}")

    uni_map, uni_n, uni_missing = enumerate_factory(UNI_FACT, TOPIC_UNI, uni_deploy, B, decode_uni_log)
    print(f"uni: {uni_n} logs, {len(uni_map)} paires, {len(uni_missing)} chunks manquants")
    slip_map, slip_n, slip_missing = enumerate_factory(SLIP_FACT, TOPIC_SLIP, slip_deploy, B, decode_slip_log)
    print(f"slip: {slip_n} logs, {len(slip_map)} paires, {len(slip_missing)} chunks manquants")

    cands = candidates_from_maps(uni_map, slip_map)

    # decimals + code (Alchemy) + exclusions demontrables
    def tok_meta(addr):
        code, _ = rpc(alchemy, "eth_getCode", [addr, hex(B)])
        has_code = bool(code and code != "0x")
        dec = None
        if has_code:
            d, e = rpc(alchemy, "eth_call", [{"to": addr, "data": "0x" + SEL_DECIMALS.hex()}, hex(B)])
            if not e and d and len(d) >= 66:
                try:
                    dec = int(d, 16)
                except Exception:
                    dec = None
        return has_code, dec

    registry, exclusions, seen_tok = [], [], {}
    for (t0, t1) in cands:
        for tk in (t0, t1):
            if tk not in seen_tok:
                seen_tok[tk] = tok_meta(tk)
        c0, d0 = seen_tok[t0]
        c1, d1 = seen_tok[t1]
        reason = None
        if not c0 or not c1:
            reason = "token sans code (non-contrat)"
        elif d0 is None or d1 is None:
            reason = "decimals illisible (ERC-20 non standard)"
        entry = {"token0": t0, "token1": t1, "decimals0": d0, "decimals1": d1,
                 "uni_pools": [{"pool": p["pool"], "fee": p["fee"], "tickSpacing": p["tickSpacing"],
                                "block": p["block"]} for p in uni_map[(t0, t1)]],
                 "slip_pools": [{"pool": p["pool"], "tickSpacing": p["tickSpacing"], "block": p["block"]}
                                for p in slip_map[(t0, t1)]]}
        if reason:
            exclusions.append({"token0": t0, "token1": t1, "reason": reason})
        else:
            registry.append(entry)

    incomplete = bool(uni_missing or slip_missing)
    verdict = "NON_CONCLUANT" if incomplete else "REGISTRE_COMPLET"

    # raw hashé hors Git (tous les logs décodés)
    raw = json.dumps({"uni": {f"{k[0]}|{k[1]}": v for k, v in uni_map.items()},
                      "slip": {f"{k[0]}|{k[1]}": v for k, v in slip_map.items()}}, ensure_ascii=False).encode()
    raw_path = os.path.join(raw_dir, f"pools_{stamp}.json")
    with open(raw_path, "wb") as f:
        f.write(raw)

    manifest.update({
        "enumeration": {"uni_logs": uni_n, "uni_pairs": len(uni_map), "uni_missing_ranges": uni_missing,
                        "slip_logs": slip_n, "slip_pairs": len(slip_map), "slip_missing_ranges": slip_missing,
                        "complete": not incomplete},
        "candidates_count": len(cands), "registry_count": len(registry), "exclusions_count": len(exclusions),
        "candidate_registry": registry, "exclusions": exclusions,
        "receipts": [{"name": "pools", "sha256": hashlib.sha256(raw).hexdigest(),
                      "raw_path": os.path.relpath(raw_path, HERE).replace("\\", "/")}],
        "verdict": verdict,
        "verdict_detail": ("Enumeration canonique INCOMPLETE -> NON_CONCLUANT (plages manquantes ci-dessus : "
                           "uni_missing_ranges / slip_missing_ranges)." if incomplete else
                           "Registre complet. AUCUN edge mesure ni classe. D2B (regle de test prereistree) "
                           "suivra, sans choix opportuniste de token apres avoir vu les ecarts."),
        "note": "AUCUN quote de rendement, AUCUN verdict economique. Pas de selection par prix/volume/TVL/liquidite.",
    })
    with open(os.path.join(run_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    print(json.dumps({"verdict": verdict, "snapshot_block_B": B,
                      "uni_pairs": len(uni_map), "slip_pairs": len(slip_map),
                      "candidates": len(cands), "registry": len(registry), "exclusions": len(exclusions),
                      "complete": not incomplete, "uni_missing": uni_missing[:3], "slip_missing": slip_missing[:3],
                      "run_dir": os.path.relpath(run_dir, HERE).replace("\\", "/")}, ensure_ascii=False, indent=2))
    return 0


def _abort(run_dir, manifest, reason):
    manifest["verdict"] = "NON_CONCLUANT"
    manifest["abstention_reason"] = reason
    manifest["created_utc"] = now_utc()
    with open(os.path.join(run_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(json.dumps({"verdict": "NON_CONCLUANT", "reason": reason}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
