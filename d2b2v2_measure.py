#!/usr/bin/env python
"""Runner D2B-2-v2 (MESURE par lot) — fidelite REGLE 3 corrigee + transport async borne sous limiteur CUPS.

Semantique de mesure identique a v1 sur le FOND (memes routes/ordre/blocs/tailles/executeur/state-overrides/
oracle Chainlink/formule), mais avec deux corrections validees (reouverture regle 3) :

1) FIDELITE (jamais de compensation silencieuse) : un getCode echoue (transport/CUPS) NE devient PLUS un faux
   "pool absent". WINDOW_UNAVAILABLE seulement si getCode REUSSIT et renvoie explicitement 0x. Tout echec
   transport/oracle/gas/getBlock/getL1Fee -> NON_CONCLUANT_INFRA (jamais gas=0). (cf. pool_state/exec_state/
   classify_cycle2 dans d2b2_measure.)

2) TRANSPORT : plus de gros batch burst (qui saturait le rate-limit PAR SECONDE -> reponses vides + 429). Ici
   transport async BORNE (concurrence K) sous un limiteur CUPS (token-bucket CU/s) regle AVANT le run par
   benchmark. concurrency=1 = reference sequentielle ; K = production. Resultat par appel = fonction de
   (method, params, blockTag) -> identique quelle que soit la concurrence.

POLITIQUE LOT (regle 3) : un seul cycle NON_CONCLUANT_INFRA (apres retries) -> LOT_NON_CONCLUANT_RETRY_REQUIRED ;
jamais de lot partiellement contamine accepte ; reprise = re-run ENTIER du lot (memes blocs/params/endpoint,
throttle plus bas) ; jamais de fusion partiel<->reprise. Namespace DISTINCT (runs/*_d2b2v2-measure-lotNN,
data/raw/defi/d2b2v2/). Lecture seule ; aucun contrat/cle/wallet/tx/capital. Gate --lot requise.
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone

from eth_abi import encode as abi_encode
from web3 import Web3

import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from archive_rpc import endpoints  # noqa: E402
from cups_transport import CupsLimiter, run_calls  # noqa: E402
from d1_mev_boundary_control import (  # noqa: E402
    serialize_dummy_1559, gas_normal_wei, mapping_slot, SEL_GETL1FEE, GASORACLE, CHAIN_ID)
from d2b1_liveness import exec_calldata, USDC, FAKE, FROM, HUGE, ORIENTATIONS  # noqa: E402
from d2b2_measure import (  # noqa: E402  (fonctions PURES + constantes ; classification fidelite corrigee)
    B1, SIZES_USD, USDC_SLOT, CHAINLINK_ETH_USD, SEL_LATESTROUNDDATA, window_blocks, anchor_eth_usd,
    gas_normal_usdc, upper_bound_usdc, pool_state, exec_state, classify_cycle2,
    CAT_OK, CAT_CAPACITY, CAT_WINDOW, CAT_INFRA, CATEGORIES)

HERE = os.path.dirname(os.path.abspath(__file__))
# Throttle PRODUCTION (a calibrer par d2b2_bench AVANT la serie ; conservateur par defaut).
CUPS_PROD = 220                  # budget CU/seconde du limiteur (Alchemy free ~330 -> marge)
CONCURRENCY_PROD = 5             # threads bornes


def overrides(bytecode: str) -> dict:
    return {FAKE: {"code": bytecode, "balance": hex(10 ** 24)},
            USDC: {"stateDiff": {mapping_slot(FAKE, USDC_SLOT): "0x" + HUGE.to_bytes(32, "big").hex()}}}


def _decode_anchor(res):
    if not res or len(res) < 2 + 64 * 5:
        return None, None
    b = bytes.fromhex(res[2:])
    return int.from_bytes(b[32:64], "big", signed=True), int.from_bytes(b[96:128], "big")


def measure_cycles(url, OV, routes, blocks, sizes, dirs, limiter, concurrency, archive):
    """Mesure (fidelite corrigee) sous limiteur CUPS + concurrence bornee. concurrency=1 -> reference ;
    K -> production. Schema record IDENTIQUE (route_hash/block/size_usd/direction/category[/champs ok]).
    3 rounds/bloc : R1 getCode+getBlock+oracle ; R2 eth_call(exec)+estimateGas (cycles 2 pools presents) ;
    R3 getL1Fee (cycles exec ok). Tous au MEME blockTag=b."""
    records = []
    for b in blocks:
        bhex = hex(b)
        # ---- R1 : presence (getCode par pool unique) + base_fee/timestamp + ancre ETH/USD ----
        pools = []
        for r in routes:
            for p in (r["uni_pool"], r["slip_pool"]):
                if p not in pools:
                    pools.append(p)
        r1_calls = [("eth_getCode", [p, bhex]) for p in pools]
        r1_calls.append(("eth_getBlockByNumber", [bhex, False]))
        r1_calls.append(("eth_call", [{"to": CHAINLINK_ETH_USD, "data": "0x" + SEL_LATESTROUNDDATA.hex()}, bhex]))
        r1 = run_calls(url, r1_calls, limiter, concurrency, archive)
        pstate = {p: pool_state(*r1[k]) for k, p in enumerate(pools)}
        blk_res, blk_err, blk_infra = r1[len(pools)]
        if blk_infra or blk_err is not None or blk_res is None:
            bf = ts = None
        else:
            try:
                bf = int(blk_res["baseFeePerGas"], 16) if blk_res.get("baseFeePerGas") else None
                ts = int(blk_res["timestamp"], 16) if blk_res.get("timestamp") else None
            except Exception:
                bf = ts = None
        orc_res, orc_err, orc_infra = r1[len(pools) + 1]
        eth_usd = None if (orc_infra or orc_err is not None) else anchor_eth_usd(*_decode_anchor(orc_res), ts)
        anchor_ok = eth_usd is not None and eth_usd > 0

        # ---- cycles a executer = les deux pools PRESENTS (sinon classe directement infra/window) ----
        cyc = []
        for r in routes:
            us, ss = pstate[r["uni_pool"]], pstate[r["slip_pool"]]
            if us != "present" or ss != "present":
                continue
            other = r["token1"] if Web3.to_checksum_address(r["token0"]) == USDC else r["token0"]
            for s in sizes:
                for d in dirs:
                    cyc.append((r, other, s, d, exec_calldata(d, USDC, other, r["uni_fee"], r["slip_tickSpacing"], s * 10 ** 6)))

        # ---- R2 : eth_call(exec) + estimateGas ----
        r2_calls = []
        for (r, other, s, d, cd) in cyc:
            r2_calls.append(("eth_call", [{"from": FROM, "to": FAKE, "data": "0x" + cd.hex()}, bhex, OV]))
            r2_calls.append(("eth_estimateGas", [{"from": FROM, "to": FAKE, "value": "0x0", "data": "0x" + cd.hex()}, bhex, OV]))
        r2 = run_calls(url, r2_calls, limiter, concurrency, archive)

        # ---- R3 : getL1Fee pour exec ok + estimateGas dispo + base_fee dispo ----
        stage, r3_calls, r3_index = {}, [], {}
        for ci, (r, other, s, d, cd) in enumerate(cyc):
            out_res, out_err, out_infra = r2[2 * ci]
            gas_res, gas_err, gas_infra = r2[2 * ci + 1]
            est = exec_state(out_res, out_err, out_infra)
            gu = None
            if est == "ok" and not (gas_infra or gas_err is not None or gas_res is None) and bf and bf > 0:
                gu = int(gas_res, 16)
                ser = serialize_dummy_1559(CHAIN_ID, gu, FAKE, cd, max(bf, 1) * 2, 10 ** 6)
                r3_index[(r["route_hash"], s, d)] = len(r3_calls)
                r3_calls.append(("eth_call", [{"to": GASORACLE, "data": "0x" + (SEL_GETL1FEE + abi_encode(["bytes"], [ser])).hex()}, bhex]))
            stage[(r["route_hash"], s, d)] = (out_res, out_err, est, gu)
        r3 = run_calls(url, r3_calls, limiter, concurrency, archive) if r3_calls else []

        # ---- classification finale (ordre deterministe routes x sizes x dirs) ----
        for r in routes:
            us, ss = pstate[r["uni_pool"]], pstate[r["slip_pool"]]
            for s in sizes:
                for d in dirs:
                    key = (r["route_hash"], s, d)
                    rec = {"route_hash": r["route_hash"], "block": b, "size_usd": s, "direction": d}
                    if key not in stage:                                  # pool infra ou absent
                        rec["category"] = classify_cycle2(us, ss, "infra", anchor_ok, False)
                        if rec["category"] == CAT_INFRA:
                            rec["reason_raw"] = "getCode infra (presence indeterminee, retry requis)"
                        records.append(rec); continue
                    out_res, out_err, est, gu = stage[key]
                    l1 = None; gas_ok = False
                    if est == "ok" and gu is not None:
                        idx = r3_index.get(key)
                        if idx is not None:
                            lres, lerr, linfra = r3[idx]
                            if not linfra and lerr is None and lres is not None:
                                l1 = int(lres, 16); gas_ok = True
                    rec["category"] = classify_cycle2(us, ss, est, anchor_ok, gas_ok)
                    if rec["category"] == CAT_OK:
                        gnu = gas_normal_usdc(gas_normal_wei(gu, bf, l1), eth_usd)
                        rec.update({"out_usdc_6dec": int(out_res, 16), "gas_units_l2": gu, "base_fee_l2": bf,
                                    "l1_fee_wei": l1, "eth_usd": round(eth_usd, 4),
                                    "upper_bound_usd": round(upper_bound_usdc(int(out_res, 16), s * 10 ** 6, gnu), 6)})
                    elif rec["category"] == CAT_CAPACITY:
                        rec["reason_raw"] = (out_err.get("message", "") if isinstance(out_err, dict) else str(out_err))[:140]
                    elif rec["category"] == CAT_INFRA:
                        if est == "infra":
                            rec["reason_raw"] = ((out_err.get("message", "") if isinstance(out_err, dict) else str(out_err))[:140]
                                                 if out_err else "exec infra (pas de reponse)")
                        elif not anchor_ok:
                            rec["reason_raw"] = "oracle/ancre indisponible (infra)"
                        else:
                            rec["reason_raw"] = "gas/getL1Fee indisponible (infra)"
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
    ap.add_argument("--cups", type=float, default=CUPS_PROD, help="budget CU/s du limiteur (def: %d)" % CUPS_PROD)
    ap.add_argument("--concurrency", type=int, default=CONCURRENCY_PROD, help="threads bornes (def: %d)" % CONCURRENCY_PROD)
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
    manifest = {"phase": "D2B-2-v2-measure", "lot_index": args.lot,
                "transport": "async borne + limiteur CUPS (token-bucket CU/s) ; plus de batch burst",
                "throttle": {"cups": args.cups, "concurrency": args.concurrency},
                "fidelite": "regle 3 corrigee : getCode echoue -> NON_CONCLUANT_INFRA ; WINDOW_UNAVAILABLE "
                            "seulement si getCode=0x confirme ; oracle/gas/block/l1fee echoue -> INFRA, jamais gas=0",
                "categories": CATEGORIES, "window": {"B1": B1, "b_start": b_start, "b_end": b_end, "n_blocks": nb},
                "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), **prov}
    if lot is None:
        manifest["verdict"] = "NON_CONCLUANT"; manifest["reason"] = "plan/lot introuvable"
        json.dump(manifest, open(os.path.join(run_dir, "manifest.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print(json.dumps({"verdict": "NON_CONCLUANT", "reason": "plan/lot introuvable"})); return 0
    url = endpoints("base")[0]
    bytecode = json.load(open(os.path.join(HERE, "contracts", "CrossProtocolExecutor.json"), encoding="utf-8"))["deployed_bytecode"]
    OV = overrides(bytecode)
    archive = []
    limiter = CupsLimiter(args.cups)
    records = measure_cycles(url, OV, lot["routes"], list(range(b_start, b_end + 1)), SIZES_USD, ORIENTATIONS,
                             limiter, args.concurrency, archive)
    cat = {c: 0 for c in CATEGORIES}
    for r in records:
        cat[r["category"]] = cat.get(r["category"], 0) + 1
    infra = cat[CAT_INFRA]
    verdict = "LOT_NON_CONCLUANT_RETRY_REQUIRED" if infra > 0 else "LOT_MESURE"
    raw = json.dumps({"lot": args.lot, "window": [b_start, b_end], "throttle": {"cups": args.cups, "concurrency": args.concurrency},
                      "transport_errors": archive, "cycles": records}, ensure_ascii=False).encode()
    raw_path = os.path.join(raw_dir, f"lot{args.lot:02d}_{stamp}.json")
    open(raw_path, "wb").write(raw)
    manifest.update({"categories_counts": cat, "cycles_traites": len(records), "transport_errors_count": len(archive),
                     "receipts": [{"name": f"lot{args.lot:02d}", "sha256": hashlib.sha256(raw).hexdigest(),
                                   "raw_path": os.path.relpath(raw_path, HERE).replace("\\", "/")}],
                     "verdict": verdict,
                     "note": ("NON_CONCLUANT_INFRA = echec transport/CUPS/oracle/gas apres retries -> lot ENTIER "
                              "a re-run (jamais fusionne). LOT_MESURE seulement si 0 infra. Aucun verdict economique.")})
    json.dump(manifest, open(os.path.join(run_dir, "manifest.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(json.dumps({"verdict": verdict, "lot": args.lot, "cycles": len(records), "categories": cat,
                      "transport_errors": len(archive), "run_dir": os.path.relpath(run_dir, HERE).replace("\\", "/")},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
