#!/usr/bin/env python
"""Runner D2B-2-lots — HORS RÉSEAU : gel des lots deterministes des 145 routes vivantes.

Depuis le brut D2B-1 (LIVENESS_OK, integrite verifiee par sha256), extrait les routes VIVANTES dans l'ordre
route_hash GELE (sous-ensemble vivant de D2B-0), et fige le decoupage en lots deterministes (lot_size=5 ->
29 lots) AVANT toute mesure. Ref : docs/mechanisms/defi_d2b2_lots_preregistration.md.

AUCUN RESEAU. La mesure D2B-2 (reseau) est un runner separe, sur validation humaine. Tous les lots devront
etre executes, dans l'ordre, sans arret apres un resultat ; reverts = capacite ; bornes superieures hors
priorite MEV.
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
LOT_SIZE = 5
SIZES_USD = [250, 1000, 2500, 5000, 10000]
N_BLOCKS = 300
DIRECTIONS = 2


# ----------------------------------------------------------------------------- fonctions PURES (testables)
def partition_lots(routes: list, lot_size: int) -> list:
    """Decoupe la liste ORDONNEE en lots de lot_size (le dernier peut etre plus court)."""
    return [routes[i:i + lot_size] for i in range(0, len(routes), lot_size)]


def lot_digest(lot: list) -> str:
    return hashlib.sha256("".join(r["route_hash"] for r in lot).encode()).hexdigest()


def plan_digest(routes: list) -> str:
    return hashlib.sha256("".join(r["route_hash"] for r in routes).encode()).hexdigest()


def vivantes_in_order(results: list) -> list:
    """Routes vivantes (classification == 'vivante'), dans l'ordre du brut (= ordre gele D2B-0)."""
    keep = ("route_hash", "token0", "token1", "other", "uni_pool", "uni_fee", "slip_pool", "slip_tickSpacing")
    return [{k: r[k] for k in keep} for r in results if r.get("classification") == "vivante"]


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


def main() -> int:
    prov = provenance()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = os.path.join(HERE, "runs", f"{stamp}_d2b2-lots-frozen")
    os.makedirs(run_dir, exist_ok=True)

    d2b1_cands = sorted(glob.glob(os.path.join(HERE, "runs", "*_d2b1-liveness-usdc-cohort", "manifest.json")))
    if not d2b1_cands:
        print(json.dumps({"verdict": "NON_CONCLUANT", "reason": "manifeste D2B-1 introuvable"}))
        return 0
    d2b1 = json.load(open(d2b1_cands[-1], encoding="utf-8"))
    rcpt = d2b1["receipts"][0]
    raw_path = os.path.join(HERE, rcpt["raw_path"])
    if not os.path.exists(raw_path):
        print(json.dumps({"verdict": "NON_CONCLUANT", "reason": f"brut D2B-1 absent: {rcpt['raw_path']}"}))
        return 0
    raw_bytes = open(raw_path, "rb").read()
    if hashlib.sha256(raw_bytes).hexdigest() != rcpt["sha256"]:
        print(json.dumps({"verdict": "NON_CONCLUANT", "reason": "integrite brut D2B-1 KO (sha256 mismatch)"}))
        return 0
    raw = json.loads(raw_bytes.decode("utf-8"))

    vivantes = vivantes_in_order(raw["results"])
    lots = partition_lots(vivantes, LOT_SIZE)
    lot_entries = [{"lot_index": i, "n_routes": len(lot), "lot_digest": lot_digest(lot), "routes": lot}
                   for i, lot in enumerate(lots)]
    pdigest = plan_digest(vivantes)

    manifest = {
        "phase": "D2B-2-lots", "mode": "HORS_RESEAU", "track": "defi-samechain-mev-boundary", "chain": "base",
        "objective": "gel des lots deterministes des 145 routes vivantes AVANT mesure",
        "preregistration_ref": "docs/mechanisms/defi_d2b2_lots_preregistration.md",
        "d2b1_source": {"manifest": os.path.relpath(d2b1_cands[-1], HERE).replace("\\", "/"),
                        "B1": d2b1.get("block"), "raw_sha256": rcpt["sha256"],
                        "frozen_order_digest_d2b0": d2b1.get("d2b1_source", {}).get("frozen_order_digest")
                        or d2b1.get("d2b0_source", {}).get("frozen_order_digest")},
        "params_figes": {"sizes_usd": SIZES_USD, "n_blocks": N_BLOCKS, "directions": DIRECTIONS,
                         "lot_size": LOT_SIZE, "executor_source_sha": "53417e97..."},
        "vivantes_count": len(vivantes), "n_lots": len(lots),
        "cycles_total": len(vivantes) * N_BLOCKS * len(SIZES_USD) * DIRECTIONS,
        "plan_digest_sha256": pdigest, "lots": lot_entries,
        "created_utc": now_utc(), **prov,
        "verdict": "LOTS_GELES",
        "note": ("Lots deterministes geles AVANT mesure. D2B-2 (reseau) = runner separe, sur validation : "
                 "tous les lots, dans l'ordre, sans arret apres un resultat ; reverts = capacite ; bornes "
                 "superieures hors priorite MEV ; aucun verdict economique. AUCUN reseau ici."),
    }
    with open(os.path.join(run_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    print(json.dumps({"verdict": "LOTS_GELES", "vivantes": len(vivantes), "lot_size": LOT_SIZE,
                      "n_lots": len(lots), "cycles_total": manifest["cycles_total"],
                      "plan_digest": pdigest[:16] + "...", "B1": d2b1.get("block"),
                      "run_dir": os.path.relpath(run_dir, HERE).replace("\\", "/")}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
