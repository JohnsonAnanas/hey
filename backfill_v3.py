#!/usr/bin/env python
"""Backfill de CALIBRATION TECHNIQUE v3 (Base, lecture seule) — quotes v3 EXACTES au bloc passé.

Phase v3 (gel docs/route_evaluator.md). Lit l'état au bloc via archive ; quote v3 via QuoterV2 canonique
(simule le swap, traverse les ticks — jamais un mid). Routes v3↔v3 et v3↔v2, grille de tailles USD,
les deux sens. CONFORME au gel :
- #1 CALIBRATION : ne produit JAMAIS CANDIDAT_FORWARD (même si PnL>0). Conclusion éco = fenêtre 7–14 j ensuite.
- #2 gas = `gas_estime_conservateur` SÉPARÉ (exec / L1-data / marge), jamais 'exact'.
- #3 persistance = champ DESCRIPTIF + classement (REJETE/MEV_RACE/A_OBSERVER_COURT/A_OBSERVER).
- #4 USD par ancre INDÉPENDANTE au même bloc (WETH/USDC v2 hors-route ; stable=1) ; absente -> abstention.
- #5 couverture séparée : routes v3 / quotes ok / quotes revert / routes v2 / exclus / motifs d'abstention.
Borne SUPÉRIEURE : ne voit ni l'intra-bloc ni le MEV. Aucun contrat/clé/mempool/capital.

Usage : python backfill_v3.py --days 2 --cadence-min 60
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from collections import defaultdict
from itertools import combinations
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from web3 import Web3

from sim.chain import SEL_RESERVES, SEL_GETFEE, SEL_SLOT0, uint_from
from eth_abi import encode as abi_encode
from sim.amm_v2_int import leg_out
from sim.quote_v3 import V3Quoter
from sim.route_quoted import evaluate_route_quoted, classify_calibration
from sim.route_eval import persistence_stats
from manifest import write_manifest
from archive_rpc import endpoints, redact
from backfill_intrachain import ArchiveMC, est_block_time, sha256_file
import scan_dex_intrachain as live

HERE = os.path.dirname(os.path.abspath(__file__))
CHAIN_ID = 8453
SIZES_USD = [1_000.0, 5_000.0, 25_000.0, 100_000.0, 250_000.0]   # grille FIGÉE
FIXED_USD = 25_000.0                                             # taille fixe de référence (persistance)
V2_GAS_UNITS = 120_000                                           # forfait exec d'une jambe v2 (conservateur)
WETH, USDC = "WETH", "USDC"


def _fee_bps(p) -> float:
    """Frais de pool en bps (pour le pré-filtre mid). v3 fee_tier=500 -> 5 bps."""
    if p["kind"] == "v3":
        return p["fee_tier"] / 100.0
    if p["kind"] == "solidly":
        return p.get("fee_bps", 30)
    return 30.0


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="Backfill calibration technique v3 (Base, archive, lecture seule).")
    ap.add_argument("--days", type=float, default=2.0)
    ap.add_argument("--cadence-min", type=float, default=60.0)
    ap.add_argument("--start-block", type=int, default=0)
    ap.add_argument("--end-block", type=int, default=0)
    ap.add_argument("--l1-usd", type=float, default=0.02, help="coût L1/data conservateur par tx (USD)")
    ap.add_argument("--gas-margin-frac", type=float, default=0.5, help="marge de sécurité (fraction de exec+L1)")
    ap.add_argument("--persist-frac", type=float, default=0.7)
    ap.add_argument("--persist-streak", type=int, default=3)
    args = ap.parse_args()

    universe, A, dec_cfg = live.load_config()
    urls = endpoints("base")
    w3 = used = None
    for url in urls:
        try:
            cand = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 30}))
            if cand.eth.chain_id == CHAIN_ID:
                w3, used = cand, url; break
        except Exception as e:
            print(f"  [endpoint KO] {redact(url)} : {type(e).__name__}")
    if w3 is None:
        print("Aucun endpoint Base sain.", file=sys.stderr); return 1
    mc = ArchiveMC(w3)
    tip = w3.eth.block_number
    bt = est_block_time(w3, tip)
    step = max(1, round(args.cadence_min * 60 / bt))
    if args.start_block and args.end_block:
        start, end = args.start_block, args.end_block
    else:
        start, end = max(1, tip - int(args.days * 86400 / bt)), tip
    blocks = list(range(start, end + 1, step))
    print(f"RPC {redact(used)} | tip {tip} | bloc ~{bt:.2f}s | plage {start}..{end} pas {step} -> {len(blocks)} blocs")

    # Quoteur v3 VÉRIFIÉ (code + quote saine) au tip ET au 1er bloc historique (archive réelle)
    v3q = V3Quoter(w3, "univ3")
    for blk, lab in ((tip, "tip"), (start, "historique")):
        ok, why = v3q.verify(A[WETH], A[USDC], block=blk)
        if not ok:
            print(f"ABORT : quoteur v3 non vérifié au bloc {lab} ({blk}) : {why}", file=sys.stderr); return 2
    print(f"  quoteur v3 vérifié (code + quote saine) au tip ET au bloc {start} (archive OK).")

    dec, dropped = live.verify_decimals(mc, A, dec_cfg)
    pairs, valid, v3, quarantined = live.resolve(mc, A, dec)
    excluded = len(quarantined) + len(dropped)
    by_pair = defaultdict(list)
    for p in valid + v3:
        by_pair[p["pair"]].append(p)
    routable = {pk: ps for pk, ps in by_pair.items() if len(ps) >= 2}
    print(f"pools v2 {len(valid)} | pools v3 {len(v3)} | exclus {excluded} | paires routables {len(routable)}")

    out_dir = Path(HERE) / "data" / "logs"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"backfill_v3_{stamp}.csv"
    f = open(out_path, "w", newline="", encoding="utf-8")
    w = csv.writer(f)
    w.writerow(["block", "ts_unix", "pair", "venue_a", "venue_b", "direction", "status", "reason",
                "pnl_quote_usd", "gas_exec_usd", "gas_l1_usd", "gas_marge_usd", "gas_total_usd", "pnl_net_usd",
                "opt_size_usd", "max_net_usd", "breakeven_size_usd", "size_90_usd", "capacity_usd",
                "fixed_net_usd", "n_abstain_sizes"])

    requested = len(blocks)
    read = 0
    qstats = {"ok": 0, "revert": 0}
    cov = defaultdict(int)
    obs = {}            # route_key -> {fixed_net[], abstain}
    positives = {}      # route_key -> derniere decision POSITIF
    eval_aero = [p for p in valid if p["kind"] == "solidly"]
    print(f"\nCalibration v3 : {len(blocks)} blocs, grille {SIZES_USD}, fixe ${FIXED_USD:.0f}. "
          f"(borne supérieure ; CANDIDAT_FORWARD interdit ici)\n")

    for N in blocks:
        try:
            reserve_calls = [(Web3.to_checksum_address(p["address"]), SEL_RESERVES) for p in valid]
            fee_calls = [(Web3.to_checksum_address(p["factory"]),
                          SEL_GETFEE + abi_encode(["address", "bool"], [Web3.to_checksum_address(p["address"]), False]))
                         for p in eval_aero]
            slot0_calls = [(Web3.to_checksum_address(p["address"]), SEL_SLOT0) for p in v3]   # mid v3 (pré-filtre)
            res = mc.multicall(reserve_calls + fee_calls + slot0_calls, block=N)
            blk = w3.eth.get_block(N)
        except Exception:
            cov["abstain:bloc_illisible"] += 1; continue
        read += 1
        ts, base_fee = blk["timestamp"], (blk.get("baseFeePerGas") or 0)
        for p, (ok, data) in zip(valid, res[:len(reserve_calls)]):
            p["r0"] = p["r1"] = 0; p["mid"] = None
            if ok and len(data) >= 64:
                p["r0"] = int.from_bytes(data[0:32], "big"); p["r1"] = int.from_bytes(data[32:64], "big")
                if p["r0"]:
                    p["mid"] = (p["r1"] / 10 ** p["dec1"]) / (p["r0"] / 10 ** p["dec0"])   # prix token0 en token1
        off = len(reserve_calls)
        for p, (ok, data) in zip(eval_aero, res[off:off + len(fee_calls)]):
            if ok and data:
                rate = (uint_from(data) or 0) / 10_000.0
                if 0 < rate < 0.05:
                    p["fee_bps"] = round(rate * 10_000)
        for p, (ok, data) in zip(v3, res[off + len(fee_calls):]):           # mid v3 depuis slot0
            p["mid"] = None
            if ok and len(data) >= 32:
                sp = int.from_bytes(data[0:32], "big")
                if sp > 0:
                    p["mid"] = (sp / 2 ** 96) ** 2 * 10 ** (p["dec0"] - p["dec1"])

        # ancre INDÉPENDANTE (#4) : pools v2 WETH/USDC, au bloc N, hors-route
        wu = []
        for p in valid:
            if set(p["pair"]) == {WETH, USDC} and p["r0"] and p["r1"]:
                s0, s1 = p["pair"]; r0h, r1h = p["r0"] / 10 ** p["dec0"], p["r1"] / 10 ** p["dec1"]
                price = r1h / r0h if s0 == WETH else r0h / r1h
                depth = r1h if s1 == USDC else r0h
                wu.append((p["venue"], price, depth))
        if not wu:
            cov["abstain:ancre_usd_absente"] += 1; continue
        eth_usd_gas = max(wu, key=lambda x: x[2])[1]

        def gas_model(units, _bf=base_fee, _eu=eth_usd_gas):
            exec_usd = units * _bf / 1e18 * _eu
            marge = args.gas_margin_frac * (exec_usd + args.l1_usd)
            return exec_usd, args.l1_usd, marge, exec_usd + args.l1_usd + marge

        def quote_leg(pool, x_to_y, amount_in, _N=N):
            t_in, t_out = (pool["t0_addr"], pool["t1_addr"]) if x_to_y else (pool["t1_addr"], pool["t0_addr"])
            if pool["kind"] == "v3":
                r = v3q.quote(t_in, t_out, amount_in, pool["fee_tier"], _N)
                if r is None:
                    qstats["revert"] += 1; return None
                qstats["ok"] += 1
                return r[0], r[1]                       # (amount_out, gas_units du quoteur)
            out = leg_out(pool, amount_in, x_to_y)       # v2 entier
            return (out, V2_GAS_UNITS) if out > 0 else None

        for (s0, s1), ps in routable.items():
            usd0 = 1.0 if s0 in live.STABLES else (None if s0 != WETH else "WETH")
            dec_x = dec[s0]
            live_pools = [p for p in ps if p["kind"] == "v3" or (p["r0"] and p["r1"])]
            for pa, pb in combinations(live_pools, 2):
                is_v3 = "v3" in (pa["kind"], pb["kind"])
                cov["routes_v3" if is_v3 else "routes_v2v2"] += 1
                # ancre indépendante pour token0
                if usd0 == "WETH":
                    cands = [x for x in wu if x[0] not in (pa["venue"], pb["venue"])]
                    u0 = max(cands, key=lambda x: x[2])[1] if cands else None
                elif usd0 is None:
                    u0 = None
                else:
                    u0 = usd0
                if u0 is None:
                    cov["abstain:ancre_independante_absente"] += 1; continue
                # PRÉ-FILTRE slot0/mid — SÛR : mid-gap < frais => quote exacte (<= mid par l'impact) => profit
                # impossible. On ne quote (cher) QUE les routes au mid-gap >= frais ; aucun faux négatif.
                ma, mb = pa.get("mid"), pb.get("mid")
                if not ma or not mb:
                    cov["abstain:mid_illisible"] += 1; continue
                if abs(ma - mb) / min(ma, mb) * 1e4 < _fee_bps(pa) + _fee_bps(pb):
                    cov["rejet:sous_frais_mid_prefiltre"] += 1; continue
                d = evaluate_route_quoted(f"{s0}/{s1}", pa["venue"], pb["venue"], pa, pb,
                                          SIZES_USD, FIXED_USD, u0, dec_x, gas_model, quote_leg)
                if d.status == "REJETE":
                    cov[f"rejet:{d.reason}"] += 1
                else:
                    positives[(d.pair, d.venue_a, d.venue_b)] = d
                w.writerow([N, ts, d.pair, d.venue_a, d.venue_b, d.direction, d.status, d.reason,
                            _f(d.pnl_quote_usd), _f(d.gas_exec_usd), _f(d.gas_l1_usd), _f(d.gas_marge_usd),
                            _f(d.gas_total_usd), _f(d.pnl_net_usd), _f(d.opt_size_usd), _f(d.max_net_usd),
                            _f(d.breakeven_size_usd), _f(d.size_90_usd), _f(d.capacity_usd),
                            _f(d.fixed_net_usd), d.n_abstain_sizes])
                rk = (d.pair, d.venue_a, d.venue_b)
                o = obs.setdefault(rk, {"net": [], "abstain": 0})
                if d.fixed_net_usd == d.fixed_net_usd:        # net à taille fixe lisible
                    o["net"].append(d.fixed_net_usd)
                else:
                    o["abstain"] += 1
        if read % 12 == 0:
            f.flush(); print(f"  {read}/{requested} blocs | quotes v3 ok={qstats['ok']} revert={qstats['revert']}")
    f.close()

    # Classement DESCRIPTIF (gel #3) — jamais FORWARD en calibration (gel #1)
    min_blocks = max(10, read // 2)
    classed = defaultdict(int)
    rows_status = []
    for rk, d in positives.items():
        o = obs.get(rk, {"net": [], "abstain": 0})
        pers = persistence_stats(o["net"], FIXED_USD, min_blocks, o["abstain"])
        st = classify_calibration(pers.frac_positive, pers.longest_streak, pers.min_blocks_ok,
                                  args.persist_frac, args.persist_streak)
        classed[st] += 1
        if st != "REJETE":
            rows_status.append((rk, d, pers, st))

    f_hash = sha256_file(out_path)
    rejets = {k[6:]: v for k, v in cov.items() if k.startswith("rejet:")}
    abst = {k[8:]: v for k, v in cov.items() if k.startswith("abstain:")}

    print("\n" + "=" * 80)
    print("CALIBRATION TECHNIQUE v3 — couverture séparée (gel #5). VERDICT MODESTE, jamais FORWARD.")
    print(f"  COUVERTURE blocs : {requested} demandés | {read} lus")
    print(f"  routes v3 trouvées : {cov['routes_v3']} | routes v2 : {cov['routes_v2v2']}")
    print(f"  quotes v3 : réussies {qstats['ok']} | revert/illisibles {qstats['revert']}")
    print(f"  pools/tokens exclus : {excluded}")
    if abst:
        print("  abstentions par motif :")
        for r, n in sorted(abst.items(), key=lambda x: -x[1]):
            print(f"     {n:>6}  {r}")
    if rejets:
        print("  rejets par motif :")
        for r, n in sorted(rejets.items(), key=lambda x: -x[1]):
            print(f"     {n:>6}  {r}")
    print(f"  classement PnL>0 (descriptif) : " +
          " | ".join(f"{k}={classed.get(k,0)}" for k in ("MEV_RACE", "A_OBSERVER_COURT", "A_OBSERVER")))
    for rk, d, pers, st in sorted(rows_status, key=lambda x: -x[1].max_net_usd)[:10]:
        print(f"    [{st}] {d.pair} {d.venue_a}->{d.venue_b} net~${d.pnl_net_usd:.2f}@${d.opt_size_usd:.0f} "
              f"cap~${d.capacity_usd:.0f} persist {pers.frac_positive:.0%}/{pers.longest_streak}blk")

    n_observ = classed.get("A_OBSERVER", 0) + classed.get("A_OBSERVER_COURT", 0)
    verdict = "VALIDE" if (read >= 2 and qstats["ok"] > 0) else "NON_CONCLUANT"   # VALIDE = la MACHINE marche (technique)
    run_dir, m = write_manifest(
        slug="backfill-v3-calibration-technique",
        hypothesis=("CALIBRATION TECHNIQUE : le quoteur v3 historique, la couverture, le coût (gas séparé), "
                    "la courbe de taille et la qualité des abstentions fonctionnent-ils ? (PAS de conclusion éco.)"),
        command=(f"python backfill_v3.py --days {args.days:.0f} --cadence-min {args.cadence_min:.0f} "
                 f"--start-block {start} --end-block {end} --l1-usd {args.l1_usd} --gas-margin-frac {args.gas_margin_frac}"),
        period=f"blocs {start}..{end} (pas {step}, {requested} demandés)",
        sources=[f"archive RPC Base : {redact(used)}", "QuoterV2 Uniswap v3 (quote exacte au bloc) + état v2 on-chain"],
        inputs=[os.path.relpath(live.UNIVERSE_PATH, HERE), os.path.relpath(out_path, HERE)],   # 2e = HASH DE SORTIE
        universe=f"{len(dec)} tokens certifiés ; UniV3 {{500,3000}} ; routes v3↔v3 & v3↔v2 ; grille {SIZES_USD}",
        costs=("gas_estime_conservateur SÉPARÉ : exec (gasEstimate quoteur/forfait × baseFee) + L1-data "
               f"${args.l1_usd} + marge {args.gas_margin_frac:.0%} ; ancre USD indépendante au bloc"),
        result=(f"{read}/{requested} blocs ; routes v3 {cov['routes_v3']} ; quotes ok {qstats['ok']} revert "
                f"{qstats['revert']} ; PnL>0 [MEV_RACE {classed.get('MEV_RACE',0)}, COURT "
                f"{classed.get('A_OBSERVER_COURT',0)}, A_OBSERVER {classed.get('A_OBSERVER',0)}] ; sha256(sortie)={f_hash[:16]}"),
        verdict=verdict,
        notes=("CALIBRATION TECHNIQUE (#1) : aucun CANDIDAT_FORWARD produit ici ; toute conclusion éco exige une "
               "fenêtre PRÉFIXÉE 7–14 j. Borne SUPÉRIEURE (quote = réserves+simulation, ne voit ni intra-bloc ni "
               "MEV). Un résultat vide sur cet univers de calibration n'est JAMAIS 'pas d'alpha DeFi'."),
    )
    print(f"\nMANIFESTE -> {os.path.relpath(run_dir, HERE)}/  (verdict {verdict} = la machine, pas l'éco) | "
          f"sortie {os.path.relpath(out_path, HERE)}")
    print("Rappel : calibration TECHNIQUE. Pas de FORWARD, pas de conclusion économique sur 2 jours.")
    return 0


def _f(x) -> str:
    return "" if x != x else f"{x:.8g}"


if __name__ == "__main__":
    raise SystemExit(main())
