#!/usr/bin/env python
"""Collecteur PERSISTANT cross-chain — toujours actif, APPEND-ONLY, robuste (la FONDATION data).

Boucle infinie. Chaque cycle : collecte prix / liquidite / volume de TOUS les tokens vus sur N
chaines (GeckoTerminal) et APPEND chaque observation BRUTE (rien n'est jete -> on pourra re-tester
n'importe quelle hypothese plus tard) + les candidats de dislocation cross-chain. Horodatage UTC
(epoch ms + ISO). APPEND-ONLY (jamais de clobber). Un cycle qui echoue n'arrete PAS la boucle (la
veille / une erreur reseau ne doit jamais tuer la collecte).

Principe : le LIVE stocke d'aujourd'hui = l'HISTORIQUE precis de demain. On accumule le poids
statistique qui nous manquait, en continu, sans rien jeter.

Lancer DETACHE (survit a la fermeture de Claude) via run_collector.ps1. Arret : kill du process.
Usage : python collector.py --interval 1200 --pages 10 --min-liq 100000 --min-vol 20000
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scan_crosschain import CHAINS, collect_chain
from sim.identity import crosschain_identity

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "collected")
OBS_COLS = ["ts_ms", "iso_utc", "chain", "token", "price_usd", "liq_usd", "vol24h_usd", "address"]
# identite par ADRESSE (plus de ticker nu) : on PORTE les adresses des 2 jambes + le verdict
# d'identite. VERIFIED seulement = vrai candidat ; UNVERIFIED/COLLISION_SUSPECT conserves (append-only,
# rien n'est jete) mais LABELLISES -> le mensonge 'meme ticker = meme token' est mort. Cf sim.identity.
CAND_COLS = ["ts_ms", "iso_utc", "token", "lo_chain", "lo_price", "hi_chain", "hi_price",
             "gap_bps", "net_bps", "min_liq_usd", "lo_addr", "hi_addr", "identity"]


def iso(ts_ms: int) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts_ms / 1000.0))


def appender(path: str, cols: list):
    """Ouvre `path` en APPEND. Si le fichier existe avec un header DIFFERENT (schema change), bascule
    sur un sibling versionne `<stem>.vN.csv` -> on ne corrompt jamais un append-only existant. Renvoie
    (f, w, path_reel)."""
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as r:
            first = r.readline().strip()
        if first and first != ",".join(cols):
            stem, ext = os.path.splitext(path)
            n = 2
            while os.path.exists(f"{stem}.v{n}{ext}"):
                n += 1
            path = f"{stem}.v{n}{ext}"
    new = not os.path.exists(path)
    f = open(path, "a", newline="", encoding="utf-8")
    w = csv.writer(f)
    if new:
        w.writerow(cols); f.flush()
    return f, w, path


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="Collecteur persistant cross-chain (append-only).")
    ap.add_argument("--interval", type=float, default=1200.0, help="secondes entre cycles")
    ap.add_argument("--pages", type=int, default=10)
    ap.add_argument("--min-liq", type=float, default=100_000.0)
    ap.add_argument("--min-vol", type=float, default=20_000.0)
    ap.add_argument("--cost-bps", type=float, default=60.0)
    ap.add_argument("--chains", default=",".join(CHAINS))
    args = ap.parse_args()
    chains = [c.strip() for c in args.chains.split(",") if c.strip()]

    os.makedirs(OUT, exist_ok=True)
    obs_f, obs_w, obs_path = appender(os.path.join(OUT, "crosschain_obs.csv"), OBS_COLS)
    cand_f, cand_w, cand_path = appender(os.path.join(OUT, "crosschain_cand.csv"), CAND_COLS)
    hb_path = os.path.join(OUT, "collector.log")

    def log(msg: str):
        line = f"{iso(int(time.time() * 1000))} {msg}"
        print(line, flush=True)
        try:
            with open(hb_path, "a", encoding="utf-8") as h:
                h.write(line + "\n")
        except Exception:
            pass

    log(f"START collector pid={os.getpid()} interval={args.interval:.0f}s pages={args.pages} "
        f"chains={','.join(chains)} -> {OUT} (cand -> {os.path.basename(cand_path)})")
    cycle = 0
    while True:
        cycle += 1
        t0 = time.time()
        try:
            ts = int(t0 * 1000); it = iso(ts)
            per_chain, n_obs = {}, 0
            for net in chains:
                d = collect_chain(net, args.pages, args.min_liq, args.min_vol)
                per_chain[net] = d
                for sym, (price, liq, vol, addr, name) in d.items():
                    obs_w.writerow([ts, it, net, sym, f"{price:.10g}", f"{liq:.2f}", f"{vol:.2f}", addr or ""])
                    n_obs += 1
            obs_f.flush()
            tok = {}
            for net, d in per_chain.items():
                for sym, v in d.items():
                    tok.setdefault(sym, {})[net] = v
            n_cand, n_unverified = 0, 0
            for sym, chmap in tok.items():
                if len(chmap) < 2:
                    continue
                items = [(net, v[0], v[1], v[3]) for net, v in chmap.items()]   # (chain, price, liq, addr)
                hi = max(items, key=lambda x: x[1]); lo = min(items, key=lambda x: x[1])
                if lo[1] <= 0:
                    continue
                gap = (hi[1] - lo[1]) / lo[1] * 1e4
                netb = gap - args.cost_bps
                if not (0 < netb and gap < 2500):
                    continue
                # IDENTITE PAR ADRESSE (plus de ticker nu) : meme contrat cross-EVM = VERIFIED ;
                # adresses differentes hors registre = UNVERIFIED ; projets differents = COLLISION_SUSPECT.
                verdict, _ = crosschain_identity(lo[3], hi[3], lo[0], hi[0])
                cand_w.writerow([ts, it, sym, lo[0], f"{lo[1]:.10g}", hi[0], f"{hi[1]:.10g}",
                                 f"{gap:.1f}", f"{netb:.1f}", f"{min(hi[2], lo[2]):.2f}",
                                 lo[3] or "", hi[3] or "", verdict])
                if verdict == "VERIFIED":
                    n_cand += 1
                else:
                    n_unverified += 1
            cand_f.flush()
            log(f"cycle {cycle} OK: {n_obs} obs, {n_cand} candidats VERIFIED "
                f"(+{n_unverified} non prouves, labellises) ({time.time() - t0:.0f}s)")
        except Exception as e:
            log(f"cycle {cycle} ERREUR (ignoree): {type(e).__name__}: {str(e)[:140]}")
        time.sleep(max(5.0, args.interval - (time.time() - t0)))


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n(arret)")
