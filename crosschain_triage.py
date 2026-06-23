#!/usr/bin/env python
"""Phase 1 — TRIAGE anti-mirage cross-chain (données existantes, ZÉRO réseau).

Avant toute excitation sur un gros basis cross-chain, on tue les MIRAGES de pool fin/stale (leçon du
$20M et des pools WETH/USDC stale, cf docs/data_integrity.md). Pour chaque token à identité PROUVÉE
(même adresse sur ≥2 chaînes, garde sim.identity.crosschain_identity), on vérifie PAR CÔTÉ — jamais la
médiane — : liquidité des deux côtés ET volume24h > 0 des deux côtés (un côté non-tradé = prix gelé =
faux gap). Sortie : shortlist de tokens à VRAIE profondeur des deux côtés (→ Phase 2 profondeur
exécutable) + watchlist des candidats à IDENTITÉ NON PROUVÉE (adresses différentes, ex. VELVET) qui
exigent d'abord le registre de bridge officiel.

Lecture seule sur data/collected/crosschain_obs.csv. Borne : c'est un crible grossier (liq/vol agrégés
GeckoTerminal), pas un verdict — il écarte les mirages évidents avant le test on-chain coûteux.

Usage : python crosschain_triage.py --min-liq 100000 --min-vol 1000 --min-gap-bps 30
"""
from __future__ import annotations

import argparse
import csv
import os
import statistics as st
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sim.identity import crosschain_identity
from manifest import write_manifest

HERE = os.path.dirname(os.path.abspath(__file__))
OBS = os.path.join(HERE, "data", "collected", "crosschain_obs.csv")


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="Triage anti-mirage cross-chain (lecture seule).")
    ap.add_argument("--min-liq", type=float, default=100_000.0, help="liquidité USD min PAR CÔTÉ")
    ap.add_argument("--min-vol", type=float, default=1_000.0, help="vol24h USD min PAR CÔTÉ (anti-stale)")
    ap.add_argument("--min-gap-bps", type=float, default=30.0, help="basis min pour valoir la peine")
    args = ap.parse_args()

    if not os.path.exists(OBS):
        print(f"Pas de {OBS}", file=sys.stderr); return 1
    # agg[token][chain] = {"price":[...], "liq":[...], "vol":[...], "addr":set}
    agg = defaultdict(lambda: defaultdict(lambda: {"price": [], "liq": [], "vol": [], "addr": set()}))
    n = 0
    with open(OBS, encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f):
            try:
                p, l, v = float(r["price_usd"]), float(r["liq_usd"]), float(r["vol24h_usd"])
            except (TypeError, ValueError):
                continue
            a = (r.get("address") or "").lower()
            if p > 0 and a:
                c = agg[r["token"]][r["chain"]]
                c["price"].append(p); c["liq"].append(l); c["vol"].append(v); c["addr"].add(a)
                n += 1

    rows = []
    for token, chains in agg.items():
        if len(chains) < 2:
            continue
        per = {}
        for c, d in chains.items():
            # adresse majoritaire de ce (token,chain) ; prix/liq/vol médians sur la fenêtre
            addr = sorted(d["addr"])[0] if len(d["addr"]) == 1 else sorted(d["addr"])[0]
            per[c] = (st.median(d["price"]), st.median(d["liq"]), st.median(d["vol"]), addr)
        lo = min(per, key=lambda c: per[c][0]); hi = max(per, key=lambda c: per[c][0])
        lo_p = per[lo][0]
        if lo_p <= 0:
            continue
        gap = (per[hi][0] - lo_p) / lo_p * 1e4
        verdict_id, _ = crosschain_identity(per[lo][3], per[hi][3], lo, hi)   # garde d'identité (par adresse)
        min_liq = min(per[c][1] for c in per)
        min_vol = min(per[c][2] for c in per)
        if verdict_id != "VERIFIED":
            status = "IDENTITE_NON_PROUVEE"                      # candidat registre de bridge (ex. VELVET)
        elif min_vol < args.min_vol:
            status = "MIRAGE_stale"                              # un côté ~non tradé -> prix gelé -> faux gap
        elif min_liq < args.min_liq:
            status = "MIRAGE_thin"                               # un côté trop fin -> impact tuera la taille
        elif gap < args.min_gap_bps:
            status = "basis_faible"
        else:
            status = "PROFOND"                                   # vraie profondeur 2 côtés + basis -> shortlist
        rows.append((gap, token, lo, hi, per, verdict_id, min_liq, min_vol, status))
    rows.sort(reverse=True)

    shortlist = [r for r in rows if r[8] == "PROFOND"]
    registry = [r for r in rows if r[8] == "IDENTITE_NON_PROUVEE" and r[0] >= args.min_gap_bps]
    mirages = [r for r in rows if r[8] in ("MIRAGE_stale", "MIRAGE_thin")]

    print("=" * 84)
    print(f"TRIAGE ANTI-MIRAGE — {n} obs | {len(agg)} tokens | seuils liq ${args.min_liq:,.0f} / "
          f"vol ${args.min_vol:,.0f} / gap {args.min_gap_bps:.0f}bps (par côté)")
    print("=" * 84)
    print("\nIDENTITÉ PROUVÉE (même adresse) — triage par côté :")
    print(f"  {'token':<10}{'gap':>8}  {'identité':<9}{'min_liq':>12}{'min_vol24h':>13}  côtés        verdict")
    for gap, token, lo, hi, per, vid, mliq, mvol, status in [r for r in rows if r[5] == "VERIFIED"][:20]:
        print(f"  {token:<10}{gap:>7.0f}b  {vid:<9}{mliq:>12,.0f}{mvol:>13,.0f}  {lo}->{hi:<8} {status}")

    print(f"\n>>> SHORTLIST (PROFOND, → Phase 2 profondeur exécutable) : {len(shortlist)}")
    for gap, token, lo, hi, per, vid, mliq, mvol, status in shortlist:
        sides = " ".join(f"{c}:${per[c][0]:.4g}/liq${per[c][1]:,.0f}/vol${per[c][2]:,.0f}" for c in per)
        print(f"    {token:<10} gap {gap:.0f}bps | {sides}")
    if not shortlist:
        print("    (aucun) — sur la fenêtre actuelle, aucun token identité-prouvée n'a une vraie profondeur"
              " des 2 côtés ET un basis ≥ seuil. Mirages écartés ci-dessous.")

    print(f"\nMIRAGES écartés (un côté fin/stale) : {len(mirages)}")
    for gap, token, lo, hi, per, vid, mliq, mvol, status in mirages[:10]:
        print(f"    {token:<10} gap {gap:.0f}bps {status} (min_liq ${mliq:,.0f}, min_vol ${mvol:,.0f})")

    print(f"\nWATCHLIST registre (identité NON prouvée, adresses différentes, gros basis) : {len(registry)}")
    for gap, token, lo, hi, per, vid, mliq, mvol, status in registry[:10]:
        print(f"    {token:<10} gap {gap:.0f}bps {lo}({per[lo][3][:10]}) vs {hi}({per[hi][3][:10]})"
              f" -> exige registre de bridge officiel avant test")

    verdict = "VALIDE" if shortlist else ("NON_CONCLUANT" if registry else "REJETE")
    extra = {
        "shortlist_profond": [{"token": t, "gap_bps": round(g, 1), "chaines": list(per),
                               "min_liq_usd": round(mliq), "min_vol24h_usd": round(mvol)}
                              for g, t, lo, hi, per, vid, mliq, mvol, s in shortlist],
        "mirages_ecartes": [{"token": t, "gap_bps": round(g, 1), "cause": s,
                             "min_liq_usd": round(mliq), "min_vol24h_usd": round(mvol)}
                            for g, t, lo, hi, per, vid, mliq, mvol, s in mirages],
        "watchlist_registre": [{"token": t, "gap_bps": round(g, 1),
                                "lo": {"chain": lo, "addr": per[lo][3]}, "hi": {"chain": hi, "addr": per[hi][3]}}
                               for g, t, lo, hi, per, vid, mliq, mvol, s in registry],
        "seuils": {"min_liq_usd": args.min_liq, "min_vol24h_usd": args.min_vol, "min_gap_bps": args.min_gap_bps},
    }
    run_dir, _ = write_manifest(
        slug="crosschain-triage",
        hypothesis=("Quels tokens à IDENTITÉ PROUVÉE (même adresse) ont une vraie profondeur des DEUX côtés "
                    "(liq + vol24h>0) ET un basis ≥ seuil — donc un candidat NON-mirage pour l'œil-inventaire ?"),
        command=f"python crosschain_triage.py --min-liq {args.min_liq:.0f} --min-vol {args.min_vol:.0f} --min-gap-bps {args.min_gap_bps:.0f}",
        period="fenêtre actuelle du collecteur (crosschain_obs.csv)",
        sources=["data/collected/crosschain_obs.csv (GeckoTerminal, prix/liq/vol agrégés)"],
        inputs=[os.path.relpath(OBS, HERE)],
        universe=f"{len(agg)} tokens vus ; {sum(1 for r in rows if r[5]=='VERIFIED')} à identité prouvée (≥2 chaînes)",
        costs="aucun (crible liq/vol ; pas de quote exécutable — c'est la Phase 2)",
        result=(f"shortlist PROFOND {len(shortlist)} ; mirages écartés {len(mirages)} ; "
                f"watchlist registre {len(registry)}"),
        verdict=verdict,
        notes=("Crible GROSSIER anti-mirage (liq/vol agrégés), pas un verdict éco. Identité PAR ADRESSE. "
               "Un basis qui survit ici doit ENCORE passer la profondeur exécutable on-chain (Phase 2). "
               "Les candidats à identité non prouvée (adresses ≠) exigent un registre de bridge officiel."),
        extra=extra,
    )
    print(f"\nMANIFESTE -> {os.path.relpath(run_dir, HERE)}/  (verdict {verdict})")
    print("Lecture : ce triage ÉCARTE les mirages avant le test on-chain ; il ne valide rien tout seul.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
