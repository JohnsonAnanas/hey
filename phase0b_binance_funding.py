#!/usr/bin/env python
"""Runner PHASE 0B (one-shot, BORNÉ) — SOURCE DE DONNÉES = Binance USDⓈ-M / ETHUSDT.
PAS un collecteur, PAS un backfill. Pivot d'ACQUISITION (faisabilité de données) ; ne conclut RIEN sur
la venue de trading future. OKX conservé comme source NON CONCLUANTE (non rejetée).

Autorisation humaine (2026-06-23), STRICTEMENT limitée (Phase 0B) :
  - métadonnées Binance NÉCESSAIRES + UNE seule sonde historique funding `startTime/endTime` autour du
    début gelé de fenêtre, limite faible, SANS pagination ;
  - AUCUNE pagination, AUCUN backfill, AUCUNE agrégation, AUCUN PnL, AUCUN choix de stratégie ;
  - réponses brutes archivées HORS Git (data/** gitignoré), hashées (sha256), URL/params/timestamp ;
  - manifeste + rapport.
Réf : docs/mechanisms/funding_acquisition_spec.md — Annexe A. Phase 1 (backfill) reste INTERDITE.

Avantage Binance : `GET /fapi/v1/fundingRate` pagine par `startTime`/`endTime` (ms, INCLUSIFS, ordre
croissant) — sémantique NON ambiguë (≠ before/after OKX). Donc une réponse HTTP 200 vide à une fenêtre
[start, start+2j] signifie SANS ambiguïté : aucun règlement retenu dans cette fenêtre.

Critère A.4 unique : des règlements ETHUSDT proches du 2025-06-23 doivent être retournés -> SOURCE_CAPABLE.
Sinon -> SOURCE_NON_CAPABLE pour cette fenêtre. Échec d'appel -> NON_CONCLUANT.

Gouvernance : provenance honnête — un run ne peut PAS déclarer git_dirty=false si son code n'est pas
versionné (code_versioned/runner_sha256 consignés ; git_dirty forcé true si non versionné).
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import urllib.error
import urllib.request
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
SOURCE = "Binance-USDM"
SYMBOL = "ETHUSDT"
BASE = "https://fapi.binance.com"
WIN_START_MS = 1750636800000  # 2025-06-23T00:00:00Z
WIN_END_MS = 1782172800000    # 2026-06-23T00:00:00Z
DAY = 86_400_000
PROBE_START = WIN_START_MS              # 2025-06-23T00:00:00Z
PROBE_END = WIN_START_MS + 2 * DAY      # 2025-06-25T00:00:00Z  (fenêtre bornée autour du début)


def _git(*a: str) -> str:
    try:
        return subprocess.run(["git", "-C", HERE, *a], capture_output=True, text=True).stdout.strip()
    except Exception:
        return ""


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ms_to_utc(ms) -> str:
    return datetime.fromtimestamp(int(ms) / 1000, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def provenance() -> dict:
    rel = os.path.relpath(os.path.abspath(__file__), HERE).replace("\\", "/")
    with open(os.path.abspath(__file__), "rb") as f:
        runner_sha = hashlib.sha256(f.read()).hexdigest()
    tracked = bool(_git("ls-files", "--", rel))
    file_status = _git("status", "--porcelain", "--", rel)
    code_versioned = tracked and not file_status
    tracked_dirty = bool(_git("status", "--porcelain", "--untracked-files=no"))
    return {"git_hash": _git("rev-parse", "HEAD") or "UNVERSIONED",
            "runner_path": rel, "runner_sha256": runner_sha,
            "runner_tracked": tracked, "runner_status": file_status or "clean",
            "code_versioned": bool(code_versioned),
            "git_dirty": bool(tracked_dirty or not code_versioned)}


def fetch(url: str, timeout: int = 25):
    """UNE requête GET (aucun retry, aucune boucle)."""
    req = urllib.request.Request(url, headers={"User-Agent": "arb-phase0b-recon/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(), None
    except urllib.error.HTTPError as e:
        try:
            body = e.read()
        except Exception:
            body = b""
        return e.code, body, f"HTTPError {e.code}"
    except Exception as e:
        return None, b"", f"{type(e).__name__}: {e}"


def main() -> int:
    prov = provenance()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    raw_dir = os.path.join(HERE, "data", "raw", "funding", "binance", "phase0b")  # HORS Git
    run_dir = os.path.join(HERE, "runs", f"{stamp}_phase0b-binance-ethusdt")
    os.makedirs(raw_dir, exist_ok=True)
    os.makedirs(run_dir, exist_ok=True)

    # 2 appels BORNÉS : 1 métadonnées funding (A.3) + 1 sonde historique (A.4). AUCUNE pagination.
    calls = [
        ("funding_info_A3", f"{BASE}/fapi/v1/fundingInfo"),
        ("funding_history_probe_A4",
         f"{BASE}/fapi/v1/fundingRate?symbol={SYMBOL}&startTime={PROBE_START}&endTime={PROBE_END}&limit=10"),
    ]
    receipts, abstentions, parsed = [], [], {}
    for name, url in calls:
        req_utc = now_utc()
        status, raw, err = fetch(url)
        path = os.path.join(raw_dir, f"{name}_{stamp}.json")
        with open(path, "wb") as f:
            f.write(raw or b"")
        receipts.append({"name": name, "url": url, "request_utc": req_utc, "http_status": status,
                         "bytes": len(raw or b""), "sha256": hashlib.sha256(raw or b"").hexdigest(),
                         "raw_path": os.path.relpath(path, HERE).replace("\\", "/")})
        if err or status != 200:
            abstentions.append(f"{name}: {err or ('HTTP ' + str(status))}")
            continue
        try:
            parsed[name] = json.loads((raw or b"").decode("utf-8"))
        except Exception as e:
            abstentions.append(f"{name}: JSON illisible ({e})")

    # A.3 : fundingInfo -> entrée du symbole (cap/floor/intervalle par symbole)
    a3 = {}
    fi = parsed.get("funding_info_A3")
    if isinstance(fi, list):
        row = next((x for x in fi if x.get("symbol") == SYMBOL), None)
        if row:
            a3["funding_info"] = {k: row.get(k) for k in
                                  ("symbol", "adjustedFundingRateCap", "adjustedFundingRateFloor",
                                   "fundingIntervalHours", "disclaimer")}
        else:
            abstentions.append(f"funding_info_A3: symbole {SYMBOL} absent de la réponse")

    # A.4 : sonde startTime/endTime (NON ambiguë). HTTP 200 + non vide => règlements présents dans [start, +2j].
    a4 = {"source": "Binance GET /fapi/v1/fundingRate",
          "probe_param": f"symbol={SYMBOL}&startTime={PROBE_START}({ms_to_utc(PROBE_START)})"
                         f"&endTime={PROBE_END}({ms_to_utc(PROBE_END)})&limit=10",
          "window_start_utc": ms_to_utc(WIN_START_MS), "window_end_utc": ms_to_utc(WIN_END_MS)}
    hist = parsed.get("funding_history_probe_A4")
    if isinstance(hist, list):
        times = sorted(int(r["fundingTime"]) for r in hist if r.get("fundingTime"))
        a4["records_returned"] = len(hist)
        a4["fundingTimes_utc"] = [ms_to_utc(t) for t in times]
        a4["covers_window_start"] = len(hist) > 0  # startTime/endTime garantissent la fenêtre [start, +2j]
    elif "funding_history_probe_A4" in parsed:
        a4["records_returned"] = 0
        a4["covers_window_start"] = False

    # Verdict (critère A.4 unique ; aucune agrégation/calcul de strategie)
    a3_ok = bool(a3.get("funding_info"))
    if "covers_window_start" not in a4:   # appel A.4 en échec
        verdict = "NON_CONCLUANT"
    elif a3_ok and a4["covers_window_start"]:
        verdict = "SOURCE_CAPABLE"
    elif a3_ok and not a4["covers_window_start"]:
        verdict = "SOURCE_NON_CAPABLE"
    else:
        verdict = "NON_CONCLUANT"

    manifest = {
        "phase": "PHASE0B", "source_donnees": SOURCE, "symbol": SYMBOL,
        "window": {"start_utc": ms_to_utc(WIN_START_MS), "end_utc": ms_to_utc(WIN_END_MS)},
        "created_utc": now_utc(), **prov,
        "authorization": ("Phase 0B autorisee (2026-06-23) : Binance/ETHUSDT, public, borne ; metadonnees "
                          "necessaires + UNE sonde historique startTime/endTime ; AUCUNE pagination/"
                          "backfill/agregation/PnL/choix de strategie. Pivot DONNEES, pas venue de trading."),
        "calls_count": len(calls), "receipts": receipts,
        "a3_params_recus": a3, "a4_probe": a4,
        "critere_a4": "des reglements ETHUSDT proches du 2025-06-23 doivent etre retournes ; sinon NON CAPABLE",
        "verdict": verdict, "abstentions": abstentions,
        "note": ("Recus de validation parametres/capacite UNIQUEMENT. PAS une serie certifiee, non agrege, "
                 "ni calibration ni test, ni choix de venue de trading. OKX conserve NON CONCLUANT (non "
                 "rejete). Phase 1 (backfill) INTERDITE sans nouvelle validation humaine."),
    }
    with open(os.path.join(run_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    lines = [f"# Rapport PHASE 0B — source données {SOURCE} / {SYMBOL}", "",
             f"- **Verdict : {verdict}**",
             f"- Provenance : git `{prov['git_hash'][:10]}` ; code_versioned={prov['code_versioned']} ; "
             f"git_dirty={prov['git_dirty']} ; runner_sha256 `{prov['runner_sha256'][:16]}…`",
             f"- Fenêtre figée : {manifest['window']['start_utc']} → {manifest['window']['end_utc']}",
             "", "## A.3 — métadonnées reçues (fundingInfo ETHUSDT)", "```json",
             json.dumps(a3, ensure_ascii=False, indent=2), "```",
             "## A.4 — sonde historique (startTime/endTime, NON ambiguë)", "```json",
             json.dumps(a4, ensure_ascii=False, indent=2), "```",
             "## Reçus (bruts hors Git, hashés)"]
    for r in receipts:
        lines.append(f"- `{r['name']}` — HTTP {r['http_status']} — {r['bytes']} o — sha256 "
                     f"`{r['sha256'][:16]}…` — `{r['raw_path']}`")
        lines.append(f"  - {r['url']}")
    lines += ["", "## Abstentions / motifs"] + ([f"- {a}" for a in abstentions] or ["- (aucune)"])
    lines += ["", "> Reçus de validation params/capacité **uniquement** — pas une série certifiée, non "
              "agrégés, ni calibration ni test, **ni choix de venue de trading**. **Phase 1 INTERDITE.**"]
    with open(os.path.join(run_dir, "report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print(json.dumps({"verdict": verdict, "provenance": prov,
                      "run_dir": os.path.relpath(run_dir, HERE).replace("\\", "/"),
                      "a3": a3, "a4": a4, "abstentions": abstentions}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
