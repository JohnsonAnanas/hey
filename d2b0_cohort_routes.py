#!/usr/bin/env python
"""Runner D2B-0 — HORS RÉSEAU : cohorte USDC + énumération des routes + ordre déterministe gelé.

Depuis le registre D2A (REGISTRE_STRUCTUREL_COMPLET), sélectionne la cohorte initiale = paires candidates
contenant DIRECTEMENT l'USDC canonique Base, énumère TOUTES les routes `Uni-pool × Slip-pool`, et FIGE leur
ordre déterministe par `route_hash` AVANT toute mesure (pas de choix opportuniste de token après avoir vu
les écarts). Réf : docs/mechanisms/defi_d2b_crossprotocol_test_preregistration.md.

AUCUN RÉSEAU. Pure lecture du registre D2A + calcul. D2B-1/D2B-2 (réseau) = runner séparé, sur validation.
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone

from web3 import Web3

HERE = os.path.dirname(os.path.abspath(__file__))
USDC = Web3.to_checksum_address("0x833589fcd6edb6e08f4c7c32d4f71b54bda02913")  # USDC canonique Base


# ----------------------------------------------------------------------------- fonctions PURES (testables)
def usdc_cohort(registry: list, usdc: str) -> list:
    """Cohorte = entrees du registre dont token0 OU token1 == USDC canonique (contrat, jamais ticker)."""
    u = Web3.to_checksum_address(usdc)
    out = []
    for e in registry:
        if Web3.to_checksum_address(e["token0"]) == u or Web3.to_checksum_address(e["token1"]) == u:
            out.append(e)
    return out


def enumerate_routes(entry: dict) -> list:
    """Toutes les routes Uni-pool x Slip-pool d'une paire candidate."""
    routes = []
    for up in entry["uni_pools"]:
        for sp in entry["slip_pools"]:
            routes.append({
                "token0": Web3.to_checksum_address(entry["token0"]),
                "token1": Web3.to_checksum_address(entry["token1"]),
                "uni_pool": Web3.to_checksum_address(up["pool"]), "uni_fee": up["fee"],
                "uni_tickSpacing": up["tickSpacing"],
                "slip_pool": Web3.to_checksum_address(sp["pool"]), "slip_tickSpacing": sp["tickSpacing"],
            })
    return routes


def route_descriptor(r: dict) -> str:
    return (f"{r['token0']}|{r['token1']}|uni:{r['uni_pool']}:{r['uni_fee']}"
            f"|slip:{r['slip_pool']}:{r['slip_tickSpacing']}")


def route_hash(r: dict) -> str:
    return hashlib.sha256(route_descriptor(r).encode("utf-8")).hexdigest()


def frozen_order(routes: list) -> list:
    """Ordre déterministe gelé = route_hash croissant."""
    for r in routes:
        r["route_hash"] = route_hash(r)
    return sorted(routes, key=lambda x: x["route_hash"])


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


def find_d2a_manifest() -> str | None:
    cands = sorted(glob.glob(os.path.join(HERE, "runs", "*_d2a-crossprotocol-registry-base", "manifest.json")))
    return cands[-1] if cands else None


def main() -> int:
    prov = provenance()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = os.path.join(HERE, "runs", f"{stamp}_d2b0-cohort-routes-usdc")
    os.makedirs(run_dir, exist_ok=True)

    d2a_path = find_d2a_manifest()
    if d2a_path is None:
        print(json.dumps({"verdict": "NON_CONCLUANT", "reason": "manifeste D2A introuvable"}))
        return 0
    d2a = json.load(open(d2a_path, encoding="utf-8"))
    registry = d2a.get("candidate_registry", [])

    cohort = usdc_cohort(registry, USDC)
    routes = []
    for e in cohort:
        routes.extend(enumerate_routes(e))
    ordered = frozen_order(routes)
    order_digest = hashlib.sha256("".join(r["route_hash"] for r in ordered).encode()).hexdigest()

    manifest = {
        "phase": "D2B-0", "mode": "HORS_RESEAU", "track": "defi-samechain-mev-boundary", "chain": "base",
        "objective": "cohorte USDC + enumeration routes + ordre deterministe GELE (avant toute mesure)",
        "preregistration_ref": "docs/mechanisms/defi_d2b_crossprotocol_test_preregistration.md",
        "d2a_source": {"manifest": os.path.relpath(d2a_path, HERE).replace("\\", "/"),
                       "snapshot_block_B": d2a.get("snapshot_block_B"),
                       "registry_count": d2a.get("registry_count")},
        "usdc_anchor": USDC,
        "cohort_pairs_count": len(cohort),
        "routes_count": len(ordered),
        "frozen_order_digest_sha256": order_digest,
        "route_hash_formula": "sha256('{token0}|{token1}|uni:{uni_pool}:{uni_fee}|slip:{slip_pool}:{slip_tickSpacing}')",
        "frozen_routes": ordered,
        "created_utc": now_utc(), **prov,
        "verdict": "ORDRE_GELE",
        "note": ("Ordre deterministe gele AVANT mesure. D2B-1/D2B-2 (reseau) sur validation : liveness $250 "
                 "(non-revert deux sens) puis 300 blocs aux tailles figees dans CET ordre, tous les lots, "
                 "reverts=capacite, bornes superieures hors priorite MEV. AUCUN reseau ici. Paires sans USDC "
                 "hors cohorte (regle d'ancrage separee a preenregistrer)."),
    }
    with open(os.path.join(run_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    print(json.dumps({"verdict": "ORDRE_GELE", "cohort_pairs": len(cohort), "routes": len(ordered),
                      "frozen_order_digest": order_digest[:16] + "...",
                      "d2a_snapshot_B": d2a.get("snapshot_block_B"),
                      "run_dir": os.path.relpath(run_dir, HERE).replace("\\", "/")}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
