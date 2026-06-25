#!/usr/bin/env python
"""Probe technique D2B-2 : trouver le DEBIT SOUTENABLE MAX propre (0 CUPS / 0 empty / 0 infra) AU-DESSUS de
380/8, pour figer un throttle de serie AVEC MARGE. Namespace SEPARE (runs/*_d2b2-probe-throttle) ; AUCUN lot
prod, AUCUN resultat economique interprete.

Regles (validees) : points croissants ; ARRET des le premier point SALE (marque 'benchmark_infra', pas de
compensation silencieuse) ; selection serie = plus haut point teste propre dont cups <= MARGE * (plus haut
point propre), sinon fallback 380/8. Stress realiste : 13 blocs PRESENTS finissant a B1 (charge exec maximale,
sur ~1-2 min/point), plus representatif qu'un burst de 40 cycles. Lecture seule ; aucun capital.
"""
from __future__ import annotations

import glob
import json
import os
import time
from datetime import datetime, timezone

import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from archive_rpc import endpoints  # noqa: E402
from cups_transport import CupsLimiter, CU_COST  # noqa: E402
from d2b2_measure import B1, window_blocks, SIZES_USD, CAT_INFRA, CAT_WINDOW, CAT_OK, CAT_CAPACITY  # noqa: E402
from d2b1_liveness import ORIENTATIONS  # noqa: E402
from d2b2v2_measure import measure_cycles, overrides, provenance  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
PROBE_POINTS = [(380, 8), (450, 9), (520, 10), (600, 12), (700, 13), (820, 15), (950, 17)]
PROBE_NBLOCKS = 6                # 6 derniers blocs (B1-5..B1) : pools presents -> charge exec realiste (~1 min/point)
PROBE_MAX_RETRY = 2             # fail-fast : detecter vite le plafond (un point saturant n'epuise pas 8s de backoff x6)
BENCH_SIZES = [250, 10000]
MARGIN = 0.82                    # throttle serie <= 82% du plus haut point propre
CU_PER_CYCLE = CU_COST["eth_call"] * 2 + CU_COST["eth_estimateGas"] + 15


def main() -> int:
    prov = provenance()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = os.path.join(HERE, "runs", f"{stamp}_d2b2-probe-throttle")
    os.makedirs(run_dir, exist_ok=True)
    plan = json.load(open(sorted(glob.glob(os.path.join(HERE, "runs", "*_d2b2-lots-frozen", "manifest.json")))[-1], encoding="utf-8"))
    routes = plan["lots"][0]["routes"]
    blocks = list(range(B1 - (PROBE_NBLOCKS - 1), B1 + 1))     # se termine a B1 (vivant)
    n_cycles = len(routes) * len(blocks) * len(BENCH_SIZES) * len(ORIENTATIONS)
    url = endpoints("base")[0]
    bytecode = json.load(open(os.path.join(HERE, "contracts", "CrossProtocolExecutor.json"), encoding="utf-8"))["deployed_bytecode"]
    OV = overrides(bytecode)
    per_lot = 5 * 300 * len(SIZES_USD) * len(ORIENTATIONS)
    total = 145 * 300 * len(SIZES_USD) * len(ORIENTATIONS)

    rows, ceiling = [], False
    for (cups, k) in PROBE_POINTS:
        arch = []
        t0 = time.time()
        recs = measure_cycles(url, OV, routes, blocks, BENCH_SIZES, ORIENTATIONS, CupsLimiter(cups), k, arch,
                              max_retry=PROBE_MAX_RETRY)
        dt = time.time() - t0
        cc = {}
        for r in recs:
            cc[r["category"]] = cc.get(r["category"], 0) + 1
        infra = cc.get(CAT_INFRA, 0)
        win_b1 = sum(1 for r in recs if r["block"] == B1 and r["category"] == CAT_WINDOW)
        cyc_s = n_cycles / dt if dt > 0 else 0.0
        clean = (len(arch) == 0 and infra == 0 and win_b1 == 0)
        rows.append({"cups": cups, "concurrency": k, "cyc_s": round(cyc_s, 2), "transport_errors": len(arch),
                     "infra": infra, "window_at_B1": win_b1, "clean": clean,
                     "status": "propre" if clean else "benchmark_infra",
                     "cups_observee_estimee": round(cyc_s * CU_PER_CYCLE),
                     "eta_per_lot_min": round(per_lot / cyc_s / 60, 1) if cyc_s else None,
                     "eta_total_h": round(total / cyc_s / 3600, 2) if cyc_s else None})
        # ecriture INCREMENTALE (pas de perte sur interruption) + progression
        json.dump({"phase": "D2B-2-probe-throttle", "en_cours": True, "points_partiels": rows,
                   "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), **prov},
                  open(os.path.join(run_dir, "manifest.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print("[point %d/%d] cups=%d k=%d -> %.2f cyc/s | transport_errors=%d infra=%d win@B1=%d | %s | ETA=%sh"
              % (len(rows), len(PROBE_POINTS), cups, k, rows[-1]["cyc_s"], rows[-1]["transport_errors"],
                 rows[-1]["infra"], rows[-1]["window_at_B1"], rows[-1]["status"], rows[-1]["eta_total_h"]), flush=True)
        if not clean:
            ceiling = True
            break                                              # arret des le premier point sale

    cleans = [r for r in rows if r["clean"]]
    highest = max(cleans, key=lambda r: r["cyc_s"]) if cleans else None
    pick = None
    if highest:
        thresh = MARGIN * highest["cups"]
        elig = [r for r in cleans if r["cups"] <= thresh]
        pick = max(elig, key=lambda r: r["cyc_s"]) if elig else None
    if pick is None:
        pick = {"cups": 380, "concurrency": 8, "cyc_s": next((r["cyc_s"] for r in rows if r["cups"] == 380), None),
                "eta_total_h": next((r["eta_total_h"] for r in rows if r["cups"] == 380), None),
                "fallback": "pas de point propre nettement > 380 avec marge"}
    reco = {"cups": pick["cups"], "concurrency": pick["concurrency"], "cyc_s": pick.get("cyc_s"),
            "eta_total_h": pick.get("eta_total_h"), "eta_per_lot_min": pick.get("eta_per_lot_min"),
            "regle": "throttle serie <= %.0f%% du plus haut point propre, sinon 380/8" % (MARGIN * 100),
            "plafond_trouve": ceiling,
            "plus_haut_point_propre": ({"cups": highest["cups"], "concurrency": highest["concurrency"],
                                        "cyc_s": highest["cyc_s"]} if highest else None)}
    manifest = {"phase": "D2B-2-probe-throttle", "objective": "debit soutenable max propre + throttle serie avec "
                "marge ; AUCUN resultat economique, AUCUN lot prod",
                "stress": {"blocks": [blocks[0], blocks[-1]], "n_blocks": PROBE_NBLOCKS, "note": "13 blocs presents finissant a B1",
                           "sizes": BENCH_SIZES, "directions": ORIENTATIONS, "n_cycles_par_point": n_cycles},
                "points": rows, "recommandation_serie": reco,
                "note": "Throttle sale -> 'benchmark_infra', arret immediat, pas de compensation. ETA extrapolee "
                        "du debit mesure. Aucun upper_bound interprete.",
                "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), **prov}
    json.dump(manifest, open(os.path.join(run_dir, "manifest.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(json.dumps({"recommandation_serie": reco,
                      "table": [{"cups": r["cups"], "k": r["concurrency"], "cyc_s": r["cyc_s"],
                                 "transport_errors": r["transport_errors"], "infra": r["infra"],
                                 "window_at_B1": r["window_at_B1"], "status": r["status"],
                                 "eta_total_h": r["eta_total_h"]} for r in rows],
                      "run_dir": os.path.relpath(run_dir, HERE).replace("\\", "/")}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
