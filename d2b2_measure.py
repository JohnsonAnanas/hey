#!/usr/bin/env python
"""Runner D2B-2 (MESURE par lot) — borne atomique cross-protocole, READ-ONLY. NE PAS lancer sans --lot + go.

Mesure, pour les routes d'UN lot gele (d2b2_lots), la borne atomique sur la fenetre et la grille figees,
via l'executeur simule D1.6. Les 4 regles pre-enregistrees sont encodees ici :

REGLE 1 (fenetre, blockTag stable) : B_end = B1 = 47762470 ; B_start = B1-299 ; 300 blocs INCLUSIFS. Pour
CHAQUE cycle (route, bloc b, taille, direction), eth_call (sortie) + eth_estimateGas (gas L2) + getL1Fee
(L1/data) utilisent TOUS le MEME blockTag=b. JAMAIS 'latest', JAMAIS un gas calibre a la tete.

REGLE 2 (formule, ancre ETH/USD ON-CHAIN INDEPENDANTE des pools cibles) :
  upper_bound_USDC = (USDC_final - USDC_input)/1e6 - gas_normal_USDC
  gas_normal_wei = gas_units_L2(b) * base_fee_L2(b) + l1Fee(b) ; priorite MEV EXCLUE -> borne superieure.
  gas_normal_USDC = gas_normal_wei/1e18 * eth_usd(b). ANCRE = feed Chainlink ETH/USD canonique Base
  0x71041dddad3595F9CEd3DcCFBe3D1F4b0a16Bb70, decimals=8, fonction latestRoundData(), lue au MEME bloc b.
  Garde-fous : answer > 0 ; updatedAt <= timestamp(b) ; staleness = ts(b)-updatedAt <= STALENESS_MAX (3600 s,
  prefixe avant donnees). INDEPENDANTE des pools mesures (oracle, pas un pool). Absence/staleness/erreur du
  feed -> NON_CONCLUANT pour ce point, JAMAIS gas=0.

REGLE 3 (disponibilite historique, categories SEPAREES ; FIDELITE CORRIGEE -- reouverture validee) :
  - WINDOW_UNAVAILABLE UNIQUEMENT si getCode REUSSIT et renvoie explicitement 0x (absence CONFIRMEE) ;
  - getCode/oracle/gas/getBlock/getL1Fee echoue (transport/CUPS/timeout) -> NON_CONCLUANT_INFRA : un getCode
    echoue ne doit JAMAIS etre lu comme "pool absent", et l'ancre/gas manquant ne doit JAMAIS donner gas=0 ;
  - revert d'EXECUTION sur une route reellement presente (pools avec code) -> resultat de CAPACITE
    (limite OPERATIONNELLE ; reason BRUT conserve, pas reduit a la liquidite) ;
  - un seul NON_CONCLUANT_INFRA dans un lot -> LOT_NON_CONCLUANT_RETRY_REQUIRED (re-run lot ENTIER, jamais
    fusionne) ; ces categories sont separees dans les sorties (cf. classify_cycle2).

REGLE 4 : les 29 lots restent obligatoires, dans l'ordre gele, sans modification apres un resultat. Reverts
et indisponibilites RESTENT dans les raw et manifests.

Lecture seule ; aucun contrat/cle/wallet/approbation/tx/capital (override de code = simulation). Gate :
--lot N requise (pas de run de serie accidentel).
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
from d1_mev_boundary_control import (  # noqa: E402
    raw_rpc, serialize_dummy_1559, gas_normal_wei, mapping_slot, SEL_GETL1FEE, GASORACLE, CHAIN_ID)
from d2b1_liveness import exec_calldata, classify, USDC, FAKE, FROM, HUGE, ORIENTATIONS  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
B1 = 47762470
N_BLOCKS = 300
SIZES_USD = [250, 1000, 2500, 5000, 10000]
USDC_SLOT = 9                    # FiatToken (auto-verifie au run)
# Ancre ETH/USD : feed Chainlink canonique Base, INDEPENDANT des pools cibles (oracle, pas un pool).
CHAINLINK_ETH_USD = Web3.to_checksum_address("0x71041dddad3595F9CEd3DcCFBe3D1F4b0a16Bb70")
CHAINLINK_DECIMALS = 8
STALENESS_MAX_S = 3600           # seuil de staleness PREENREGISTRE (avant donnees) ; max observe fenetre = 618 s
SEL_LATESTROUNDDATA = Web3.keccak(text="latestRoundData()")[:4]


# ----------------------------------------------------------------------------- fonctions PURES (testables)
def window_blocks(b1: int, n: int = N_BLOCKS):
    """Fenetre INCLUSIVE [b1-(n-1), b1] -> (b_start, b_end, n_blocs)."""
    return b1 - (n - 1), b1, n


def anchor_eth_usd(answer: int | None, updated_at: int | None, block_ts: int | None,
                   decimals: int = CHAINLINK_DECIMALS, staleness_max: int = STALENESS_MAX_S):
    """ETH/USD depuis Chainlink avec garde-fous. None si invalide -> declenche NON_CONCLUANT (jamais gas=0).

    Exige : answer > 0 ; updatedAt <= ts(b) (pas dans le futur) ; ts(b)-updatedAt <= staleness_max.
    """
    if answer is None or block_ts is None or updated_at is None:
        return None
    if answer <= 0:
        return None
    if updated_at > block_ts:
        return None
    if block_ts - updated_at > staleness_max:
        return None
    return answer / (10 ** decimals)


def gas_normal_usdc(gas_wei: int, eth_usd: float) -> float:
    return gas_wei / 1e18 * eth_usd


def upper_bound_usdc(out_usdc_6dec: int, in_usdc_6dec: int, gas_norm_usdc: float) -> float:
    """upper_bound (USD) = (sortie - entree) en USDC - gas converti. Priorite MEV exclue (borne sup)."""
    return (out_usdc_6dec - in_usdc_6dec) / 1e6 - gas_norm_usdc


def classify_cycle(pool_present: bool, exec_status: str, anchor_ok: bool, gas_ok: bool) -> str:
    """[LEGACY] Categories (regle 3 v1). exec_status: 'ok'/'revert'/'rpcerror'. Conserve pour compat tests.

    BUG DE FIDELITE connu : prend un bool pool_present qui ne distingue PAS "getCode a renvoye 0x" (absence
    confirmee) de "getCode a echoue" (infra). NE PLUS UTILISER dans les runners -> classify_cycle2.
    """
    if not pool_present:
        return "WINDOW_UNAVAILABLE"
    if exec_status == "rpcerror":
        return "NON_CONCLUANT"
    if exec_status == "revert":
        return "CAPACITY"                       # route presente, revert d'execution = capacite operationnelle
    if not (anchor_ok and gas_ok):
        return "NON_CONCLUANT"                  # ancre/gas manquant -> NON_CONCLUANT, jamais gas=0
    return "ok"


# --- Regle 3 CORRIGEE (fidelite) : tri-etats + categorie infra explicite ; jamais de faux "absent" ---
CAT_OK = "ok"
CAT_CAPACITY = "CAPACITY"
CAT_WINDOW = "WINDOW_UNAVAILABLE"
CAT_INFRA = "NON_CONCLUANT_INFRA"               # getCode/oracle/gas/getBlock/getL1Fee/transport echoue -> retry lot
CATEGORIES = [CAT_OK, CAT_CAPACITY, CAT_WINDOW, CAT_INFRA]


def pool_state(result, error, infra: bool) -> str:
    """Tri-etat de presence d'un pool a partir d'une reponse getCode (result, error, infra).

    'infra' si echec transport/CUPS (infra) OU erreur RPC OU resultat absent -> presence INDETERMINEE.
    'absent' UNIQUEMENT si getCode a REUSSI et renvoie explicitement '0x'. 'present' si code non vide.
    """
    if infra or error is not None or result is None:
        return "infra"
    if result == "0x":
        return "absent"
    return "present"


def exec_state(result, error, infra: bool) -> str:
    """Tri-etat de l'eth_call d'execution -> 'ok' / 'revert' (echec deterministe = capacite) / 'infra'."""
    if infra:
        return "infra"
    if error is not None:
        return "revert" if classify(error) == "revert" else "infra"
    if result is None:
        return "infra"
    return "ok"


def classify_cycle2(uni_state: str, slip_state: str, exec_st: str, anchor_ok: bool, gas_ok: bool) -> str:
    """Categorie d'un cycle a partir des tri-etats. L'INFRA prime : on ne conclut JAMAIS absence/capacite
    sur information incomplete. WINDOW_UNAVAILABLE uniquement sur absence CONFIRMEE (getCode reussi = 0x)."""
    if uni_state == "infra" or slip_state == "infra":
        return CAT_INFRA
    if uni_state == "absent" or slip_state == "absent":
        return CAT_WINDOW                       # au moins un pool confirme absent -> fenetre indisponible
    if exec_st == "infra":
        return CAT_INFRA
    if exec_st == "revert":
        return CAT_CAPACITY
    if not (anchor_ok and gas_ok):
        return CAT_INFRA                        # oracle/gas/getBlock/getL1Fee manquant -> infra, jamais gas=0
    return CAT_OK


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
        return None, None, None
    plan = json.load(open(cands[-1], encoding="utf-8"))
    lots = plan["lots"]
    if not (0 <= lot_index < len(lots)):
        return plan, None, cands[-1]
    return plan, lots[lot_index], cands[-1]


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
    plan, lot, plan_path = load_lot(args.lot)
    b_start, b_end, nb = window_blocks(B1)
    manifest = {
        "phase": "D2B-2-measure", "lot_index": args.lot, "track": "defi-samechain-mev-boundary", "chain": "base",
        "read_only": True, "no_contract_key_wallet_tx_capital": True,
        "window": {"B1": B1, "b_start": b_start, "b_end": b_end, "n_blocks": nb, "inclusive": True,
                   "blockTag": "b par cycle (eth_call/estimateGas/getL1Fee) ; jamais latest/tete"},
        "formula": "upper_bound_USDC = (USDC_final-USDC_input)/1e6 - gas_normal_wei/1e18*eth_usd(b) ; priorite MEV EXCLUE",
        "eth_usd_anchor": {"type": "Chainlink feed (oracle, INDEPENDANT des pools cibles)",
                           "feed": CHAINLINK_ETH_USD, "decimals": CHAINLINK_DECIMALS,
                           "function": "latestRoundData()", "read_at": "meme bloc b",
                           "guards": ["answer>0", "updatedAt<=ts(b)", f"ts(b)-updatedAt<={STALENESS_MAX_S}s"],
                           "staleness_max_s": STALENESS_MAX_S,
                           "on_invalid": "NON_CONCLUANT (jamais gas=0)"},
        "categories": CATEGORIES,
        "params": {"sizes_usd": SIZES_USD, "directions": ORIENTATIONS, "usdc": USDC, "usdc_slot": USDC_SLOT},
        "lots_source": (os.path.relpath(plan_path, HERE).replace("\\", "/") if plan_path else None),
        "plan_digest": (plan or {}).get("plan_digest_sha256"),
        "created_utc": now_utc(), **prov,
    }
    if plan is None or lot is None:
        return _abort(run_dir, manifest, "plan de lots gele introuvable ou index hors borne")

    url = endpoints("base")[0]
    bytecode = json.load(open(os.path.join(HERE, "contracts", "CrossProtocolExecutor.json"),
                              encoding="utf-8"))["deployed_bytecode"]
    OV = {FAKE: {"code": bytecode, "balance": hex(10 ** 24)},
          USDC: {"stateDiff": {mapping_slot(FAKE, USDC_SLOT): "0x" + HUGE.to_bytes(32, "big").hex()}}}
    if not _slot_ok(url, OV) or not _code_override_ok(url):
        return _abort(run_dir, manifest, "garde-fou KO (slot USDC ou code-override) -> NON_CONCLUANT")

    cycles, cat = [], {c: 0 for c in CATEGORIES}
    code_cache, block_cache = {}, {}     # block_cache[b] = (base_fee, eth_usd)
    for r in lot["routes"]:
        other = r["token1"] if Web3.to_checksum_address(r["token0"]) == USDC else r["token0"]
        for b in range(b_start, b_end + 1):
            bhex = hex(b)
            us = _pool_state(url, r["uni_pool"], b, code_cache)
            ss = _pool_state(url, r["slip_pool"], b, code_cache)
            both_present = us == "present" and ss == "present"
            if b not in block_cache:
                block_cache[b] = _block_bf_anchor(url, bhex)
            bf, eth_usd = block_cache[b]
            anchor_ok = eth_usd is not None and eth_usd > 0
            for s in SIZES_USD:
                for d in ORIENTATIONS:
                    rec = {"route_hash": r["route_hash"], "block": b, "size_usd": s, "direction": d}
                    if not both_present:
                        rec["category"] = classify_cycle2(us, ss, "infra", anchor_ok, False)
                        if rec["category"] == CAT_INFRA:
                            rec["reason_raw"] = "getCode infra (presence indeterminee, retry requis)"
                        cat[rec["category"]] += 1; cycles.append(rec); continue
                    cd = exec_calldata(d, USDC, other, r["uni_fee"], r["slip_tickSpacing"], s * 10 ** 6)
                    out_res, out_err = raw_rpc(url, "eth_call",
                                               [{"from": FROM, "to": FAKE, "data": "0x" + cd.hex()}, bhex, OV])
                    est = exec_state(out_res, out_err, False)
                    gas_ok = False; gu = l1 = None
                    if est == "ok":
                        gres, gerr = raw_rpc(url, "eth_estimateGas",
                                             [{"from": FROM, "to": FAKE, "value": "0x0", "data": "0x" + cd.hex()}, bhex, OV])
                        if gres and not gerr and bf and bf > 0:
                            gu = int(gres, 16)
                            ser = serialize_dummy_1559(CHAIN_ID, gu, FAKE, cd, max(bf, 1) * 2, 10 ** 6)
                            lres, lerr = raw_rpc(url, "eth_call",
                                                 [{"to": GASORACLE, "data": "0x" + (SEL_GETL1FEE + abi_encode(["bytes"], [ser])).hex()}, bhex])
                            if lres and not lerr:
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
                        rec["reason_raw"] = ("oracle/ancre indisponible (infra)" if est == "ok" and not anchor_ok
                                             else "gas/getL1Fee indisponible (infra)" if est == "ok"
                                             else (out_err.get("message", "") if isinstance(out_err, dict) else str(out_err))[:140]
                                             if out_err else "exec infra")
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
        "verdict": "LOT_MESURE" if cat[CAT_INFRA] == 0 else "LOT_NON_CONCLUANT_RETRY_REQUIRED",
        "note": ("Bornes superieures hors priorite MEV ; AUCUN verdict economique. CAPACITY = limite "
                 "OPERATIONNELLE (reason brut conserve) ; WINDOW_UNAVAILABLE = absence CONFIRMEE (getCode=0x) ; "
                 "NON_CONCLUANT_INFRA = echec transport/CUPS/oracle/gas apres retries -> lot ENTIER a re-run "
                 "(jamais fusionne). Reverts + indisponibilites CONSERVES dans raw+manifest. Lot du plan gele, "
                 "ordre inchange. Les 29 lots restent obligatoires."),
    })
    with open(os.path.join(run_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(json.dumps({"verdict": manifest["verdict"], "lot": args.lot, "cycles": len(cycles),
                      "categories": cat, "run_dir": os.path.relpath(run_dir, HERE).replace("\\", "/")},
                     ensure_ascii=False, indent=2))
    return 0


# --- helpers reseau (isoles ; non purs) ---
def _slot_ok(url, ov):
    sel = Web3.keccak(text="balanceOf(address)")[:4]
    r, e = raw_rpc(url, "eth_call", [{"to": USDC, "data": "0x" + (sel + abi_encode(["address"], [FAKE])).hex()}, hex(B1), ov])
    return bool(r) and not e and int(r, 16) == HUGE


def _code_override_ok(url):
    r, e = raw_rpc(url, "eth_call", [{"from": FROM, "to": FAKE, "data": "0x"}, hex(B1),
                                     {FAKE: {"code": "0x602a60005260206000f3", "balance": hex(10 ** 24)}}])
    return bool(r) and not e and int(r, 16) == 42


def _pool_state(url, pool, b, cache):
    """Tri-etat de presence (fidelite) : 'present'/'absent'/'infra'. getCode echoue -> 'infra', jamais faux absent."""
    key = (pool, b)
    if key not in cache:
        c, e = raw_rpc(url, "eth_getCode", [pool, hex(b)])
        cache[key] = pool_state(c, e, False)
    return cache[key]


def _block_bf_anchor(url, bhex):
    """(base_fee, eth_usd) au bloc bhex : base_fee + timestamp via get_block ; eth_usd via Chainlink + garde-fous."""
    blk, _ = raw_rpc(url, "eth_getBlockByNumber", [bhex, False])
    try:
        bf = int(blk["baseFeePerGas"], 16) if blk and blk.get("baseFeePerGas") else None
        ts = int(blk["timestamp"], 16) if blk and blk.get("timestamp") else None
    except Exception:
        bf = ts = None
    answer = updated_at = None
    r, e = raw_rpc(url, "eth_call", [{"to": CHAINLINK_ETH_USD, "data": "0x" + SEL_LATESTROUNDDATA.hex()}, bhex])
    if r and not e and len(r) >= 2 + 64 * 5:
        b = bytes.fromhex(r[2:])
        answer = int.from_bytes(b[32:64], "big", signed=True)     # int256 answer
        updated_at = int.from_bytes(b[96:128], "big")             # uint updatedAt
    return bf, anchor_eth_usd(answer, updated_at, ts)


def _abort(run_dir, manifest, reason):
    manifest["verdict"] = "NON_CONCLUANT"; manifest["abstention_reason"] = reason
    with open(os.path.join(run_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(json.dumps({"verdict": "NON_CONCLUANT", "reason": reason}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
