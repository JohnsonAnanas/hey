#!/usr/bin/env python
"""MERIDIAN — backend du moniteur live d'arbitrage DEX<->CEX (FastAPI, LECTURE SEULE).

Lit le CSV du collecteur (data/logs/dex_cex_multi.csv), en derive l'etat par actif/venue, les
series, les stats de session et les "moments forts", et sert la page + /api/state (JSON).
Le front interroge /api/state toutes les ~2,5 s. Re-parse uniquement quand le CSV a change.

Lancer : python dashboard/server.py   (puis http://127.0.0.1:8765)
"""
from __future__ import annotations

import csv
import time
from collections import defaultdict
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

HERE = Path(__file__).resolve().parent
CSV = HERE.parent / "data" / "logs" / "dex_cex_multi.csv"
INDEX = HERE / "index.html"
FEE_BPS = {"UniV3-5": 5.0, "UniV3-30": 30.0, "Aerodrome": 30.0}   # frais one-side par venue (affichage)
HOT = -5.0      # seuil "chaud" : a moins de 5 bps du bord
ACTIONABLE = 0.0

app = FastAPI()
_cache: dict = {"sig": None, "state": None}


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _i(x):
    try:
        return int(x)
    except (TypeError, ValueError):
        return None


def build_events(per: dict, meta: dict) -> list:
    """Detecte les moments forts depuis les series best-par-bloc de chaque actif."""
    ev = []
    for a, bm in per.items():
        blocks = sorted(bm)
        run_max = -1e9
        hot_seen = live_seen = False
        prev = None
        for b in blocks:
            vmap = bm[b]
            if not vmap:
                continue
            net = max(vmap.values())
            t = meta.get(b, {}).get("wall", "")
            if net > run_max + 1.5 and net > -40:                       # nouveau plus proche du bord
                run_max = net
                ev.append((b, t, a, "peak", f"{a} au plus proche : {net:+.1f} bps"))
            else:
                run_max = max(run_max, net)
            if net > ACTIONABLE and not live_seen:
                live_seen = True
                ev.append((b, t, a, "live", f"ACTIONNABLE — {a} {net:+.1f} bps a franchi le seuil"))
            elif net > HOT and not hot_seen:
                hot_seen = True
                ev.append((b, t, a, "hot", f"{a} s'approche du bord ({net:+.1f} bps)"))
            if prev is not None and abs(net - prev) > 8.0:              # mouvement brusque = volatilite
                ev.append((b, t, a, "vol", f"{a} bouge vite : {net - prev:+.1f} bps en 1 bloc"))
            prev = net
    # evenements d'integrite (abstentions de bloc)
    for b, m in meta.items():
        if m.get("abstain"):
            ev.append((b, m.get("wall", ""), "", "guard", f"integrite : {m['abstain']}"))
    ev.sort(key=lambda e: (e[0] if e[0] else 0), reverse=True)
    return [{"block": b, "ts": t, "asset": a, "kind": k, "text": txt} for (b, t, a, k, txt) in ev[:26]]


def build_state() -> dict:
    if not CSV.exists():
        return {"top": None, "assets": [], "session": None, "events": [], "waiting": True}
    rows = list(csv.DictReader(open(CSV, encoding="utf-8", newline="")))
    per: dict = defaultdict(lambda: defaultdict(dict))   # asset -> block -> {venue: net}
    cfg: dict = {}
    meta: dict = {}
    n_abstain = 0
    for r in rows:
        b = _i(r.get("block"))
        if b is None:
            continue
        meta.setdefault(b, {"ts": _i(r.get("block_ts")), "fresh_ok": r.get("fresh_ok") == "True",
                            "n_sources": _i(r.get("n_sources")), "wall": r.get("ts")})
        a = r.get("asset")
        if not a:
            continue
        cfg.setdefault(a, {"binance": r.get("binance_sym", ""), "basis": r.get("basis_usdt") == "True"})
        status = r.get("status", "") or ""
        if status.startswith("ABSTAIN"):
            n_abstain += 1
        net = _f(r.get("net_bps"))
        if net is not None and r.get("venue"):
            per[a][b][r["venue"]] = net
    blocks = sorted(meta)
    if not blocks:
        return {"top": None, "assets": [], "session": None, "events": [], "waiting": True}
    last_b = blocks[-1]

    assets_out, best_overall, persist_max = [], None, 0
    total_pts, act_pts = 0, 0
    for a, bm in per.items():
        ablocks = sorted(bm)
        series, run, mx = [], 0, 0
        for b in ablocks:
            vmap = bm[b]
            if not vmap:
                continue
            bv = max(vmap, key=vmap.get)
            net = vmap[bv]
            series.append({"block": b, "net": round(net, 2), "venue": bv})
            best_overall = net if best_overall is None else max(best_overall, net)
            total_pts += 1
            act_pts += (net > 0)
            run = run + 1 if net > 0 else 0
            mx = max(mx, run)
        persist_max = max(persist_max, mx)
        latest = ablocks[-1]
        venues = [{"venue": v, "net": round(n, 2), "fee_bps": FEE_BPS.get(v)}
                  for v, n in sorted(bm[latest].items(), key=lambda kv: -kv[1])]
        assets_out.append({
            "sym": a, "binance": cfg[a]["binance"], "basis": cfg[a]["basis"],
            "current": series[-1] if series else None,
            "series": [s["net"] for s in series][-160:],
            "venues": venues,
        })
    assets_out.sort(key=lambda x: x["current"]["net"] if x["current"] else -1e9, reverse=True)

    top = {"block": last_b, "block_ts": meta[last_b]["ts"],
           "fresh_ok": meta[last_b]["fresh_ok"], "n_sources": meta[last_b]["n_sources"]}
    session = {"n_blocks": len(blocks), "pct_actionable": round(100 * act_pts / total_pts, 1) if total_pts else 0.0,
               "best_net": round(best_overall, 2) if best_overall is not None else None,
               "persist_max": persist_max, "n_abstain": n_abstain}
    return {"top": top, "assets": assets_out, "session": session,
            "events": build_events(per, meta), "waiting": False}


def get_state() -> dict:
    if not CSV.exists():
        return build_state()
    st = CSV.stat()
    sig = (st.st_size, st.st_mtime_ns)
    if _cache["sig"] != sig:
        _cache["sig"], _cache["state"] = sig, build_state()
    return _cache["state"]


@app.get("/", response_class=HTMLResponse)
def index():
    return INDEX.read_text(encoding="utf-8")


@app.get("/api/state")
def api_state():
    s = dict(get_state())
    if s.get("top") and s["top"].get("block_ts"):
        s["top"]["block_age_s"] = max(0, int(time.time()) - s["top"]["block_ts"])
    s["server_now"] = int(time.time())
    return JSONResponse(s)


if __name__ == "__main__":
    import uvicorn
    print("MERIDIAN -> http://127.0.0.1:8765")
    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="warning")
