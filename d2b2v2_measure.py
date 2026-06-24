#!/usr/bin/env python
"""Runner D2B-2-v2 (MESURE par lot) — SEMANTIQUE IDENTIQUE a v1 (938b6a5), seul le TRANSPORT RPC change.

Memes routes, ordre, blocs, tailles, executeur, state-overrides, oracle Chainlink, categories et schema raw
que d2b2_measure (v1). Reutilise les MEMES fonctions PURES (fenetre, ancre, formule, categories). Le SEUL
changement : transport JSON-RPC BATCH (un POST = N requetes), IDs stables, reponses reordonnees de maniere
DETERMINISTE par id. Aucune baisse de fidelite : eth_call, estimateGas, getL1Fee et oracle restent tous au
MEME blockTag=b. Retries et erreurs de transport TOUJOURS archives.

Namespace DISTINCT de v1 (runs/*_d2b2v2-measure-lotNN, data/raw/defi/d2b2v2/) -> jamais melange avec
D2B2_ABORTED_PERFORMANCE. Equivalence byte/resultat-a-resultat v1<->v2 prouvee par d2b2_bench.py avant tout
run complet. Lecture seule ; aucun contrat/cle/wallet/tx/capital. Gate --lot requise.
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import subprocess
import time
from datetime import datetime, timezone

import requests
from eth_abi import encode as abi_encode
from web3 import Web3

import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from archive_rpc import endpoints  # noqa: E402
from d1_mev_boundary_control import (  # noqa: E402
    serialize_dummy_1559, gas_normal_wei, mapping_slot, SEL_GETL1FEE, GASORACLE, CHAIN_ID)
from d2b1_liveness import exec_calldata, classify, USDC, FAKE, FROM, HUGE, ORIENTATIONS  # noqa: E402
from d2b2_measure import (  # noqa: E402  (fonctions PURES + constantes IDENTIQUES a v1)
    B1, N_BLOCKS, SIZES_USD, USDC_SLOT, CHAINLINK_ETH_USD, CHAINLINK_DECIMALS, STALENESS_MAX_S,
    SEL_LATESTROUNDDATA, window_blocks, anchor_eth_usd, gas_normal_usdc, upper_bound_usdc, classify_cycle)

HERE = os.path.dirname(os.path.abspath(__file__))
BATCH_CHUNK = 60                 # requetes/POST (override-heavy -> conservateur)
SEL_GETCODE = None               # eth_getCode est une methode, pas un selecteur


# ----------------------------------------------------------------------------- transport BATCH (testable en partie)
def build_request(rid: int, method: str, params: list) -> dict:
    return {"jsonrpc": "2.0", "id": rid, "method": method, "params": params}


def reorder_by_id(responses: list) -> dict:
    """Reordonne DETERMINISTE par id -> {id: (result, error)}."""
    return {x["id"]: (x.get("result"), x.get("error")) for x in responses if isinstance(x, dict) and "id" in x}


def batch_post(url: str, reqs: list, archive: list, max_retry: int = 4) -> dict | None:
    """Envoie un batch (chunk <= BATCH_CHUNK gere par l'appelant). Retries transport archives. -> {id:(res,err)}."""
    for attempt in range(max_retry):
        try:
            resp = requests.post(url, json=reqs, timeout=90).json()
            if isinstance(resp, list) and len(resp) == len(reqs):
                return reorder_by_id(resp)
            archive.append({"attempt": attempt, "n_req": len(reqs),
                            "error": f"reponse non-liste/incomplete ({type(resp).__name__})"})
        except Exception as e:
            archive.append({"attempt": attempt, "n_req": len(reqs), "error": f"{type(e).__name__}: {str(e)[:80]}"})
        time.sleep(0.5 * (attempt + 1))
    return None


def batched(url: str, reqs: list, archive: list) -> dict:
    """Decoupe en chunks <= BATCH_CHUNK, fusionne les {id:(res,err)}. Chunk en echec total -> ids absents."""
    out = {}
    for i in range(0, len(reqs), BATCH_CHUNK):
        chunk = reqs[i:i + BATCH_CHUNK]
        res = batch_post(url, chunk, archive)
        if res is None:
            archive.append({"chunk_offset": i, "error": "chunk en echec apres retries (ids absents -> NON_CONCLUANT)"})
            continue
        out.update(res)
    return out


# ----------------------------------------------------------------------------- override + calldatas (identiques v1)
def overrides(bytecode: str) -> dict:
    return {FAKE: {"code": bytecode, "balance": hex(10 ** 24)},
            USDC: {"stateDiff": {mapping_slot(FAKE, USDC_SLOT): "0x" + HUGE.to_bytes(32, "big").hex()}}}


def _decode_anchor(res):
    if not res or len(res) < 2 + 64 * 5:
        return None, None
    b = bytes.fromhex(res[2:])
    return int.from_bytes(b[32:64], "big", signed=True), int.from_bytes(b[96:128], "big")


def measure_batched(url: str, OV: dict, routes: list, blocks: list, sizes: list, dirs: list, archive: list) -> list:
    """Mesure batchee (transport seul). Schema de record IDENTIQUE a v1. 2 rounds/bloc (R-A ; R-B getL1Fee)."""
    records = []
    for b in blocks:
        bhex = hex(b)
        rid = 0
        idmap = {}
        reqs = []

        def add(method, params, tag):
            nonlocal rid
            reqs.append(build_request(rid, method, params))
            idmap[rid] = tag
            rid += 1

        pools = {}
        for r in routes:
            for pool in (r["uni_pool"], r["slip_pool"]):
                if pool not in pools:
                    pools[pool] = ("code", pool)
                    add("eth_getCode", [pool, bhex], ("code", pool))
        add("eth_getBlockByNumber", [bhex, False], ("block",))
        add("eth_call", [{"to": CHAINLINK_ETH_USD, "data": "0x" + SEL_LATESTROUNDDATA.hex()}, bhex], ("oracle",))
        cyc = []
        for r in routes:
            other = r["token1"] if Web3.to_checksum_address(r["token0"]) == USDC else r["token0"]
            for s in sizes:
                for d in dirs:
                    cd = exec_calldata(d, USDC, other, r["uni_fee"], r["slip_tickSpacing"], s * 10 ** 6)
                    add("eth_call", [{"from": FROM, "to": FAKE, "data": "0x" + cd.hex()}, bhex, OV], ("call", r["route_hash"], s, d))
                    add("eth_estimateGas", [{"from": FROM, "to": FAKE, "value": "0x0", "data": "0x" + cd.hex()}, bhex, OV], ("gas", r["route_hash"], s, d))
                    cyc.append((r, other, s, d, cd))
        resA = batched(url, reqs, archive)
        ridA = {v: k for k, v in idmap.items()}   # tag -> id (tags uniques par bloc)

        def getA(tag):
            i = ridA.get(tag)
            return resA.get(i, (None, "ID_ABSENT")) if i is not None else (None, "ID_ABSENT")

        present = {p: bool((getA(("code", p))[0] or "0x") != "0x" and getA(("code", p))[0]) for p in pools}
        blk_res, _ = getA(("block",))
        try:
            bf = int(blk_res["baseFeePerGas"], 16) if blk_res and blk_res.get("baseFeePerGas") else None
            ts = int(blk_res["timestamp"], 16) if blk_res and blk_res.get("timestamp") else None
        except Exception:
            bf = ts = None
        ans, upd = _decode_anchor(getA(("oracle",))[0])
        eth_usd = anchor_eth_usd(ans, upd, ts)

        # round B : getL1Fee pour les cycles dont l'eth_call est ok
        reqsB, idmapB = [], {}
        ridB = [0]

        def addB(params, tag):
            reqsB.append(build_request(ridB[0], "eth_call", params))
            idmapB[tag] = ridB[0]; ridB[0] += 1

        stage1 = {}
        for (r, other, s, d, cd) in cyc:
            pres = present.get(r["uni_pool"], False) and present.get(r["slip_pool"], False)
            out_res, out_err = getA(("call", r["route_hash"], s, d))
            est = classify(out_err) if out_err else ("ok" if out_res is not None else "rpcerror")
            gu = None
            if est == "ok":
                gres, gerr = getA(("gas", r["route_hash"], s, d))
                if gres and not gerr and bf and bf > 0:
                    gu = int(gres, 16)
                    ser = serialize_dummy_1559(CHAIN_ID, gu, FAKE, cd, max(bf, 1) * 2, 10 ** 6)
                    addB([{"to": GASORACLE, "data": "0x" + (SEL_GETL1FEE + abi_encode(["bytes"], [ser])).hex()}, bhex],
                         (r["route_hash"], s, d))
            stage1[(r["route_hash"], s, d)] = (pres, out_res, out_err, est, gu)
        resB = batched(url, reqsB, archive) if reqsB else {}

        for (r, other, s, d, cd) in cyc:
            pres, out_res, out_err, est, gu = stage1[(r["route_hash"], s, d)]
            l1 = None; gas_ok = False
            if gu is not None:
                lres, lerr = resB.get(idmapB.get((r["route_hash"], s, d)), (None, "ID_ABSENT"))
                if lres and not lerr:
                    l1 = int(lres, 16); gas_ok = True
            anchor_ok = eth_usd is not None and eth_usd > 0
            rec = {"route_hash": r["route_hash"], "block": b, "size_usd": s, "direction": d}
            rec["category"] = classify_cycle(pres, est, anchor_ok, gas_ok)
            if rec["category"] == "ok":
                gnu = gas_normal_usdc(gas_normal_wei(gu, bf, l1), eth_usd)
                rec.update({"out_usdc_6dec": int(out_res, 16), "gas_units_l2": gu, "base_fee_l2": bf,
                            "l1_fee_wei": l1, "eth_usd": round(eth_usd, 4),
                            "upper_bound_usd": round(upper_bound_usdc(int(out_res, 16), s * 10 ** 6, gnu), 6)})
            elif rec["category"] == "CAPACITY":
                rec["reason_raw"] = (out_err.get("message", "") if isinstance(out_err, dict) else str(out_err))[:140]
            elif rec["category"] == "NON_CONCLUANT":
                rec["reason_raw"] = ("ancre/gas manquant" if est == "ok"
                                     else (out_err.get("message", "") if isinstance(out_err, dict) else str(out_err))[:140])
            records.append(rec)
    return records


# ----------------------------------------------------------------------------- reference SEQUENTIELLE (v1-exacte)
def measure_seq_ref(url: str, OV: dict, routes: list, blocks: list, sizes: list, dirs: list) -> list:
    """Replique EXACTEMENT la sequence d'appels v1 (sequentielle), pour la comparaison byte-a-byte du benchmark."""
    from d1_mev_boundary_control import raw_rpc
    records, code_cache, block_cache = [], {}, {}
    for r in routes:
        other = r["token1"] if Web3.to_checksum_address(r["token0"]) == USDC else r["token0"]
        for b in blocks:
            bhex = hex(b)

            def present_pool(pool):
                k = (pool, b)
                if k not in code_cache:
                    c, _ = raw_rpc(url, "eth_getCode", [pool, bhex]); code_cache[k] = bool(c and c != "0x")
                return code_cache[k]
            pres = present_pool(r["uni_pool"]) and present_pool(r["slip_pool"])
            if b not in block_cache:
                blk, _ = raw_rpc(url, "eth_getBlockByNumber", [bhex, False])
                try:
                    bf = int(blk["baseFeePerGas"], 16) if blk and blk.get("baseFeePerGas") else None
                    ts = int(blk["timestamp"], 16) if blk and blk.get("timestamp") else None
                except Exception:
                    bf = ts = None
                ar, _ = raw_rpc(url, "eth_call", [{"to": CHAINLINK_ETH_USD, "data": "0x" + SEL_LATESTROUNDDATA.hex()}, bhex])
                ans, upd = _decode_anchor(ar)
                block_cache[b] = (bf, anchor_eth_usd(ans, upd, ts))
            bf, eth_usd = block_cache[b]
            for s in sizes:
                for d in dirs:
                    rec = {"route_hash": r["route_hash"], "block": b, "size_usd": s, "direction": d}
                    if not pres:
                        rec["category"] = "WINDOW_UNAVAILABLE"; records.append(rec); continue
                    cd = exec_calldata(d, USDC, other, r["uni_fee"], r["slip_tickSpacing"], s * 10 ** 6)
                    out_res, out_err = raw_rpc(url, "eth_call", [{"from": FROM, "to": FAKE, "data": "0x" + cd.hex()}, bhex, OV])
                    est = classify(out_err) if out_err else ("ok" if out_res is not None else "rpcerror")
                    gu = l1 = None; gas_ok = False
                    if est == "ok":
                        gres, gerr = raw_rpc(url, "eth_estimateGas", [{"from": FROM, "to": FAKE, "value": "0x0", "data": "0x" + cd.hex()}, bhex, OV])
                        if gres and not gerr and bf and bf > 0:
                            gu = int(gres, 16)
                            ser = serialize_dummy_1559(CHAIN_ID, gu, FAKE, cd, max(bf, 1) * 2, 10 ** 6)
                            lres, lerr = raw_rpc(url, "eth_call", [{"to": GASORACLE, "data": "0x" + (SEL_GETL1FEE + abi_encode(["bytes"], [ser])).hex()}, bhex])
                            if lres and not lerr:
                                l1 = int(lres, 16); gas_ok = True
                    anchor_ok = eth_usd is not None and eth_usd > 0
                    rec["category"] = classify_cycle(pres, est, anchor_ok, gas_ok)
                    if rec["category"] == "ok":
                        gnu = gas_normal_usdc(gas_normal_wei(gu, bf, l1), eth_usd)
                        rec.update({"out_usdc_6dec": int(out_res, 16), "gas_units_l2": gu, "base_fee_l2": bf,
                                    "l1_fee_wei": l1, "eth_usd": round(eth_usd, 4),
                                    "upper_bound_usd": round(upper_bound_usdc(int(out_res, 16), s * 10 ** 6, gnu), 6)})
                    elif rec["category"] == "CAPACITY":
                        rec["reason_raw"] = (out_err.get("message", "") if isinstance(out_err, dict) else str(out_err))[:140]
                    elif rec["category"] == "NON_CONCLUANT":
                        rec["reason_raw"] = ("ancre/gas manquant" if est == "ok"
                                             else (out_err.get("message", "") if isinstance(out_err, dict) else str(out_err))[:140])
                    records.append(rec)
    return records


def _git(*a):
    try:
        return subprocess.run(["git", "-C", HERE, *a], capture_output=True, text=True).stdout.strip()
    except Exception:
        return ""


def provenance():
    rel = os.path.relpath(os.path.abspath(__file__), HERE).replace("\\", "/")
    with open(os.path.abspath(__file__), "rb") as f:
        rs = hashlib.sha256(f.read()).hexdigest()
    tr = bool(_git("ls-files", "--", rel)); st = _git("status", "--porcelain", "--", rel)
    cv = tr and not st; td = bool(_git("status", "--porcelain", "--untracked-files=no"))
    return {"git_hash": _git("rev-parse", "HEAD") or "UNVERSIONED", "runner_path": rel, "runner_sha256": rs,
            "code_versioned": bool(cv), "git_dirty": bool(td or not cv)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lot", type=int, required=True)
    args = ap.parse_args()
    prov = provenance()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    raw_dir = os.path.join(HERE, "data", "raw", "defi", "d2b2v2")
    run_dir = os.path.join(HERE, "runs", f"{stamp}_d2b2v2-measure-lot{args.lot:02d}")
    os.makedirs(raw_dir, exist_ok=True); os.makedirs(run_dir, exist_ok=True)
    cands = sorted(glob.glob(os.path.join(HERE, "runs", "*_d2b2-lots-frozen", "manifest.json")))
    plan = json.load(open(cands[-1], encoding="utf-8")) if cands else None
    lot = plan["lots"][args.lot] if (plan and 0 <= args.lot < len(plan["lots"])) else None
    b_start, b_end, nb = window_blocks(B1)
    manifest = {"phase": "D2B-2-v2-measure", "lot_index": args.lot, "transport": "JSON-RPC batch (semantique v1)",
                "window": {"B1": B1, "b_start": b_start, "b_end": b_end, "n_blocks": nb},
                "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), **prov}
    if lot is None:
        manifest["verdict"] = "NON_CONCLUANT"; manifest["reason"] = "plan/lot introuvable"
        json.dump(manifest, open(os.path.join(run_dir, "manifest.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print(json.dumps({"verdict": "NON_CONCLUANT", "reason": "plan/lot introuvable"})); return 0
    url = endpoints("base")[0]
    bytecode = json.load(open(os.path.join(HERE, "contracts", "CrossProtocolExecutor.json"), encoding="utf-8"))["deployed_bytecode"]
    OV = overrides(bytecode)
    archive = []
    records = measure_batched(url, OV, lot["routes"], list(range(b_start, b_end + 1)), SIZES_USD, ORIENTATIONS, archive)
    cat = {"ok": 0, "CAPACITY": 0, "WINDOW_UNAVAILABLE": 0, "NON_CONCLUANT": 0}
    for r in records:
        cat[r["category"]] = cat.get(r["category"], 0) + 1
    raw = json.dumps({"lot": args.lot, "window": [b_start, b_end], "transport_errors": archive, "cycles": records}, ensure_ascii=False).encode()
    raw_path = os.path.join(raw_dir, f"lot{args.lot:02d}_{stamp}.json")
    open(raw_path, "wb").write(raw)
    manifest.update({"categories_counts": cat, "cycles_traites": len(records), "transport_errors_count": len(archive),
                     "receipts": [{"name": f"lot{args.lot:02d}", "sha256": hashlib.sha256(raw).hexdigest(),
                                   "raw_path": os.path.relpath(raw_path, HERE).replace("\\", "/")}],
                     "verdict": "LOT_MESURE" if cat["NON_CONCLUANT"] == 0 else "LOT_MESURE_AVEC_NON_CONCLUANTS"})
    json.dump(manifest, open(os.path.join(run_dir, "manifest.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(json.dumps({"verdict": manifest["verdict"], "lot": args.lot, "cycles": len(records), "categories": cat,
                      "transport_errors": len(archive), "run_dir": os.path.relpath(run_dir, HERE).replace("\\", "/")}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
