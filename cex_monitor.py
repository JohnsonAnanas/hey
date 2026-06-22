#!/usr/bin/env python
"""Moniteur CEX<->CEX CONTINU, filtre-transferts + filtre-PROFONDEUR (ccxt) — capturable REEL.

Lecons accumulees :
- gros gap persistant = souvent VERROUILLE (transferts bloques) -> filtre transferts (withdraw cote
  achat + deposit cote vente).
- gros gap OUVERT = souvent **carnet POUSSIERE** (profondeur de $300 -> rien a extraire) -> le volume
  24h ne suffit PAS ; il faut la PROFONDEUR du carnet maintenant. On calcule le PROFIT EXTRACTIBLE
  en marchant les deux carnets (acheter les asks du moins cher, vendre dans les bids du plus cher,
  net de frais, tant que c'est profitable) -> c'est le vrai "MAV" CEX<->CEX.
- groupement par TICKER = BUG D'IDENTITE (2026-06-22) : 'HYPE' htx/okx 'rendait' ~$20.6M dans les
  DEUX sens a 0.6 bps (3352/3363 lignes >= $1M). Le walk nu se fait avoir. -> on passe par le GARDE
  sim.identity.cex_extractable_guarded : abstention si profitable 2-sens (falsifieur directionnel),
  si divergence d'echelle, ou si magnitude implausible (>$1M sur 20 niveaux). Abstention LOGGEE.

On ne RETIENT qu'un candidat : transferts OUVERTS des deux cotes ET profit extractible GARDE >= --min-usd.
CEX<->CEX non atomique : inventaire des deux cotes ; necessaire pas suffisant. SCREENING de candidats.

Usage : python cex_monitor.py --seconds 3600 --interval 25 --min-vol 1000000 --min-usd 50
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scan_cex import make_exchange, EXCHANGES, TAKER
from sim.identity import cex_extractable_guarded


def transfer_status(ex) -> dict:
    """{coin: (deposit_ok, withdraw_ok)} (bool/None). {} si echec."""
    try:
        cur = ex.fetch_currencies()
    except Exception:
        return {}
    return {coin: (info.get("deposit"), info.get("withdraw")) for coin, info in (cur or {}).items()}


def route_status(transfer: dict, buy_ex: str, sell_ex: str, coin: str) -> str:
    wd = transfer.get(buy_ex, {}).get(coin, (None, None))[1]   # retrait cote achat (le coin s'accumule)
    dp = transfer.get(sell_ex, {}).get(coin, (None, None))[0]  # depot cote vente (le coin s'epuise)
    if wd is False or dp is False:
        return "LOCKED"
    if wd is True and dp is True:
        return "OPEN"
    return "UNKNOWN"


def tickers_usdt(ex) -> dict:
    """{base: (bid, ask, quoteVolume)} pour les paires /USDT. {} si echec."""
    try:
        ts = ex.fetch_tickers()
    except Exception:
        return {}
    out = {}
    for sym, t in ts.items():
        if not sym.endswith("/USDT"):
            continue
        b, a, qv = t.get("bid"), t.get("ask"), t.get("quoteVolume")
        if b and a and a > 0 and b > 0:
            out[sym.split("/")[0]] = (float(b), float(a), float(qv or 0))
    return out


def fetch_book(cli, coin: str, limit: int = 20):
    """(asks, bids) du carnet /USDT d'un client ccxt, ou (None, None) si illisible.
    asks/bids = [(prix, taille), ...]. Le walk + les gardes d'identite/echelle/magnitude vivent dans
    sim.identity.cex_extractable_guarded (PUR, donc testable) — voir tests/test_identity.py."""
    sym = coin + "/USDT"
    try:
        ob = cli.fetch_order_book(sym, limit=limit)
        return ob.get("asks") or [], ob.get("bids") or []
    except Exception:
        return None, None


def abstain_class(reason: str) -> str:
    """Regroupe un motif d'abstention en classe stable (pour la synthese)."""
    if "DEUX sens" in reason:
        return "directionnel (profitable 2 sens)"
    if "divergence" in reason:
        return "divergence d'echelle"
    if "reconcilier" in reason:
        return "magnitude implausible (>$1M/20 niveaux)"
    return "carnet illisible" if "illisible" in reason else "autre"


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="Moniteur CEX<->CEX continu, transferts + profondeur.")
    ap.add_argument("--seconds", type=float, default=3600.0)
    ap.add_argument("--interval", type=float, default=25.0)
    ap.add_argument("--min-vol", type=float, default=1_000_000.0, help="volume 24h min /jambe (pre-filtre)")
    ap.add_argument("--min-usd", type=float, default=50.0, help="profit extractible min (carnet) pour retenir")
    ap.add_argument("--top-depth", type=int, default=10, help="nb de candidats verifies en profondeur /poll")
    args = ap.parse_args()

    print(f"Init clients + statut transferts ({len(EXCHANGES)} exchanges)…")
    clients, transfer = {}, {}
    for name in EXCHANGES:
        try:
            clients[name] = make_exchange(name)
        except Exception as e:
            print(f"  [skip] {name} init: {type(e).__name__}"); continue
        ts = transfer_status(clients[name])
        transfer[name] = ts
        known = sum(1 for v in ts.values() if v[0] is not None or v[1] is not None)
        print(f"  {name:<12} {len(ts):>5} devises ({known} avec statut transfert)")

    out_dir = Path(__file__).resolve().parent / "data" / "logs"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    log_path = out_dir / f"cex_monitor_{stamp}.csv"          # unique/run -> jamais de clobber inter-instances
    abstain_path = out_dir / f"cex_monitor_abstain_{stamp}.csv"   # charte : abstention LOGGEE + motif
    f = open(log_path, "w", newline="", encoding="utf-8")
    w = csv.writer(f)
    w.writerow(["ts", "coin", "buy_ex", "sell_ex", "net_bps", "extract_usd", "transfer_status"])
    af = open(abstain_path, "w", newline="", encoding="utf-8")
    aw = csv.writer(af)
    aw.writerow(["ts", "coin", "ex_a", "ex_b", "reason"])

    hits = defaultdict(lambda: {"n": 0, "max_usd": 0.0, "max_bps": 0.0})
    abstain_by_class = defaultdict(int)
    n_abstain = 0
    n_poll, t_end = 0, time.time() + args.seconds
    print(f"\nMoniteur : {args.seconds:.0f}s, poll {args.interval:.0f}s, volume>=${args.min_vol/1e6:.1f}M, "
          f"profit extractible >= ${args.min_usd:.0f} (profondeur carnet, top {args.top_depth} verifies/poll).\n")
    try:
        while time.time() < t_end:
            t0 = time.time()
            books = {name: tickers_usdt(cli) for name, cli in clients.items()}
            assets = defaultdict(dict)
            for ex, d in books.items():
                for coin, v in d.items():
                    assets[coin][ex] = v
            # 1) pre-candidats par tickers : meilleur sens, net>0, transferts OUVERTS
            pre = []
            for coin, exmap in assets.items():
                legs = [(ex, b, a, vol) for ex, (b, a, vol) in exmap.items() if vol >= args.min_vol]
                if len(legs) < 2:
                    continue
                best = None
                for e1, b1, a1, v1 in legs:
                    for e2, b2, a2, v2 in legs:
                        if e1 == e2:
                            continue
                        net = (b2 * (1 - TAKER) - a1 * (1 + TAKER)) / ((a1 + b2) / 2) * 1e4
                        if best is None or net > best[0]:
                            best = (net, e1, e2)
                if best and best[0] > 0 and route_status(transfer, best[1], best[2], coin) == "OPEN":
                    pre.append((best[0], coin, best[1], best[2]))
            # 2) filtre PROFONDEUR sur les top candidats (cout : 2 carnets chacun)
            pre.sort(reverse=True)
            n_poll += 1
            kept = []
            for net, coin, e1, e2 in pre[:args.top_depth]:
                asks1, bids1 = fetch_book(clients[e1], coin)
                asks2, bids2 = fetch_book(clients[e2], coin)
                if not (asks1 and bids1 and asks2 and bids2):
                    n_abstain += 1; abstain_by_class["carnet illisible"] += 1
                    aw.writerow([time.strftime("%H:%M:%S"), coin, e1, e2, "carnet illisible"]); af.flush()
                    continue
                pr, direction, reason = cex_extractable_guarded(asks1, bids1, asks2, bids2, TAKER, args.min_usd)
                if reason is not None:                       # GARDE : abstention loggee (jamais de chiffre fantome)
                    n_abstain += 1; abstain_by_class[abstain_class(reason)] += 1
                    aw.writerow([time.strftime("%H:%M:%S"), coin, e1, e2, reason]); af.flush()
                    continue
                if pr is None or pr < args.min_usd:
                    continue
                buy, sell = (e1, e2) if direction == "A->B" else (e2, e1)   # le carnet tranche le sens reel
                kept.append((pr, net, coin, buy, sell))
                k = (coin, buy, sell)
                hits[k]["n"] += 1
                hits[k]["max_usd"] = max(hits[k]["max_usd"], pr)
                hits[k]["max_bps"] = max(hits[k]["max_bps"], net)
                w.writerow([time.strftime("%H:%M:%S"), coin, buy, sell, f"{net:.1f}", f"{pr:.0f}", "OPEN"])
            f.flush()
            kept.sort(reverse=True)
            top = "  ".join(f"{c}:${pr:.0f}/{net:.0f}bps({e1}->{e2})" for pr, net, c, e1, e2 in kept[:4])
            print(f"[{time.strftime('%H:%M:%S')}] poll {n_poll} | candidats reels (extractible>=${args.min_usd:.0f}) : "
                  f"{len(kept)}" + (f" | {top}" if top else " (aucun)"))
            time.sleep(max(0.0, args.interval - (time.time() - t0)))
    except KeyboardInterrupt:
        print("\n(interrompu)")
    finally:
        f.close()
        af.close()

    print("\n" + "=" * 80)
    print(f"SYNTHESE — candidats REELS (transferts ouverts + profit extractible GARDE)  (log -> {log_path})")
    ranked = sorted(hits.items(), key=lambda kv: -kv[1]["max_usd"])
    if not ranked:
        print("  Aucun candidat reel sur la fenetre (gaps = verrouilles, carnets trop fins, ou ecartes par le garde).")
    for (coin, e1, e2), s in ranked[:25]:
        print(f"  {coin:<10} {e1:<8}->{e2:<8} vu {s['n']:>3}x | profit max ${s['max_usd']:>7.0f} | gap max {s['max_bps']:.0f} bps")
    if n_abstain:
        print(f"\nABSTENTIONS (garde identite/echelle/magnitude) : {n_abstain}  (log -> {abstain_path})")
        for cls, c in sorted(abstain_by_class.items(), key=lambda kv: -kv[1]):
            print(f"  {c:>5}x  {cls}")
    print("\nLecture : 'profit extractible' = en marchant les carnets, net de frais (taker 2x), APRES le garde")
    print("d'identite (abstention si profitable 2-sens / divergence d'echelle / magnitude implausible).")
    print("Un candidat recurrent a profit non trivial = a verifier en inventaire/latence (forward).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
