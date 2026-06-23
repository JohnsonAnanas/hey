#!/usr/bin/env python
"""Runner Phase B — evaluateur de route DeFi INTRA-CHAINE (Base, LECTURE SEULE, zero capital).

Cherche des dislocations capturables ENTRE PROTOCOLES d'une meme chaine (fragmentation de liquidite),
PAS des 'bugs' ni des prix affiches. Chaque route passe les 7 portes de sim/route_eval (math ENTIERE
EVM, identite certifiee par adresse, decomposition gross/frais/gas/net, courbe, v3 -> REJETE explicite).
Sortie = TABLEAU DE DECISION + rapport de COUVERTURE + MANIFESTE obligatoire.

IMPORTANT (cadre utilisateur) : c'est un univers de CALIBRATION. Un resultat vide n'est PAS une
absence d'alpha DeFi -- c'est une mesure de couverture (routes v2 evaluees, v3 abstenues, pools
rejetes). Aucune execution, aucune cle privee, aucun flash loan, aucun mempool, aucun cross-chain.

Usage : python scan_dex_intrachain.py --seconds 60 --min-usd 50000
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
from eth_abi import encode as abi_encode

from sim.chain import (RPC, addr_from, uint_from, SEL_GETPAIR, SEL_GETPOOL_BOOL, SEL_GETPOOL_V3,
                       SEL_GETFEE, SEL_RESERVES, SEL_DECIMALS)
from sim.validate import validate_pools
from sim.pricing import reference_usd, pool_liquidity_usd
from sim.integrity import poll_meta, poll_should_abstain
from sim.route_eval import load_universe, evaluate_route, persistence_stats, assign_forward
from manifest import write_manifest

HERE = os.path.dirname(os.path.abspath(__file__))
UNIVERSE_PATH = os.path.join(HERE, "config", "universe_base.json")
STABLES = {"USDC"}

# Venues v2 (constant-product) — frais 0.30% fixes pour les forks UniV2 ; Aerodrome volatile lu on-chain.
V2_FACTORIES = [
    {"name": "UniV2",     "factory": "0x8909Dc15e40173Ff4699343b6eB8132c65e18eC6", "method": "getPair",     "fee": 0.0030, "kind": "univ2"},
    {"name": "SushiV2",   "factory": "0x71524B4f93c58fcbF659783284E38825f0622859", "method": "getPair",     "fee": 0.0030, "kind": "univ2"},
    {"name": "BaseSwap",  "factory": "0xFDa619b6d20975be80A10332cD39b9a4b0FAa8BB", "method": "getPair",     "fee": 0.0030, "kind": "univ2"},
    {"name": "Aerodrome", "factory": "0x420DD381b31aEf6683db6B902084cB0FFECe40Da", "method": "getPoolBool", "fee": None,   "kind": "solidly"},
]
# Venues v3 — incluses pour COUVERTURE : toute route v3 -> REJETE: v3_quoter_non_implemente (#7).
V3_VENUES = [
    {"name": "UniV3-5",   "factory": "0x33128a8fC17869897dcE68Ed026d694621f6FDfD", "fee": 500},
    {"name": "UniV3-30",  "factory": "0x33128a8fC17869897dcE68Ed026d694621f6FDfD", "fee": 3000},
    {"name": "PancV3-5",  "factory": "0x0BFbCF9fa4f9C56B0F40a671Ad40E0805A091865", "fee": 500},
    {"name": "PancV3-25", "factory": "0x0BFbCF9fa4f9C56B0F40a671Ad40E0805A091865", "fee": 2500},
]


def load_config():
    universe = load_universe(UNIVERSE_PATH)                       # {addr_lower: {symbol, decimals}}
    import json
    with open(UNIVERSE_PATH, encoding="utf-8") as f:
        cfg = json.load(f)
    A = {v["symbol"]: Web3.to_checksum_address(a) for a, v in cfg["tokens"].items()}
    dec_cfg = {v["symbol"]: v["decimals"] for v in cfg["tokens"].values()}
    return universe, A, dec_cfg


def build_pairs(A) -> list[tuple[str, str]]:
    pairs = []
    for s0, s1 in combinations(A, 2):
        pairs.append((s0, s1) if int(A[s0], 16) < int(A[s1], 16) else (s1, s0))
    return pairs


def verify_decimals(rpc, A, dec_cfg):
    """Re-verifie les decimals ON-CHAIN vs la config versionnee (identite : on ne fait pas confiance
    a un fichier seul). Ecart -> token ECARTE (loggue), jamais utilise."""
    syms = list(A)
    res = rpc.multicall([(A[s], SEL_DECIMALS) for s in syms])
    dec, dropped = {}, []
    for (ok, data), s in zip(res, syms):
        v = uint_from(data) if ok else None
        if v is None:
            dropped.append((s, "decimals illisible on-chain"))
        elif v != dec_cfg[s]:
            dropped.append((s, f"decimals on-chain {v} != config {dec_cfg[s]}"))
        else:
            dec[s] = v
    return dec, dropped


def resolve(rpc, A, dec):
    """Resout pools v2 (valides) + v3 (pour couverture). Renvoie (pairs, valides_v2, v3, quarantaine)."""
    pairs = [(s0, s1) for (s0, s1) in build_pairs(A) if s0 in dec and s1 in dec]
    specs, calls = [], []
    for (s0, s1) in pairs:
        for f in V2_FACTORIES:
            fac = Web3.to_checksum_address(f["factory"])
            cd = (SEL_GETPAIR + abi_encode(["address", "address"], [A[s0], A[s1]])) if f["method"] == "getPair" \
                else (SEL_GETPOOL_BOOL + abi_encode(["address", "address", "bool"], [A[s0], A[s1], False]))
            specs.append({"pair": (s0, s1), "venue": f["name"], "method": f["method"], "fee": f["fee"],
                          "kind": f["kind"], "factory": fac})
            calls.append((fac, cd))
        for v in V3_VENUES:
            fac = Web3.to_checksum_address(v["factory"])
            cd = SEL_GETPOOL_V3 + abi_encode(["address", "address", "uint24"], [A[s0], A[s1], v["fee"]])
            specs.append({"pair": (s0, s1), "venue": v["name"], "method": "getPoolV3", "fee": None,
                          "kind": "v3", "factory": fac, "fee_tier": v["fee"]})   # fee_tier pour le quoteur v3
            calls.append((fac, cd))
    res = rpc.multicall(calls)
    resolved = [{**spec, "address": addr_from(data)} for spec, (ok, data) in zip(specs, res) if ok and addr_from(data)]

    v2 = [p for p in resolved if p["kind"] != "v3"]
    v3 = [p for p in resolved if p["kind"] == "v3"]

    aero = [p for p in v2 if p["method"] == "getPoolBool"]
    if aero:
        rf = rpc.multicall([(p["factory"], SEL_GETFEE +
                             abi_encode(["address", "bool"], [Web3.to_checksum_address(p["address"]), False])) for p in aero])
        for p, (ok, data) in zip(aero, rf):
            rate = (uint_from(data) or 0) / 10_000.0 if ok else 0
            p["fee"] = rate if 0 < rate < 0.05 else None          # PAS de fallback muet -> quarantaine si illisible

    valid, quarantined = validate_pools(rpc, v2, A)
    for p in valid:                                               # champs statiques pour route_eval
        s0, s1 = p["pair"]
        p["t0_addr"], p["t1_addr"] = A[s0].lower(), A[s1].lower()
        p["dec0"], p["dec1"] = dec[s0], dec[s1]
        if p["method"] == "getPoolBool":
            p["kind"], p["fee_bps"] = "solidly", round(p["fee"] * 10_000)
        else:
            p["kind"], p["fee_num"], p["fee_den"] = "univ2", 997, 1000
        p["r0"] = p["r1"] = 0
    for p in v3:
        s0, s1 = p["pair"]
        p["t0_addr"], p["t1_addr"] = A[s0].lower(), A[s1].lower()
        p["dec0"], p["dec1"] = dec[s0], dec[s1]
        p["r0"] = p["r1"] = 0
    return pairs, valid, v3, quarantined


def derive_eth_usd(v2pools):
    best, price = -1.0, None
    for p in v2pools:
        if set(p["pair"]) == {"WETH", "USDC"} and p["r0"] and p["r1"]:
            s0, s1 = p["pair"]
            r0h, r1h = p["r0"] / 10 ** p["dec0"], p["r1"] / 10 ** p["dec1"]
            usdc = r1h if s1 == "USDC" else r0h
            if usdc > best:
                best, price = usdc, (r1h / r0h if s0 == "WETH" else r0h / r1h)
    return price


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="Evaluateur de route DeFi intra-chaine sur Base (lecture seule).")
    ap.add_argument("--seconds", type=float, default=60.0)
    ap.add_argument("--interval", type=float, default=4.0)
    ap.add_argument("--gas-units", type=int, default=300_000)
    ap.add_argument("--min-usd", type=float, default=50_000.0, help="liquidite USD min/jambe (prix de reference)")
    ap.add_argument("--status-margin", type=float, default=5.0, help="marge de securite (USD) pour FORWARD")
    ap.add_argument("--persist-min-blocks", type=int, default=10)
    ap.add_argument("--persist-frac", type=float, default=0.7, help="part min de blocs net>0 pour FORWARD")
    ap.add_argument("--persist-streak", type=int, default=3, help="plus longue sequence net>0 min pour FORWARD")
    ap.add_argument("--cap-min-usd", type=float, default=200.0, help="capacite min (USD) pour FORWARD")
    args = ap.parse_args()

    universe, A, dec_cfg = load_config()
    rpc = RPC()
    dec, dropped_dec = verify_decimals(rpc, A, dec_cfg)
    for s, why in dropped_dec:
        print(f"  [token ecarte] {s} : {why}")
    print("Resolution pools v2 (valides) + v3 (couverture) :")
    pairs, valid, v3, quarantined = resolve(rpc, A, dec)
    for p, reasons in quarantined:
        s0, s1 = p["pair"]
        print(f"  [quarantaine] {p['venue']:<10} {s0}/{s1:<6} : {', '.join(reasons)}")
    by_pair = defaultdict(list)
    for p in valid + v3:
        by_pair[p["pair"]].append(p)
    routable = {pk: ps for pk, ps in by_pair.items() if len(ps) >= 2}
    print(f"paires testees: {len(pairs)} | pools v2 valides: {len(valid)} | pools v3: {len(v3)} | "
          f"quarantaine: {len(quarantined)} | paires routables (>=2 pools): {len(routable)}")
    if not routable:
        print("Aucune paire routable. (Tests: pytest tests/)", file=sys.stderr)

    out_dir = Path(HERE) / "data" / "logs"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    log_path = out_dir / f"intrachain_{stamp}.csv"
    f = open(log_path, "w", newline="", encoding="utf-8")
    w = csv.writer(f)
    w.writerow(["ts", "block", "pair", "venue_a", "venue_b", "direction", "status", "reason",
                "pnl_gross_usd", "pool_fees_usd", "gas_usd", "pnl_net_usd",
                "opt_size_x", "opt_notional_usd", "max_net_usd", "breakeven_size_x", "size_90_x", "capacity_usd"])

    cov = defaultdict(int)                          # compteurs de couverture par statut/motif
    obs = {}                                        # persistance : route_key -> {dir, fixed_size_wei, pa, pb, dec_x, net_series, last}
    decisions = {}                                  # derniere decision A_OBSERVER par route_key (pour le tableau final)
    blocks_seen = set()
    valid_v2 = valid
    t_end = time.time() + args.seconds
    print(f"\nScan {args.seconds:.0f}s, poll {args.interval:.1f}s, {len(routable)} paires routables, "
          f"liquidite min ${args.min_usd:,.0f}/jambe. (CALIBRATION — vide != absence d'alpha)\n")
    try:
        while time.time() < t_end:
            t0 = time.time()
            reserve_calls = [(Web3.to_checksum_address(p["address"]), SEL_RESERVES) for p in valid_v2]
            try:
                block, block_ts, res, fresh = rpc.read_block(reserve_calls)
                gas_price = rpc.w3.eth.gas_price
            except Exception as e:
                print(f"poll KO : {e!r}"); time.sleep(args.interval); continue
            ab = poll_should_abstain(fresh)
            if ab:
                print(f"[{time.strftime('%H:%M:%S')} blk={block}] ABSTAIN poll : {ab}")
                time.sleep(max(0.0, args.interval - (time.time() - t0))); continue
            if block:
                blocks_seen.add(block)
            for p, (ok, data) in zip(valid_v2, res):
                p["r0"] = p["r1"] = 0
                if ok and len(data) >= 64:
                    p["r0"] = int.from_bytes(data[0:32], "big")
                    p["r1"] = int.from_bytes(data[32:64], "big")
            eth_usd = derive_eth_usd(valid_v2)
            if eth_usd is None:
                print(f"[{time.strftime('%H:%M:%S')} blk={block}] ABSTAIN : pas d'ancre WETH/USDC liquide")
                time.sleep(max(0.0, args.interval - (time.time() - t0))); continue
            gas_usd = args.gas_units * gas_price / 1e18 * eth_usd

            poll_obs = 0
            for (s0, s1), ps in routable.items():
                live_v2 = [p for p in ps if p["kind"] != "v3" and p["r0"] and p["r1"]]
                reserves_h = [(p["r0"] / 10 ** p["dec0"], p["r1"] / 10 ** p["dec1"]) for p in live_v2]
                refs = reference_usd(s0, s1, reserves_h, eth_usd, STABLES) if reserves_h else None
                usd0 = refs[0] if refs else None
                # filtre liquidite au prix de reference (anti dust-mirage)
                if refs:
                    usd0, usd1 = refs
                    deep = [p for p, (r0h, r1h) in zip(live_v2, reserves_h)
                            if pool_liquidity_usd(r0h, r1h, usd0, usd1) >= args.min_usd]
                else:
                    deep = []
                v3_here = [p for p in ps if p["kind"] == "v3"]
                routables_pools = deep + v3_here                  # v3 inclus -> routes v3 rejetees (couverture)
                for pa, pb in combinations(routables_pools, 2):
                    if usd0 is None and "v3" not in (pa["kind"], pb["kind"]):
                        cov["abstain_pricing"] += 1; continue     # pas d'ancre prix -> on ne fabrique pas un net
                    d = evaluate_route(pa, pb, usd0 if usd0 else float("nan"), gas_usd, universe, args.status_margin)
                    cov["routes_total"] += 1
                    if d.status == "REJETE":
                        cov[f"rejet:{d.reason}"] += 1
                    rkey = (f"{s0}/{s1}", pa["venue"], pb["venue"])
                    w.writerow([time.strftime("%H:%M:%S"), block, d.pair, d.venue_a, d.venue_b, d.direction,
                                d.status, d.reason, _f(d.pnl_gross_usd), _f(d.pool_fees_usd), _f(d.gas_usd),
                                _f(d.pnl_net_usd), _f(d.opt_size_x), _f(d.opt_notional_usd), _f(d.max_net_usd),
                                _f(d.breakeven_size_x), _f(d.size_90_x), _f(d.capacity_usd)])
                    if d.status == "A_OBSERVER":
                        poll_obs += 1
                        cov["a_observer_hits"] += 1
                        decisions[rkey] = d
                        # persistance a TAILLE FIXE (figee a la 1re observation)
                        if rkey not in obs:
                            dec_x = pa["dec0"] if d.direction == "A->B" else pb["dec0"]
                            obs[rkey] = {"dir": d.direction, "fixed_wei": int(d.opt_size_x * 10 ** dec_x),
                                         "pa": pa, "pb": pb, "dec_x": dec_x, "net": [], "abstain": 0}
            # mesurer la persistance (taille FIXE) de toutes les routes suivies, ce bloc
            from sim.amm_v2_int import two_pool_profit
            for rkey, o in obs.items():
                pa, pb = (o["pa"], o["pb"]) if o["dir"] == "A->B" else (o["pb"], o["pa"])
                if not (pa["r0"] and pa["r1"] and pb["r0"] and pb["r1"]):
                    o["abstain"] += 1; continue
                s0 = o["pa"]["pair"][0]
                # usd0 du token0 = X : re-derive (WETH->eth_usd, stable->1, sinon via ancre)
                u0 = 1.0 if s0 in STABLES else (eth_usd if s0 == "WETH" else None)
                if u0 is None:
                    o["abstain"] += 1; continue
                prof = two_pool_profit(o["fixed_wei"], pa, pb) / 10 ** o["dec_x"] * u0 - gas_usd
                o["net"].append(prof)
            if poll_obs:
                print(f"[{time.strftime('%H:%M:%S')} blk={block}] {poll_obs} route(s) A_OBSERVER ce bloc")
            f.flush()
            time.sleep(max(0.0, args.interval - (time.time() - t0)))
    except KeyboardInterrupt:
        print("\n(interrompu)")
    finally:
        f.close()

    # --- Verdicts finaux : FORWARD via persistance ---
    forward = []
    for rkey, d in decisions.items():
        o = obs.get(rkey)
        pers = persistence_stats(o["net"], o["fixed_wei"] / 10 ** o["dec_x"], args.persist_min_blocks, o["abstain"]) if o else None
        if pers:
            d2 = assign_forward(d, pers, p_min=args.persist_frac, streak_min=args.persist_streak, cap_min_usd=args.cap_min_usd)
            if d2.status == "CANDIDAT_FORWARD":
                forward.append((rkey, d2, pers))

    print("\n" + "=" * 78)
    print(f"TABLEAU DE DECISION — runner intra-chaine (log -> {log_path})")
    lo = min(blocks_seen) if blocks_seen else 0
    hi = max(blocks_seen) if blocks_seen else 0
    court = "  — fenetre TRES COURTE, ne pas generaliser" if len(blocks_seen) < 30 else ""
    print(f"COUVERTURE : {len(blocks_seen)} blocs ({lo}..{hi}){court}")
    print(f"  pools v2 valides {len(valid)} | pools v3 {len(v3)} | quarantaine {len(quarantined)} | "
          f"paires routables {len(routable)}")
    print(f"  routes evaluees {cov['routes_total']} | A_OBSERVER (hits) {cov['a_observer_hits']} | "
          f"routes distinctes A_OBSERVER {len(decisions)} | CANDIDAT_FORWARD {len(forward)}")
    rejets = {k[6:]: v for k, v in cov.items() if k.startswith("rejet:")}
    if rejets:
        print("  rejets par motif :")
        for r, n in sorted(rejets.items(), key=lambda x: -x[1]):
            print(f"    {n:5d}  {r}")
    if cov.get("abstain_pricing"):
        print(f"  abstentions prix (pas d'ancre USD) : {cov['abstain_pricing']}")
    if forward:
        print("\n  CANDIDAT_FORWARD :")
        for rkey, d, pers in forward:
            print(f"    {d.pair:<12} {d.venue_a}->{d.venue_b} {d.direction} net~${d.pnl_net_usd:.2f} "
                  f"cap~${d.capacity_usd:.0f} persist {pers.frac_positive:.0%}/{pers.longest_streak}blk")
    else:
        print("\n  Aucun CANDIDAT_FORWARD sur la fenetre.")

    verdict = "LEAD" if forward else "NON_CONCLUANT"   # signal forward = PISTE, jamais VALIDE (§2)
    note = ("CALIBRATION du moteur. Resultat vide/court = couverture & liquidite v2 sur Base "
            "(v3 ABSTENU faute de quoter, fenetre courte), PAS une absence d'alpha DeFi. "
            "v3 = grosse part de la liquidite Base -> a instrumenter (quoter) avant toute conclusion.")
    run_dir, m = write_manifest(
        slug="intrachain-base-calibration",
        hypothesis="Le moteur de route intra-chaine surface-t-il des dislocations v2-v2 net-positives et persistantes sur Base (univers de calibration) ?",
        command=f"python scan_dex_intrachain.py --seconds {args.seconds:.0f} --min-usd {args.min_usd:.0f} --gas-units {args.gas_units}",
        period=f"blocs {lo}..{hi} (live {time.strftime('%Y-%m-%d')})",
        sources=["Base RPC public (sim/chain RPC garde, same-block Multicall3)", "factories UniV2/Sushi/BaseSwap/Aerodrome + v3 UniV3/Panc"],
        inputs=[os.path.relpath(UNIVERSE_PATH, HERE)],
        universe=f"{len(dec)} tokens certifies (config v1) ; {len(routable)} paires routables",
        costs=f"frais pool on-chain ; gas {args.gas_units} u @ block ; taille optimale entiere ; marge statut ${args.status_margin:.0f}",
        result=(f"{len(blocks_seen)} blocs ; routes {cov['routes_total']} ; A_OBSERVER {len(decisions)} ; "
                f"FORWARD {len(forward)} ; rejets v3={rejets.get('v3_quoter_non_implemente', 0)}"),
        verdict=verdict,
        notes=note,
    )
    print(f"\nMANIFESTE -> {os.path.relpath(run_dir, HERE)}/  (verdict {verdict})")
    print("Lecture : un tableau vide ici est une mesure de COUVERTURE, pas une conclusion sur l'alpha DeFi.")
    return 0


def _f(x) -> str:
    return "" if x != x else f"{x:.8g}"      # nan -> vide


if __name__ == "__main__":
    raise SystemExit(main())
