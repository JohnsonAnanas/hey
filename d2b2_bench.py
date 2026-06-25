#!/usr/bin/env python
"""Benchmark technique D2B-2 DURCI — AVANT toute serie. AUCUN resultat economique interprete.

Couvre (cf. directives) :
- CHEMIN SUCCES + EQUIVALENCE : measure_cycles concurrency=1 (reference sequentielle) vs K (production) ->
  resultats byte/identiques (le resultat d'un appel ne depend que de method/params/blockTag).
- B1 CONNU VIVANT : au bloc B1, les routes du lot 0 (prouvees vivantes en D2B-1) ne doivent JAMAIS etre
  classees WINDOW_UNAVAILABLE.
- DEBIT SOUTENABLE SANS ERREUR : rampe de (cups, concurrency) -> plus haut debit avec 0 erreur transport ET
  0 NON_CONCLUANT_INFRA -> throttle recommande + ETA reelle (par lot / 29 lots) + CUPS observee (estimee).

Le CHEMIN D'ECHEC (getCode None/0x/empty/CUPS -> INFRA, jamais faux absent/gas=0) est couvert par les tests
OFFLINE test_d2b2_fidelity + test_cups_transport (injection deterministe). Lecture seule ; aucun capital.
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import time
from datetime import datetime, timezone

import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from archive_rpc import endpoints  # noqa: E402
from cups_transport import CupsLimiter, CU_COST  # noqa: E402
from d2b2_measure import B1, window_blocks, SIZES_USD, CAT_OK, CAT_CAPACITY, CAT_WINDOW, CAT_INFRA  # noqa: E402
from d2b1_liveness import ORIENTATIONS  # noqa: E402
from d2b2v2_measure import measure_cycles, overrides, provenance  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
BENCH_SIZES = [250, 10000]                          # min + max de la grille gelee
CANDIDATES = [(150, 4), (220, 5), (300, 6), (380, 8)]   # (cups, concurrency) rampe ; le dernier sonde le plafond
CU_PER_CYCLE = CU_COST["eth_call"] * 2 + CU_COST["eth_estimateGas"] + 15   # ~estimation CU/cycle (R2+R3 + amorti)


def compare(recs_a: list, recs_b: list) -> dict:
    key = lambda r: (r["route_hash"], r["block"], r["size_usd"], r["direction"])
    a = {key(r): r for r in recs_a}
    b = {key(r): r for r in recs_b}
    mism = []
    for k in sorted(set(a) | set(b)):
        ra, rb = a.get(k), b.get(k)
        if ra is None or rb is None or json.dumps(ra, sort_keys=True) != json.dumps(rb, sort_keys=True):
            mism.append({"key": list(k), "v1": ra, "v2": rb})
    return {"n_a": len(a), "n_b": len(b), "identiques": len(a) == len(b) and not mism,
            "n_mismatch": len(mism), "mismatches_sample": mism[:5]}


def _counts(records: list) -> dict:
    c = {}
    for r in records:
        c[r["category"]] = c.get(r["category"], 0) + 1
    return c


def main() -> int:
    prov = provenance()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = os.path.join(HERE, "runs", f"{stamp}_d2b2-bench-hardened")
    os.makedirs(run_dir, exist_ok=True)
    plan = json.load(open(sorted(glob.glob(os.path.join(HERE, "runs", "*_d2b2-lots-frozen", "manifest.json")))[-1], encoding="utf-8"))
    routes = plan["lots"][0]["routes"]
    b_start, b_end, nb = window_blocks(B1)
    blocks = [b_start, B1]                          # B1 = bloc connu VIVANT (D2B-1)
    n_cycles = len(routes) * len(blocks) * len(BENCH_SIZES) * len(ORIENTATIONS)
    url = endpoints("base")[0]
    bytecode = json.load(open(os.path.join(HERE, "contracts", "CrossProtocolExecutor.json"), encoding="utf-8"))["deployed_bytecode"]
    OV = overrides(bytecode)

    # 1) RAMPE : plus haut debit PROPRE (0 erreur transport, 0 INFRA, 0 WINDOW a B1)
    ramp = []
    for (cups, k) in CANDIDATES:
        arch = []
        t0 = time.time()
        recs = measure_cycles(url, OV, routes, blocks, BENCH_SIZES, ORIENTATIONS, CupsLimiter(cups), k, arch)
        dt = time.time() - t0
        cc = _counts(recs)
        b1_win = sum(1 for r in recs if r["block"] == B1 and r["category"] == CAT_WINDOW)
        clean = (len(arch) == 0 and cc.get(CAT_INFRA, 0) == 0 and b1_win == 0)
        ramp.append({"cups": cups, "concurrency": k, "t_s": round(dt, 2),
                     "cyc_s": round(n_cycles / dt, 2) if dt > 0 else None,
                     "transport_errors": len(arch), "infra": cc.get(CAT_INFRA, 0),
                     "window_at_B1": b1_win, "categories": cc, "clean": clean})
    cleans = [x for x in ramp if x["clean"]]
    best = max(cleans, key=lambda x: x["cyc_s"]) if cleans else None

    # 2) EQUIVALENCE c=1 (reference) vs c=K (production) au throttle recommande + B1 jamais WINDOW
    equiv = b1_check = eta = None
    if best:
        a1 = []; recs1 = measure_cycles(url, OV, routes, blocks, BENCH_SIZES, ORIENTATIONS, CupsLimiter(best["cups"]), 1, a1)
        aK = []; recsK = measure_cycles(url, OV, routes, blocks, BENCH_SIZES, ORIENTATIONS, CupsLimiter(best["cups"]), best["concurrency"], aK)
        equiv = compare(recs1, recsK)
        b1_win = sum(1 for r in recsK if r["block"] == B1 and r["category"] == CAT_WINDOW)
        b1_alive = sum(1 for r in recsK if r["block"] == B1 and r["category"] in (CAT_OK, CAT_CAPACITY))
        b1_check = {"window_unavailable_at_B1": b1_win, "ok_ou_capacity_at_B1": b1_alive,
                    "transport_errors": len(a1) + len(aK), "pass": b1_win == 0 and b1_alive > 0}
        cyc_s = best["cyc_s"]
        per_lot = 5 * 300 * len(SIZES_USD) * len(ORIENTATIONS)
        total = 145 * 300 * len(SIZES_USD) * len(ORIENTATIONS)
        eta = {"cyc_s_soutenable": cyc_s, "cups_observee_estimee": round(cyc_s * CU_PER_CYCLE),
               "per_lot_cycles": per_lot, "total_cycles": total,
               "eta_per_lot_min": round(per_lot / cyc_s / 60, 1) if cyc_s else None,
               "eta_total_h": round(total / cyc_s / 3600, 2) if cyc_s else None}

    valide = bool(best and equiv and equiv["identiques"] and b1_check and b1_check["pass"])
    verdict = "EQUIVALENT_ET_PROPRE" if valide else "NON_VALIDE"
    manifest = {"phase": "D2B-2-bench-durci", "objective": "succes+equivalence c1<->cK, B1 jamais WINDOW, debit "
                "soutenable propre + ETA reelle ; AUCUN resultat economique",
                "bench_set": {"lot": 0, "routes": len(routes), "blocks": blocks, "blocks_note": "b_start + B1(vivant)",
                              "sizes": BENCH_SIZES, "directions": ORIENTATIONS, "n_cycles": n_cycles},
                "rampe_throttle": ramp, "throttle_recommande": ({"cups": best["cups"], "concurrency": best["concurrency"]} if best else None),
                "equivalence_c1_cK": equiv, "b1_vivant_check": b1_check, "eta_serie": eta,
                "failure_path_couvert_par": ["tests/test_d2b2_fidelity.py", "tests/test_cups_transport.py"],
                "note": "Benchmark technique : seules l'EGALITE c1<->cK, l'absence de WINDOW a B1 et la proprete "
                        "(0 erreur/0 infra) comptent. Aucun upper_bound interprete.",
                "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), **prov, "verdict": verdict}
    json.dump(manifest, open(os.path.join(run_dir, "manifest.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(json.dumps({"verdict": verdict, "throttle_recommande": manifest["throttle_recommande"],
                      "equivalence_identiques": (equiv or {}).get("identiques"), "n_mismatch": (equiv or {}).get("n_mismatch"),
                      "b1_vivant": b1_check, "eta": eta,
                      "rampe": [{"cups": x["cups"], "k": x["concurrency"], "cyc_s": x["cyc_s"], "clean": x["clean"],
                                 "transport_errors": x["transport_errors"], "infra": x["infra"]} for x in ramp],
                      "run_dir": os.path.relpath(run_dir, HERE).replace("\\", "/")}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
