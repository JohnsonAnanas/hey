#!/usr/bin/env python
"""Backfill de CALIBRATION intra-chaine (Base, v2 certifie) — relit l'etat ON-CHAIN a des blocs PASSES.

Meme moteur que le live (scan_dex_intrachain) : memes 7 portes (sim/route_eval), meme math ENTIERE
EVM (sim/amm_v2_int), meme univers certifie par adresse. La SEULE difference : on lit l'etat au BLOC
PASSE via un RPC d'ARCHIVE (Multicall3.aggregate3 avec block_identifier), au lieu de poller le tip.

NON-NEGOCIABLES (cf demande) :
- appels historiques sur un RPC archive REELLEMENT capable de lire l'etat au bloc demande (verifie au
  demarrage ; sinon abort, jamais de repli silencieux sur le tip) ;
- frais, reserves, gas (baseFee du bloc) et ancre USD du MEME bloc (1 aggregate3 + 1 getBlock par bloc) ;
- calcul en unites BRUTES avec arrondis EVM (sim/amm_v2_int) ;
- AUCUNE donnee manquante remplacee par une valeur actuelle -> lecture KO = ABSTENTION loggee ;
- couverture rapportee : X blocs demandes, Y lus, Z abstentions (+ motifs) ;
- manifeste : plage de blocs, RPC/source (redige), parametres, hash de sortie, verdict.

VERDICT MODESTE (le seul qu'un backfill de reserves autorise) :
  Le moteur observe-t-il des PnL nets positifs, sur des routes certifiees, a une taille utile, et
  pendant assez de blocs pour justifier un test FORWARD ?
PAS : "on aurait gagne". Un backfill de reserves ne voit NI les tx concurrentes intra-bloc NI le MEV.

Usage : python backfill_intrachain.py --days 7 --cadence-min 60
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import os
import sys
import time
from collections import defaultdict
from itertools import combinations
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from web3 import Web3
from eth_abi import encode as abi_encode

from sim.chain import MULTICALL3, ABI_MC3, SEL_RESERVES, SEL_GETFEE, uint_from
from sim.pricing import reference_usd, pool_liquidity_usd
from sim.route_eval import load_universe, evaluate_route, persistence_stats, assign_forward
from sim.amm_v2_int import two_pool_profit
from manifest import write_manifest
from archive_rpc import endpoints, redact
import scan_dex_intrachain as live   # reutilise load_config, verify_decimals, resolve, derive_eth_usd, STABLES

HERE = os.path.dirname(os.path.abspath(__file__))
CHAIN_ID = 8453


class ArchiveMC:
    """Multicall3 via un endpoint ARCHIVE : lectures atomiques AU BLOC demande (block_identifier)."""

    def __init__(self, w3):
        self.w3 = w3
        self.mc = w3.eth.contract(address=MULTICALL3, abi=ABI_MC3)

    def multicall(self, calls, block="latest"):
        payload = [(Web3.to_checksum_address(t), True, d) for (t, d) in calls]
        return self.mc.functions.aggregate3(payload).call(block_identifier=block)


def est_block_time(w3, tip, span=20000):
    try:
        t1 = w3.eth.get_block(tip)["timestamp"]
        t0 = w3.eth.get_block(max(1, tip - span))["timestamp"]
        return (t1 - t0) / min(span, tip - 1) if t1 > t0 else 2.0
    except Exception:
        return 2.0


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="Backfill de calibration intra-chaine Base v2 (archive, lecture seule).")
    ap.add_argument("--days", type=float, default=7.0)
    ap.add_argument("--cadence-min", type=float, default=60.0, help="cadence FIXE (minutes) entre blocs lus")
    ap.add_argument("--start-block", type=int, default=0, help="reproductibilite exacte (sinon derive de --days)")
    ap.add_argument("--end-block", type=int, default=0)
    ap.add_argument("--gas-units", type=int, default=300_000)
    ap.add_argument("--min-usd", type=float, default=50_000.0)
    ap.add_argument("--status-margin", type=float, default=5.0)
    ap.add_argument("--persist-frac", type=float, default=0.7)
    ap.add_argument("--persist-streak", type=int, default=3)
    ap.add_argument("--cap-min-usd", type=float, default=200.0)
    args = ap.parse_args()

    universe, A, dec_cfg = live.load_config()

    # 1) Connexion + resolution des pools au TIP (adresses statiques) sur un endpoint Base.
    urls = endpoints("base")
    if not urls:
        print("Aucun endpoint Base (archive_rpc).", file=sys.stderr); return 1
    w3 = mc = used_url = None
    for url in urls:
        try:
            cand = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 25}))
            if cand.eth.chain_id == CHAIN_ID:
                w3, mc, used_url = cand, ArchiveMC(cand), url
                break
        except Exception as e:
            print(f"  [endpoint KO] {redact(url)} : {type(e).__name__}")
    if w3 is None:
        print("Aucun endpoint Base sain.", file=sys.stderr); return 1
    tip = w3.eth.block_number
    bt = est_block_time(w3, tip)
    print(f"RPC: {redact(used_url)} | tip {tip} | temps de bloc ~{bt:.2f}s")

    dec, dropped = live.verify_decimals(mc, A, dec_cfg)
    for s, why in dropped:
        print(f"  [token ecarte] {s} : {why}")
    pairs, valid, v3, quarantined = live.resolve(mc, A, dec)
    for p, reasons in quarantined:
        s0, s1 = p["pair"]; print(f"  [quarantaine] {p['venue']:<10} {s0}/{s1:<6} : {', '.join(reasons)}")
    if not valid:
        print("Aucun pool v2 valide.", file=sys.stderr); return 1

    # 2) Plage de blocs (cadence FIXE) — reproductible (consignee dans le manifeste).
    step = max(1, round(args.cadence_min * 60 / bt))
    if args.start_block and args.end_block:
        start, end = args.start_block, args.end_block
    else:
        start, end = max(1, tip - int(args.days * 86400 / bt)), tip
    blocks = list(range(start, end + 1, step))
    print(f"plage blocs : {start}..{end} pas {step} (~{args.cadence_min:.0f}min) -> {len(blocks)} blocs demandes")

    # 3) VERIFICATION ARCHIVE : le RPC lit-il REELLEMENT l'etat au 1er bloc demande ? (sinon abort)
    probe = Web3.to_checksum_address(valid[0]["address"])
    try:
        r = mc.multicall([(probe, SEL_RESERVES)], block=start)
        if not (r and r[0][0] and len(r[0][1]) >= 64):
            raise RuntimeError("lecture vide")
        print(f"  archive OK : etat lu au bloc {start} (pool sonde {probe[:10]}).")
    except Exception as e:
        print(f"ABORT : le RPC ne lit PAS l'etat au bloc {start} ({type(e).__name__}: {str(e)[:60]}). "
              f"Pas de repli sur le tip. Active un endpoint archive (ALCHEMY_KEY).", file=sys.stderr)
        return 2

    # routes structurelles v3 (non quotees) — comptees une fois (couverture #1/#7)
    by_pair = defaultdict(list)
    for p in valid + v3:
        by_pair[p["pair"]].append(p)
    routable = {pk: ps for pk, ps in by_pair.items() if len([x for x in ps if x["kind"] != "v3"]) >= 2 or len(ps) >= 2}
    v3_routes_struct = 0
    for pk, ps in routable.items():
        n_all, n_v2 = len(ps), len([x for x in ps if x["kind"] != "v3"])
        v3_routes_struct += n_all * (n_all - 1) // 2 - n_v2 * (n_v2 - 1) // 2

    out_dir = Path(HERE) / "data" / "logs"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"backfill_intrachain_{stamp}.csv"
    f = open(out_path, "w", newline="", encoding="utf-8")
    w = csv.writer(f)
    w.writerow(["block", "ts_unix", "pair", "venue_a", "venue_b", "direction", "status", "reason",
                "pnl_gross_usd", "pool_fees_usd", "gas_usd", "pnl_net_usd", "opt_size_x", "opt_notional_usd",
                "max_net_usd", "breakeven_size_x", "size_90_x", "capacity_usd"])

    requested = len(blocks)
    read = 0
    blk_abstain = defaultdict(int)
    pool_reads = bad_pool_reads = 0
    cov = defaultdict(int)
    obs = {}            # persistance : route_key -> {dir, fixed_wei, pa, pb, dec_x, net[], abstain}
    decisions = {}
    eval_aero = [p for p in valid if p["kind"] == "solidly"]
    print(f"\nBackfill {len(blocks)} blocs, {len(valid)} pools v2, {len(routable)} paires routables, "
          f"liquidite min ${args.min_usd:,.0f}/jambe.\n")

    for N in blocks:
        try:
            reserve_calls = [(Web3.to_checksum_address(p["address"]), SEL_RESERVES) for p in valid]
            fee_calls = [(Web3.to_checksum_address(p["factory"]),
                          SEL_GETFEE + abi_encode(["address", "bool"], [Web3.to_checksum_address(p["address"]), False]))
                         for p in eval_aero]
            res = mc.multicall(reserve_calls + fee_calls, block=N)
            blk = w3.eth.get_block(N)
        except Exception as e:
            blk_abstain["bloc_illisible"] += 1
            continue
        read += 1
        ts = blk["timestamp"]
        base_fee = blk.get("baseFeePerGas") or 0
        for p, (ok, data) in zip(valid, res[:len(reserve_calls)]):
            pool_reads += 1
            p["r0"] = p["r1"] = 0
            if ok and len(data) >= 64:
                p["r0"] = int.from_bytes(data[0:32], "big")
                p["r1"] = int.from_bytes(data[32:64], "big")
            if not (p["r0"] and p["r1"]):
                bad_pool_reads += 1               # pool absent/illisible/incoherent A CE BLOC (jamais comble)
        for p, (ok, data) in zip(eval_aero, res[len(reserve_calls):]):
            if ok and data:
                rate = (uint_from(data) or 0) / 10_000.0
                if 0 < rate < 0.05:
                    p["fee_bps"] = round(rate * 10_000)
        eth_usd = live.derive_eth_usd(valid)
        if eth_usd is None:
            blk_abstain["ancre_usd_absente"] += 1   # NON-NEGOCIABLE : jamais de prix de secours -> abstention
            continue
        gas_usd = args.gas_units * base_fee / 1e18 * eth_usd

        for (s0, s1), ps in routable.items():
            live_v2 = [p for p in ps if p["kind"] != "v3" and p["r0"] and p["r1"]]
            reserves_h = [(p["r0"] / 10 ** p["dec0"], p["r1"] / 10 ** p["dec1"]) for p in live_v2]
            refs = reference_usd(s0, s1, reserves_h, eth_usd, live.STABLES) if reserves_h else None
            if not refs:
                continue
            usd0, usd1 = refs
            deep = [p for p, (r0h, r1h) in zip(live_v2, reserves_h)
                    if pool_liquidity_usd(r0h, r1h, usd0, usd1) >= args.min_usd]
            for pa, pb in combinations(deep, 2):
                d = evaluate_route(pa, pb, usd0, gas_usd, universe, args.status_margin)
                cov["routes_v2"] += 1
                if d.status == "REJETE":
                    cov[f"rejet:{d.reason}"] += 1
                w.writerow([N, ts, d.pair, d.venue_a, d.venue_b, d.direction, d.status, d.reason,
                            _f(d.pnl_gross_usd), _f(d.pool_fees_usd), _f(d.gas_usd), _f(d.pnl_net_usd),
                            _f(d.opt_size_x), _f(d.opt_notional_usd), _f(d.max_net_usd),
                            _f(d.breakeven_size_x), _f(d.size_90_x), _f(d.capacity_usd)])
                if d.status == "A_OBSERVER":
                    cov["a_observer_hits"] += 1
                    decisions[(d.pair, d.venue_a, d.venue_b)] = d
                    rk = (d.pair, d.venue_a, d.venue_b)
                    if rk not in obs:
                        dx = pa["dec0"] if d.direction == "A->B" else pb["dec0"]
                        obs[rk] = {"dir": d.direction, "fixed_wei": int(d.opt_size_x * 10 ** dx),
                                   "pa": pa, "pb": pb, "dec_x": dx, "net": [], "abstain": 0}
        # persistance a TAILLE FIXE (toutes routes suivies), ce bloc
        for rk, o in obs.items():
            pa, pb = (o["pa"], o["pb"]) if o["dir"] == "A->B" else (o["pb"], o["pa"])
            s0 = o["pa"]["pair"][0]
            u0 = 1.0 if s0 in live.STABLES else (eth_usd if s0 == "WETH" else None)
            if not (pa["r0"] and pa["r1"] and pb["r0"] and pb["r1"]) or u0 is None:
                o["abstain"] += 1; continue
            o["net"].append(two_pool_profit(o["fixed_wei"], pa, pb) / 10 ** o["dec_x"] * u0 - gas_usd)
        if read % 24 == 0:
            f.flush(); print(f"  {read}/{requested} blocs lus... (bloc {N})")
    f.close()

    # --- FORWARD via persistance (min_blocks = la moitie des blocs lus, borne a >=10) ---
    min_blocks = max(10, read // 2)
    forward = []
    for rk, d in decisions.items():
        o = obs.get(rk)
        if not o:
            continue
        pers = persistence_stats(o["net"], o["fixed_wei"] / 10 ** o["dec_x"], min_blocks, o["abstain"])
        d2 = assign_forward(d, pers, p_min=args.persist_frac, streak_min=args.persist_streak, cap_min_usd=args.cap_min_usd)
        if d2.status == "CANDIDAT_FORWARD":
            forward.append((rk, d2, pers))

    f_hash = sha256_file(out_path)
    rejets = {k[6:]: v for k, v in cov.items() if k.startswith("rejet:")}
    bad_frac = (bad_pool_reads / pool_reads) if pool_reads else 0.0

    print("\n" + "=" * 80)
    print("CALIBRATION BACKFILL — couverture (le verdict reste MODESTE)")
    print(f"  COUVERTURE : {requested} blocs demandes | {read} lus | {requested - read} abstentions bloc")
    for r, n in blk_abstain.items():
        print(f"     abstention bloc: {n:>4}  {r}")
    print(f"  lectures pool illisibles/incoherentes : {bad_pool_reads}/{pool_reads} ({100*bad_frac:.1f}%)")
    print(f"  routes v2 evaluees : {cov['routes_v2']} | v3 non quotees (structurel) : {v3_routes_struct}")
    print(f"  A_OBSERVER (hits) : {cov['a_observer_hits']} | routes distinctes A_OBSERVER : {len(decisions)} | "
          f"CANDIDAT_FORWARD : {len(forward)}")
    if rejets:
        print("  rejets v2 par motif :")
        for r, n in sorted(rejets.items(), key=lambda x: -x[1]):
            print(f"     {n:>6}  {r}")
    if forward:
        print("  CANDIDAT_FORWARD :")
        for rk, d, pers in forward:
            print(f"     {d.pair} {d.venue_a}->{d.venue_b} net~${d.pnl_net_usd:.2f} cap~${d.capacity_usd:.0f} "
                  f"persist {pers.frac_positive:.0%}/{pers.longest_streak}blk sur {pers.n_blocks}")

    verdict = "LEAD" if forward else "NON_CONCLUANT"   # signal forward = PISTE, jamais VALIDE (§2)
    run_dir, m = write_manifest(
        slug="backfill-intrachain-base-calibration",
        hypothesis=("Sur Base v2 certifie, le moteur observe-t-il des PnL nets POSITIFS, sur routes certifiees, "
                    "a taille utile, et assez de blocs pour justifier un test FORWARD ? (PAS 'on aurait gagne'.)"),
        command=(f"python backfill_intrachain.py --days {args.days:.0f} --cadence-min {args.cadence_min:.0f} "
                 f"--start-block {start} --end-block {end} --min-usd {args.min_usd:.0f} --gas-units {args.gas_units}"),
        period=f"blocs {start}..{end} (pas {step}, {requested} demandes)",
        sources=[f"archive RPC Base : {redact(used_url)}", "etat on-chain au bloc (getReserves/getFee + baseFee du bloc)"],
        inputs=[os.path.relpath(live.UNIVERSE_PATH, HERE), os.path.relpath(out_path, HERE)],   # 2e = HASH DE SORTIE
        universe=f"{len(dec)} tokens certifies v2 ; {len(routable)} paires routables ; {len(valid)} pools v2",
        costs=(f"frais pool au bloc ; gas {args.gas_units}u x baseFee(bloc) ; ancre USD(bloc) ; "
               f"taille optimale ENTIERE EVM ; marge statut ${args.status_margin:.0f}"),
        result=(f"{requested} demandes / {read} lus / {requested-read} abstentions ; lectures illisibles {100*bad_frac:.1f}% ; "
                f"routes v2 {cov['routes_v2']} ; A_OBSERVER {len(decisions)} ; FORWARD {len(forward)} ; "
                f"v3 non quotees {v3_routes_struct} ; sha256(sortie)={f_hash[:16]}"),
        verdict=verdict,
        notes=("Backfill de RESERVES : reconstruit le prix/PnL exact au bloc, mais NE VOIT NI les transactions "
               "concurrentes intra-bloc NI le positionnement MEV reel. Ne prouve donc PAS qu'on aurait gagne ; "
               "borne SUPERIEURE optimiste. Un FORWARD reste requis pour conclure."),
    )
    print(f"\nMANIFESTE -> {os.path.relpath(run_dir, HERE)}/  (verdict {verdict}) | sortie {os.path.relpath(out_path, HERE)}")
    print("Rappel : un backfill de reserves est une borne SUPERIEURE — il ne voit pas le MEV intra-bloc.")
    return 0


def _f(x) -> str:
    return "" if x != x else f"{x:.8g}"


if __name__ == "__main__":
    raise SystemExit(main())
