#!/usr/bin/env python
"""Runner D2B-1 — liveness $250 des 540 routes gelees (cohorte USDC), READ-ONLY.

Pour chaque route, dans l'ordre route_hash PRE-ENREGISTRE (D2B-0) : simulation de l'executeur atomique D1.6
dans LES DEUX orientations, entree = $250 en USDC. ADMISSION (vivante) = UNIQUEMENT si les deux appels ne
revert PAS. JAMAIS de filtre/tri/arret selon le signe de la sortie / upper bound (aucun upper bound calcule
ici). Toutes les sorties brutes (requete, reponse, reason de revert) archivees + hashees.

Override : code executeur + ETH sur FAKE ; balance USDC sur FAKE (= L'EXECUTEUR, slot auto-verifie). Le
`from` est une adresse DISTINCTE de l'executeur -> prouve que la balance est lue sur l'executeur (to), pas
sur from. Code-override verifie honore pour eth_call (INVALID -> revert), slot USDC auto-verifie
(balanceOf(FAKE)=HUGE) : tout probleme slot/RPC/code-override/cout -> NON_CONCLUANT (jamais silencieusement
"non vivante").

INTERDITS D2B-1 : aucun test 300 blocs, aucune grille $1k-$10k, aucun verdict economique. Liveness seule.
Sortie : routes passantes, reverts ventiles par motif, non-concluantes, couverture, integrite des recus.
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import subprocess
import time
from datetime import datetime, timezone

from eth_abi import encode as abi_encode
from web3 import Web3

import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from archive_rpc import endpoints  # noqa: E402
from d1_mev_boundary_control import raw_rpc, mapping_slot, CHAIN_ID  # noqa: E402
from d1_6_simulated_executor_envelope import (  # noqa: E402
    SEL_UNI_THEN_SLIP, SEL_SLIP_THEN_UNI, UNI_ROUTER, SLIP_ROUTER)

HERE = os.path.dirname(os.path.abspath(__file__))
USDC = Web3.to_checksum_address("0x833589fcd6edb6e08f4c7c32d4f71b54bda02913")
FAKE = Web3.to_checksum_address("0x00000000000000000000000000000000DeaDBeef")     # executeur simule
FROM = Web3.to_checksum_address("0x0000000000000000000000000000000000000001")     # DISTINCT de l'executeur
USDC_AMOUNT = 250 * 10 ** 6        # $250 en USDC (6 decimales)
HUGE = 10 ** 15                    # 1e9 USDC ; top-bit 0 (non blackliste)
USDC_SLOT_CANDIDATES = [9, 0, 1, 2, 3, 8, 10, 11]
SEL_BALANCEOF = Web3.keccak(text="balanceOf(address)")[:4]
ORIENTATIONS = ["uni_then_slip", "slip_then_uni"]


def exec_calldata(orient: str, token_in: str, token_other: str, uni_fee: int, slip_ts: int,
                  amount_in: int) -> bytes:
    if orient == "uni_then_slip":
        return SEL_UNI_THEN_SLIP + abi_encode(
            ["address", "address", "address", "address", "uint24", "int24", "uint256", "uint256"],
            [UNI_ROUTER, SLIP_ROUTER, token_in, token_other, int(uni_fee), int(slip_ts), int(amount_in), 0])
    return SEL_SLIP_THEN_UNI + abi_encode(
        ["address", "address", "address", "address", "int24", "uint24", "uint256", "uint256"],
        [SLIP_ROUTER, UNI_ROUTER, token_in, token_other, int(slip_ts), int(uni_fee), int(amount_in), 0])


def classify(err: dict | None) -> str:
    """ok / revert (ECHEC d'EXECUTION deterministe = mort) / rpcerror (INFRA -> NON_CONCLUANT).

    Echec d'execution = revert, invalid opcode, EVM error, out of gas... -> route 'morte'.
    Infra = timeout, rate limit, missing trie node, connexion... -> NON_CONCLUANT. Inconnu -> rpcerror
    (conservateur : jamais silencieusement traite comme 'non vivante').
    """
    if err is None:
        return "ok"
    msg = (err.get("message", "") if isinstance(err, dict) else str(err)).lower()
    infra = ["missing trie node", "header not found", "timeout", "timed out", "rate limit", "429",
             "too many requests", "connection", "could not resolve", "temporarily", "service unavailable",
             "503", "502", "bad gateway", "try again", "capacity"]
    if any(k in msg for k in infra):
        return "rpcerror"
    execf = ["revert", "invalid opcode", "invalidfeopcode", "evm error", "out of gas", "gas required",
             "stack underflow", "stack overflow", "invalid jump"]
    if any(k in msg for k in execf):
        return "revert"
    return "rpcerror"   # inconnu -> NON_CONCLUANT


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


def abstain(run_dir, manifest, reason):
    manifest["verdict"] = "NON_CONCLUANT"
    manifest["abstention_reason"] = reason
    manifest["created_utc"] = now_utc()
    os.makedirs(run_dir, exist_ok=True)
    with open(os.path.join(run_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(json.dumps({"verdict": "NON_CONCLUANT", "reason": reason}, ensure_ascii=False))
    return 0


def eth_call_route(url, cd, block_hex, override):
    """eth_call avec retries sur erreur RPC (infra). -> (status, payload). revert != rpcerror."""
    last = None
    for attempt in range(3):
        res, err = raw_rpc(url, "eth_call", [{"from": FROM, "to": FAKE, "data": "0x" + cd.hex()}, block_hex, override])
        st = classify(err)
        if st == "ok":
            return "ok", res
        if st == "revert":
            return "revert", (err.get("message", "") if isinstance(err, dict) else str(err))
        last = err
        time.sleep(0.4 * (attempt + 1))
    return "rpcerror", (last.get("message", "") if isinstance(last, dict) else str(last))


def main() -> int:
    prov = provenance()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    raw_dir = os.path.join(HERE, "data", "raw", "defi", "d2b1")
    run_dir = os.path.join(HERE, "runs", f"{stamp}_d2b1-liveness-usdc-cohort")
    os.makedirs(raw_dir, exist_ok=True)
    os.makedirs(run_dir, exist_ok=True)

    d2b0_cands = sorted(glob.glob(os.path.join(HERE, "runs", "*_d2b0-cohort-routes-usdc", "manifest.json")))
    if not d2b0_cands:
        return abstain(run_dir, {"phase": "D2B-1", **prov}, "manifeste D2B-0 (ordre gele) introuvable")
    d2b0 = json.load(open(d2b0_cands[-1], encoding="utf-8"))
    routes = d2b0["frozen_routes"]
    bytecode = json.load(open(os.path.join(HERE, "contracts", "CrossProtocolExecutor.json"),
                              encoding="utf-8"))["deployed_bytecode"]
    manifest = {
        "phase": "D2B-1", "track": "defi-samechain-mev-boundary", "chain": "base",
        "objective": "liveness $250 des routes gelees (cohorte USDC), 2 sens, admission = non-revert seulement",
        "read_only": True, "no_contract_key_wallet_tx_capital": True,
        "d2b0_source": {"manifest": os.path.relpath(d2b0_cands[-1], HERE).replace("\\", "/"),
                        "frozen_order_digest": d2b0.get("frozen_order_digest_sha256"),
                        "routes_count": d2b0.get("routes_count")},
        "params": {"usdc": USDC, "usdc_amount_6dec": USDC_AMOUNT, "from_distinct_de_executeur": FROM,
                   "executeur": FAKE, "orientations": ORIENTATIONS},
        "created_utc": now_utc(), **prov,
        "note": "Liveness seule. Aucun upper bound, aucune grille $1k-$10k, aucun 300 blocs, aucun verdict economique.",
    }

    url = endpoints("base")[0]
    res, err = raw_rpc(url, "eth_blockNumber", [])
    if err or not res:
        return abstain(run_dir, manifest, "RPC indisponible")
    head = int(res, 16)
    head_hex = hex(head)
    manifest["block"] = head

    # --- Slot balance USDC auto-verifie SUR L'EXECUTEUR (FAKE) ---
    slot = None
    for s in USDC_SLOT_CANDIDATES:
        ov = {USDC: {"stateDiff": {mapping_slot(FAKE, s): "0x" + HUGE.to_bytes(32, "big").hex()}}}
        r, e = raw_rpc(url, "eth_call",
                       [{"to": USDC, "data": "0x" + (SEL_BALANCEOF + abi_encode(["address"], [FAKE])).hex()},
                        head_hex, ov])
        if not e and r and int(r, 16) == HUGE:
            slot = s
            break
    if slot is None:
        return abstain(run_dir, manifest, "slot balance USDC introuvable (override non reflete sur l'executeur)")
    manifest["usdc_balance_slot_on_executor"] = slot

    OVERRIDE = {FAKE: {"code": bytecode, "balance": hex(10 ** 24)},
                USDC: {"stateDiff": {mapping_slot(FAKE, slot): "0x" + HUGE.to_bytes(32, "big").hex()}}}
    # --- Code-override honore pour eth_call : bytecode-temoin qui RETOURNE 42 (sans ambiguite) ---
    RET42 = "0x602a60005260206000f3"   # PUSH1 0x2a; MSTORE; RETURN 32 -> 42
    r42, e42 = raw_rpc(url, "eth_call", [{"from": FROM, "to": FAKE, "data": "0x"},
                                         head_hex, {FAKE: {"code": RET42, "balance": hex(10 ** 24)}}])
    if e42 or not r42 or int(r42, 16) != 42:
        return abstain(run_dir, manifest, "code-override non honore par eth_call (temoin ne retourne pas 42)")

    # --- Liveness des 540 routes, ordre gele ---
    results, order_used = [], []
    live = 0
    revert_reasons, n_nonconcl = {}, 0
    for r in routes:
        other = r["token1"] if Web3.to_checksum_address(r["token0"]) == USDC else r["token0"]
        order_used.append(r["route_hash"])
        per = {"route_hash": r["route_hash"], "token0": r["token0"], "token1": r["token1"], "other": other,
               "uni_pool": r["uni_pool"], "uni_fee": r["uni_fee"], "slip_pool": r["slip_pool"],
               "slip_tickSpacing": r["slip_tickSpacing"], "orientations": {}}
        statuses = []
        for orient in ORIENTATIONS:
            cd = exec_calldata(orient, USDC, other, r["uni_fee"], r["slip_tickSpacing"], USDC_AMOUNT)
            st, payload = eth_call_route(url, cd, head_hex, OVERRIDE)
            if st == "ok":
                per["orientations"][orient] = {"status": "ok", "out_usdc_6dec": int(payload, 16)}
            elif st == "revert":
                per["orientations"][orient] = {"status": "revert", "reason": payload[:160]}
            else:
                per["orientations"][orient] = {"status": "rpcerror", "reason": payload[:160]}
            statuses.append(st)
        if "rpcerror" in statuses:
            per["classification"] = "non_concluante"
            n_nonconcl += 1
        elif all(s == "ok" for s in statuses):
            per["classification"] = "vivante"
            live += 1
        else:
            per["classification"] = "morte"
            for orient in ORIENTATIONS:
                o = per["orientations"][orient]
                if o["status"] == "revert":
                    key = o["reason"] or "execution reverted (no data)"
                    revert_reasons[key] = revert_reasons.get(key, 0) + 1
        results.append(per)

    # Couverture + integrite : ordre utilise == ordre gele D2B-0
    order_digest_used = hashlib.sha256("".join(order_used).encode()).hexdigest()
    coverage_ok = (len(results) == d2b0.get("routes_count")) and \
                  (order_digest_used == d2b0.get("frozen_order_digest_sha256"))

    raw = json.dumps({"block": head, "results": results}, ensure_ascii=False).encode()
    raw_path = os.path.join(raw_dir, f"liveness_{stamp}.json")
    with open(raw_path, "wb") as f:
        f.write(raw)
    raw_sha = hashlib.sha256(raw).hexdigest()

    manifest.update({
        "routes_total": len(results), "routes_vivantes": live,
        "routes_mortes": sum(1 for x in results if x["classification"] == "morte"),
        "routes_non_concluantes": n_nonconcl,
        "reverts_par_motif": dict(sorted(revert_reasons.items(), key=lambda kv: -kv[1])),
        "couverture": {"routes_attendues": d2b0.get("routes_count"), "routes_traitees": len(results),
                       "ordre_gele_respecte": order_digest_used == d2b0.get("frozen_order_digest_sha256"),
                       "ordre_digest_utilise": order_digest_used, "complete": coverage_ok},
        "receipts": [{"name": "liveness", "sha256": raw_sha,
                      "raw_path": os.path.relpath(raw_path, HERE).replace("\\", "/"),
                      "n_routes": len(results)}],
        "verdict": "LIVENESS_OK" if coverage_ok else "NON_CONCLUANT",
        "verdict_detail": ("Liveness complete sur l'ordre gele. Admission = non-revert des 2 sens uniquement ; "
                           "aucun filtre/tri/arret par signe de sortie. D2B-2 = decision separee." if coverage_ok
                           else "Couverture/ordre incomplet -> NON_CONCLUANT."),
    })
    with open(os.path.join(run_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    print(json.dumps({"verdict": manifest["verdict"], "routes_total": len(results),
                      "vivantes": live, "mortes": manifest["routes_mortes"], "non_concluantes": n_nonconcl,
                      "reverts_par_motif": manifest["reverts_par_motif"],
                      "couverture_complete": coverage_ok, "ordre_gele_respecte": coverage_ok,
                      "receipt_sha256": raw_sha[:16] + "...", "usdc_slot": slot,
                      "run_dir": os.path.relpath(run_dir, HERE).replace("\\", "/")}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
