#!/usr/bin/env python
"""Benchmark technique D2B-2 v1 (sequentiel) vs v2 (batch) — equivalence byte/resultat + debit + ETA.

Sur un PETIT ensemble PREDEFINI de cycles (pas un run economique) : compare resultat-a-resultat la reference
sequentielle v1-exacte (measure_seq_ref) et la mesure batchee v2 (measure_batched) -> doivent etre
IDENTIQUES. Mesure le debit (cycles/s), les erreurs de transport, et l'ETA reelle de la serie complete.
AUCUN resultat economique n'est analyse (les upper_bounds ne sont pas interpretes ; seule l'EGALITE compte).
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
from d2b2_measure import B1, window_blocks, SIZES_USD  # noqa: E402
from d2b1_liveness import ORIENTATIONS  # noqa: E402
from d2b2v2_measure import measure_seq_ref, measure_batched, overrides, provenance  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
# Ensemble PREDEFINI (avant donnees) : lot 0, 2 blocs (bornes de fenetre), 2 tailles (min+max), 2 directions.
BENCH_BLOCKS_FROM_WINDOW = ("b_start", "b_end")
BENCH_SIZES = [250, 10000]


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


def main() -> int:
    prov = provenance()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = os.path.join(HERE, "runs", f"{stamp}_d2b2-bench-v1-vs-v2")
    os.makedirs(run_dir, exist_ok=True)
    plan = json.load(open(sorted(glob.glob(os.path.join(HERE, "runs", "*_d2b2-lots-frozen", "manifest.json")))[-1], encoding="utf-8"))
    routes = plan["lots"][0]["routes"]
    b_start, b_end, nb = window_blocks(B1)
    blocks = [b_start, b_end]
    n_cycles = len(routes) * len(blocks) * len(BENCH_SIZES) * len(ORIENTATIONS)

    url = endpoints("base")[0]
    bytecode = json.load(open(os.path.join(HERE, "contracts", "CrossProtocolExecutor.json"), encoding="utf-8"))["deployed_bytecode"]
    OV = overrides(bytecode)

    t0 = time.time()
    recs_v1 = measure_seq_ref(url, OV, routes, blocks, BENCH_SIZES, ORIENTATIONS)
    t_v1 = time.time() - t0

    arch = []
    t0 = time.time()
    recs_v2 = measure_batched(url, OV, routes, blocks, BENCH_SIZES, ORIENTATIONS, arch)
    t_v2 = time.time() - t0

    cmp = compare(recs_v1, recs_v2)
    deb_v1 = n_cycles / t_v1 if t_v1 > 0 else None
    deb_v2 = n_cycles / t_v2 if t_v2 > 0 else None
    speedup = (t_v1 / t_v2) if t_v2 > 0 else None
    total_cycles = 145 * 300 * len(SIZES_USD) * len(ORIENTATIONS)   # serie complete 29 lots
    per_lot_cycles = 5 * 300 * len(SIZES_USD) * len(ORIENTATIONS)
    eta_v2_total_s = (total_cycles / deb_v2) if deb_v2 else None
    eta_v2_lot_s = (per_lot_cycles / deb_v2) if deb_v2 else None

    manifest = {
        "phase": "D2B-2-bench", "objective": "equivalence byte/resultat v1<->v2 + debit + ETA (AUCUN resultat economique)",
        "bench_set": {"lot": 0, "routes": len(routes), "blocks": blocks, "sizes": BENCH_SIZES,
                      "directions": ORIENTATIONS, "n_cycles": n_cycles},
        "equivalence": cmp,
        "perf": {"t_v1_s": round(t_v1, 3), "t_v2_s": round(t_v2, 3),
                 "debit_v1_cyc_s": round(deb_v1, 2) if deb_v1 else None,
                 "debit_v2_cyc_s": round(deb_v2, 2) if deb_v2 else None,
                 "speedup": round(speedup, 2) if speedup else None,
                 "transport_errors_v2": len(arch)},
        "eta_serie_v2": {"total_cycles_29_lots": total_cycles, "per_lot_cycles": per_lot_cycles,
                         "eta_total_h": round(eta_v2_total_s / 3600, 2) if eta_v2_total_s else None,
                         "eta_per_lot_min": round(eta_v2_lot_s / 60, 1) if eta_v2_lot_s else None},
        "note": "Benchmark technique : seule l'EGALITE byte/resultat et la perf comptent. Aucun upper_bound interprete.",
        "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), **prov,
        "transport_errors_v2_detail": arch[:10],
        "verdict": "EQUIVALENT" if cmp["identiques"] else "DIVERGENT",
    }
    json.dump(manifest, open(os.path.join(run_dir, "manifest.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(json.dumps({"verdict": manifest["verdict"], "n_cycles_bench": n_cycles, "identiques": cmp["identiques"],
                      "n_mismatch": cmp["n_mismatch"], "t_v1_s": round(t_v1, 2), "t_v2_s": round(t_v2, 2),
                      "speedup": manifest["perf"]["speedup"], "debit_v2_cyc_s": manifest["perf"]["debit_v2_cyc_s"],
                      "transport_errors_v2": len(arch),
                      "ETA_total_h": manifest["eta_serie_v2"]["eta_total_h"],
                      "ETA_per_lot_min": manifest["eta_serie_v2"]["eta_per_lot_min"],
                      "run_dir": os.path.relpath(run_dir, HERE).replace("\\", "/")}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
