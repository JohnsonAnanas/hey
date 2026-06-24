#!/usr/bin/env python
"""Runner D2B-2 (MESURE par lot) — borne atomique cross-protocole, READ-ONLY. NE PAS lancer sans --lot + go.

Mesure, pour les routes d'UN lot gele (d2b2_lots), la borne atomique sur la fenetre et la grille figees,
via l'executeur simule D1.6. Les 4 regles pre-enregistrees sont encodees ici :

REGLE 1 (fenetre, blockTag stable) : B_end = B1 = 47762470 ; B_start = B1-299 ; 300 blocs INCLUSIFS. Pour
CHAQUE cycle (route, bloc b, taille, direction), eth_call (sortie) + eth_estimateGas (gas L2) + getL1Fee
(L1/data) utilisent TOUS le MEME blockTag=b. JAMAIS 'latest', JAMAIS un gas calibre a la tete.

REGLE 2 (formule, ancre ETH/USD independante lue au bloc b) :
  upper_bound_USDC = (USDC_final - USDC_input)/1e6 - gas_normal_USDC
  gas_normal_wei = gas_units_L2(b) * base_fee_L2(b) + l1Fee(b) ; priorite MEV EXCLUE -> borne superieure.
  gas_normal_USDC = gas_normal_wei/1e18 * eth_usd(b). ANCRE = Uniswap v3 QuoterV2 (0x3d4e44...), WETH/USDC
  fee=500, TAILLE = 1 WETH (1e18 wei) -> out_USDC(6dec)/1e6 = USD/WETH, lue au MEME bloc b. INDEPENDANTE de
  la route (paire WETH/USDC, usage = conversion gas seulement). Si l'ancre manque a un bloc -> NON_CONCLUANT
  pour ce point, JAMAIS gas=0.

REGLE 3 (disponibilite historique, categories SEPAREES) :
  - pool/code ABSENT au bloc b -> WINDOW_UNAVAILABLE (pas un revert de capacite) ;
  - revert d'EXECUTION sur une route reellement presente (pools avec code) -> resultat de CAPACITE ;
  - erreur RPC/override/quoteur/cout -> NON_CONCLUANT ;
  - ces categories sont separees dans les sorties.

REGLE 4 : les 29 lots restent obligatoires, dans l'ordre gele, sans modification apres un resultat. Reverts
et indisponibilites RESTENT dans les raw et manifests.

Lecture seule ; aucun contrat/cle/wallet/approbation/tx/capital (override de code = simulation). Gate :
--lot N requis (pas de run de serie accidentel).
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
from sim.quote_v3 import V3Quoter  # noqa: E402
from d1_mev_boundary_control import (  # noqa: E402
    raw_rpc, serialize_dummy_1559, gas_normal_wei, mapping_slot, SEL_GETL1FEE, GASORACLE, CHAIN_ID, WETH)
from d2b1_liveness import exec_calldata, classify, USDC, FAKE, FROM, HUGE, ORIENTATIONS  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
B1 = 47762470
N_BLOCKS = 300
SIZES_USD = [250, 1000, 2500, 5000, 10000]
ANCHOR_SIZE_WETH = 10 ** 18      # 1 WETH (ancre ETH/USD)
ANCHOR_FEE = 500                 # Uniswap v3 WETH/USDC, palier le plus liquide
USDC_SLOT = 9                    # FiatToken (auto-verifie au run)


# ----------------------------------------------------------------------------- fonctions PURES (testables)
def window_blocks(b1: int, n: int = N_BLOCKS):
    """Fenetre INCLUSIVE [b1-(n-1), b1] -> (b_start, b_end, n_blocs)."""
    return b1 - (n - 1), b1, n


def gas_normal_usdc(gas_wei: int, eth_usd: float) -> float:
    return gas_wei / 1e18 * eth_usd


def upper_bound_usdc(out_usdc_6dec: int, in_usdc_6dec: int, gas_norm_usdc: float) -> float:
    """upper_bound (USD) = (sortie - entree) en USDC - gas converti. Priorite MEV exclue (borne sup)."""
    return (out_usdc_6dec - in_usdc_6dec) / 1e6 - gas_norm_usdc


def classify_cycle(pool_present: bool, exec_status: str, anchor_ok: bool, gas_ok: bool) -> str:
    """Categories SEPAREES (regle 3). exec_status: 'ok'/'revert'/'rpcerror'."""
    if not pool_present:
        return "WINDOW_UNAVAILABLE"
    if exec_status == "rpcerror":
        return "NON_CONCLUANT"
    if exec_status == "revert":
        return "CAPACITY"                       # route presente, revert d'execution = capacite
    if not (anchor_ok and gas_ok):
        return "NON_CONCLUANT"                  # ancre/gas manquant -> NON_CONCLUANT, jamais gas=0
    return "ok"


# ----------------------------------------------------------------------------- gouvernance
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


def load_lot(lot_index: int):
    cands = sorted(glob.glob(os.path.join(HERE, "runs", "*_d2b2-lots-frozen", "manifest.json")))
    if not cands:
        return None, None
    plan = json.load(open(cands[-1], encoding="utf-8"))
    lots = plan["lots"]
    if not (0 <= lot_index < len(lots)):
        return plan, None
    return plan, lots[lot_index]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lot", type=int, required=True, help="index de lot gele (0..28) -- requis")
    args = ap.parse_args()

    prov = provenance()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    raw_dir = os.path.join(HERE, "data", "raw", "defi", "d2b2")
    run_dir = os.path.join(HERE, "runs", f"{stamp}_d2b2-measure-lot{args.lot:02d}")
    os.makedirs(raw_dir, exist_ok=True)
    os.makedirs(run_dir, exist_ok=True)
    plan, lot = load_lot(args.lot)
    b_start, b_end, nb = window_blocks(B1)
    manifest = {
        "phase": "D2B-2-measure", "lot_index": args.lot, "track": "defi-samechain-mev-boundary", "chain": "base",
        "read_only": True, "no_contract_key_wallet_tx_capital": True,
        "window": {"B1": B1, "b_start": b_start, "b_end": b_end, "n_blocks": nb, "inclusive": True,
                   "blockTag": "b par cycle (eth_call/estimateGas/getL1Fee) ; jamais latest/tete"},
        "formula": "upper_bound_USDC = (USDC_final-USDC_input)/1e6 - gas_normal_wei/1e18*eth_usd(b) ; priorite MEV EXCLUE",
        "eth_usd_anchor": {"source": "Uniswap v3 QuoterV2 0x3d4e44Eb1374240CE5F1B871ab261CD16335B76a",
                           "pair": "WETH/USDC", "fee": ANCHOR_FEE, "size_weth_wei": ANCHOR_SIZE_WETH,
                           "read_at": "meme bloc b ; manquant -> NON_CONCLUANT, jamais gas=0", "independent": True},
        "categories": ["ok", "CAPACITY", "WINDOW_UNAVAILABLE", "NON_CONCLUANT"],
        "params": {"sizes_usd": SIZES_USD, "directions": ORIENTATIONS, "usdc": USDC, "usdc_slot": USDC_SLOT},
        "lots_source": (os.path.relpath(sorted(glob.glob(os.path.join(HERE, "runs", "*_d2b2-lots-frozen",
                        "manifest.json")))[-1], HERE).replace("\\", "/") if plan else None),
        "plan_digest": (plan or {}).get("plan_digest_sha256"),
        "created_utc": now_utc(), **prov,
    }
    if plan is None or lot is None:
        manifest["verdict"] = "NON_CONCLUANT"
        manifest["abstention_reason"] = "plan de lots gele introuvable ou index hors borne"
        with open(os.path.join(run_dir, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        print(json.dumps({"verdict": "NON_CONCLUANT", "reason": manifest["abstention_reason"]}))
        return 0

    url = endpoints("base")[0]
    bytecode = json.load(open(os.path.join(HERE, "contracts", "CrossProtocolExecutor.json"),
                              encoding="utf-8"))["deployed_bytecode"]
    uq = V3Quoter(w3=_Web3(url), family="univ3")
    OV = {FAKE: {"code": bytecode, "balance": hex(10 ** 24)},
          USDC: {"stateDiff": {mapping_slot(FAKE, USDC_SLOT): "0x" + HUGE.to_bytes(32, "big").hex()}}}

    # garde-fous (slot USDC sur l'executeur + code-override) au bloc B1
    if not _slot_ok(url, OV) or not _code_override_ok(url):
        return _abort(run_dir, manifest, "garde-fou KO (slot USDC ou code-override) -> NON_CONCLUANT")

    cycles, cat = [], {"ok": 0, "CAPACITY": 0, "WINDOW_UNAVAILABLE": 0, "NON_CONCLUANT": 0}
    code_cache, anchor_cache, bf_cache = {}, {}, {}
    for r in lot["routes"]:
        other = r["token1"] if Web3.to_checksum_address(r["token0"]) == USDC else r["token0"]
        for b in range(b_start, b_end + 1):
            bhex = hex(b)
            present = _pool_present(url, r["uni_pool"], b, code_cache) and _pool_present(url, r["slip_pool"], b, code_cache)
            eth_usd = anchor_cache.get(b) if b in anchor_cache else anchor_cache.setdefault(b, _anchor(uq, b))
            bf = bf_cache.get(b) if b in bf_cache else bf_cache.setdefault(b, _base_fee(url, bhex))
            for s in SIZES_USD:
                for d in ORIENTATIONS:
                    rec = {"route_hash": r["route_hash"], "block": b, "size_usd": s, "direction": d}
                    if not present:
                        rec["category"] = "WINDOW_UNAVAILABLE"
                        cat["WINDOW_UNAVAILABLE"] += 1; cycles.append(rec); continue
                    cd = exec_calldata(d, USDC, other, r["uni_fee"], r["slip_tickSpacing"], s * 10 ** 6)
                    out_res, out_err = raw_rpc(url, "eth_call", [{"from": FROM, "to": FAKE, "data": "0x" + cd.hex()}, bhex, OV])
                    est = classify(out_err) if out_err else "ok"
                    if est == "ok" and out_res is None:
                        est = "rpcerror"
                    gas_ok = anchor_ok = False
                    gu = l1 = None
                    if est == "ok":
                        gres, gerr = raw_rpc(url, "eth_estimateGas", [{"from": FROM, "to": FAKE, "value": "0x0", "data": "0x" + cd.hex()}, bhex, OV])
                        if gres and not gerr and bf and bf > 0:
                            gu = int(gres, 16)
                            ser = serialize_dummy_1559(CHAIN_ID, gu, FAKE, cd, max(bf, 1) * 2, 10 ** 6)
                            lres, lerr = raw_rpc(url, "eth_call", [{"to": GASORACLE, "data": "0x" + (SEL_GETL1FEE + abi_encode(["bytes"], [ser])).hex()}, bhex])
                            if lres and not lerr:
                                l1 = int(lres, 16); gas_ok = True
                        anchor_ok = eth_usd is not None and eth_usd > 0
                    rec["category"] = classify_cycle(present, est, anchor_ok, gas_ok)
                    if rec["category"] == "ok":
                        gnw = gas_normal_wei(gu, bf, l1)
                        gnu = gas_normal_usdc(gnw, eth_usd)
                        rec.update({"out_usdc_6dec": int(out_res, 16), "gas_units_l2": gu, "base_fee_l2": bf,
                                    "l1_fee_wei": l1, "eth_usd": round(eth_usd, 4),
                                    "upper_bound_usd": round(upper_bound_usdc(int(out_res, 16), s * 10 ** 6, gnu), 6)})
                    elif rec["category"] == "CAPACITY":
                        rec["reason"] = (out_err.get("message", "") if isinstance(out_err, dict) else str(out_err))[:140]
                    elif rec["category"] == "NON_CONCLUANT":
                        rec["reason"] = ("ancre/gas manquant" if est == "ok" else
                                         (out_err.get("message", "") if isinstance(out_err, dict) else str(out_err))[:140])
                    cat[rec["category"]] += 1
                    cycles.append(rec)

    raw = json.dumps({"lot": args.lot, "window": [b_start, b_end], "cycles": cycles}, ensure_ascii=False).encode()
    raw_path = os.path.join(raw_dir, f"lot{args.lot:02d}_{stamp}.json")
    with open(raw_path, "wb") as f:
        f.write(raw)
    manifest.update({
        "routes_in_lot": [r["route_hash"] for r in lot["routes"]],
        "cycles_total_attendus": len(lot["routes"]) * nb * len(SIZES_USD) * len(ORIENTATIONS),
        "cycles_traites": len(cycles), "categories_counts": cat,
        "receipts": [{"name": f"lot{args.lot:02d}", "sha256": hashlib.sha256(raw).hexdigest(),
                      "raw_path": os.path.relpath(raw_path, HERE).replace("\\", "/")}],
        "verdict": "LOT_MESURE" if cat["NON_CONCLUANT"] == 0 else "LOT_MESURE_AVEC_NON_CONCLUANTS",
        "note": ("Bornes superieures hors priorite MEV ; AUCUN verdict economique. Reverts (CAPACITY) et "
                 "indisponibilites (WINDOW_UNAVAILABLE) CONSERVES dans raw+manifest. Lot du plan gele, ordre "
                 "inchange. Les 29 lots restent obligatoires."),
    })
    with open(os.path.join(run_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(json.dumps({"verdict": manifest["verdict"], "lot": args.lot, "cycles": len(cycles),
                      "categories": cat, "run_dir": os.path.relpath(run_dir, HERE).replace("\\", "/")},
                     ensure_ascii=False, indent=2))
    return 0


# --- helpers reseau (isoles pour lisibilite ; non purs) ---
def _Web3(url):
    return Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 40}))


def _slot_ok(url, ov):
    from eth_abi import encode as enc
    sel = Web3.keccak(text="balanceOf(address)")[:4]
    r, e = raw_rpc(url, "eth_call", [{"to": USDC, "data": "0x" + (sel + enc(["address"], [FAKE])).hex()}, hex(B1), ov])
    return bool(r) and not e and int(r, 16) == HUGE


def _code_override_ok(url):
    r, e = raw_rpc(url, "eth_call", [{"from": FROM, "to": FAKE, "data": "0x"}, hex(B1),
                                     {FAKE: {"code": "0x602a60005260206000f3", "balance": hex(10 ** 24)}}])
    return bool(r) and not e and int(r, 16) == 42


def _pool_present(url, pool, b, cache):
    key = (pool, b)
    if key not in cache:
        c, _ = raw_rpc(url, "eth_getCode", [pool, hex(b)])
        cache[key] = bool(c and c != "0x")
    return cache[key]


def _anchor(uq, b):
    q = uq.quote(WETH, USDC, ANCHOR_SIZE_WETH, ANCHOR_FEE, b)
    return (q[0] / 1e6) if q else None


def _base_fee(url, bhex):
    blk, e = raw_rpc(url, "eth_getBlockByNumber", [bhex, False])
    try:
        return int(blk["baseFeePerGas"], 16) if blk and blk.get("baseFeePerGas") else None
    except Exception:
        return None


def _abort(run_dir, manifest, reason):
    manifest["verdict"] = "NON_CONCLUANT"; manifest["abstention_reason"] = reason
    with open(os.path.join(run_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(json.dumps({"verdict": "NON_CONCLUANT", "reason": reason}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
