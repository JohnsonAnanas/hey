#!/usr/bin/env python
"""Runner PHASE 1 (backfill BORNÉ, certifié) — SOURCE DE DONNÉES = Binance USDⓈ-M / ETHUSDT.

Acquisition BRUTE certifiée de l'historique funding ETHUSDT sur la fenêtre figée, en DEUX requêtes
temporelles FIXES et NON chevauchantes (limite ≤1000 chacune, AUCUNE pagination). Faisabilité prouvée
en Phase 0B (verdict SOURCE_CAPABLE). Ce runner NE conclut RIEN sur la venue de trading ni l'économie.

Autorisation humaine (2026-06-23), STRICTEMENT limitée (Phase 1) :
  - 2 requêtes fixes non chevauchantes :
      W1 : 2025-06-23T00:00:00.000Z → 2025-12-22T23:59:59.999Z
      W2 : 2025-12-23T00:00:00.000Z → 2026-06-23T00:00:00.000Z
  - limite ≤1000 par requête ; AUCUNE pagination, AUCUN backfill au-delà de ces 2 fenêtres ;
  - réponses brutes archivées HORS Git (data/** gitignoré), hashées (sha256), URL/params/timestamp ;
  - manifeste versionné (paramètres, hashes, couverture, gaps, doublons, intervalles, verdict) ;
  - QC obligatoire : timestamps monotones, déduplication, couverture/gaps explicités, intervalles réels
    OBSERVÉS, AUCUNE valeur remplie ni interpolée.
INTERDITS maintenus : aucune agrégation, annualisation, sélection de venue, calibration, règle d'entrée,
PnL, ni conclusion de stratégie. Aucun travail économique ensuite sans nouvelle validation humaine.

Sémantique Binance (confirmée par le brut Phase 0B) :
  - `GET /fapi/v1/fundingRate?symbol=&startTime=&endTime=&limit=` : ms, ordre croissant ;
  - `fundingTime` porte une GIGUE de quelques ms (p.ex. 08:00:00.004) → la QC raisonne en PAS arrondis
    `round(delta / 8h)`, jamais en deltas ms stricts ;
  - `endTime` exact exclut le règlement de borne → la série s'arrête au dernier règlement < endTime.

Verdict de collecte : COLLECTE_COMPLETE / COLLECTE_INCOMPLETE / ABSTENTION.

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
LIMIT = 1000                      # ≤1000 ; chaque fenêtre attend ~547 règlements (< limite)
BASE_MS = 28_800_000             # 8 h — fundingIntervalHours=8 (fundingInfo ETHUSDT, Phase 0B)


def _dt_ms(y, mo, d, h=0, mi=0, s=0, ms=0):
    """ms UTC en arithmétique ENTIÈRE (évite l'imprécision flottante de .timestamp())."""
    whole = int(datetime(y, mo, d, h, mi, s, tzinfo=timezone.utc).timestamp()) * 1000
    return whole + ms


# Fenêtre figée + 2 sous-fenêtres FIXES non chevauchantes (paramètres imposés par l'autorisation).
WIN_START_MS = _dt_ms(2025, 6, 23)                       # 1750636800000  2025-06-23T00:00:00.000Z
WIN_END_MS = _dt_ms(2026, 6, 23)                         # 1782172800000  2026-06-23T00:00:00.000Z
W1_START = _dt_ms(2025, 6, 23)                           # 2025-06-23T00:00:00.000Z
W1_END = _dt_ms(2025, 12, 22, 23, 59, 59, 999)           # 2025-12-22T23:59:59.999Z
W2_START = _dt_ms(2025, 12, 23)                          # 2025-12-23T00:00:00.000Z
W2_END = _dt_ms(2026, 6, 23)                             # 2026-06-23T00:00:00.000Z


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


def fetch(url: str, timeout: int = 30):
    """UNE requête GET (aucun retry, aucune boucle, aucune pagination)."""
    req = urllib.request.Request(url, headers={"User-Agent": "arb-phase1-backfill/1.0"})
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


# ---------------------------------------------------------------------------------------------------
# Fonctions PURES (testables hors réseau) : parsing + QC + verdict.
# ---------------------------------------------------------------------------------------------------
def parse_funding(raw_bytes: bytes) -> list:
    """Parse une réponse fundingRate. AUCUNE valeur synthétisée. Lève ValueError si non-liste/malformé."""
    data = json.loads((raw_bytes or b"").decode("utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"reponse funding non-liste (type={type(data).__name__}) : {str(data)[:200]}")
    out = []
    for i, r in enumerate(data):
        if not isinstance(r, dict) or "fundingTime" not in r:
            raise ValueError(f"enregistrement #{i} malforme : {str(r)[:160]}")
        out.append({"symbol": r.get("symbol"), "fundingTime": int(r["fundingTime"]),
                    "fundingRate": r.get("fundingRate"), "markPrice": r.get("markPrice")})
    return out


def qc_series(windows_records: list, win_start_ms: int, win_end_ms: int, base_ms: int) -> dict:
    """QC PURE sur les enregistrements bruts (par fenêtre). Aucune I/O, aucune interpolation.

    - ordre brut par fenêtre + ordre de couture ; fusion ; déduplication par fundingTime EXACT ;
    - monotonie stricte ; intervalles réels OBSERVÉS (histogramme heures + pas) ; gaps (pas ≥2) ;
    - bornes de fenêtre atteintes ; jamais de valeur remplie.
    """
    raw_ascending = []
    for recs in windows_records:
        ts = [r["fundingTime"] for r in recs]
        raw_ascending.append(all(ts[i] < ts[i + 1] for i in range(len(ts) - 1)))
    seam_ordered = True
    for a, b in zip(windows_records, windows_records[1:]):
        if a and b and not (max(x["fundingTime"] for x in a) < min(x["fundingTime"] for x in b)):
            seam_ordered = False

    merged = sorted((r for recs in windows_records for r in recs), key=lambda r: r["fundingTime"])
    deduped, seen, dup_times = [], set(), []
    for r in merged:
        ft = r["fundingTime"]
        if ft in seen:
            dup_times.append(ft)
            continue
        seen.add(ft)
        deduped.append(r)
    times = [r["fundingTime"] for r in deduped]

    qc = {
        "records_raw_total": sum(len(w) for w in windows_records),
        "raw_ascending_per_window": raw_ascending,
        "seam_ordered": seam_ordered,
        "duplicates_removed": len(dup_times),
        "duplicate_fundingTimes_utc": sorted({ms_to_utc(t) for t in dup_times}),
        "records_after_dedup": len(times),
        "base_interval_ms": base_ms,
        "nominal_settlements_half_open": round((win_end_ms - win_start_ms) / base_ms),
        "no_interpolation": True,
    }
    if not times:
        qc.update({"monotonic_strict": False, "first_settlement_utc": None, "last_settlement_utc": None,
                   "reaches_window_start": False, "reaches_window_end": False, "gaps": [], "gaps_count": 0,
                   "missing_settlements_total": 0, "sub_interval_anomalies": [],
                   "observed_interval_hours_histogram": {}, "nstep_histogram": {},
                   "raw_delta_ms_min": None, "raw_delta_ms_max": None, "contiguous": False})
        return qc

    monotonic = all(times[i] < times[i + 1] for i in range(len(times) - 1))
    deltas = [times[i + 1] - times[i] for i in range(len(times) - 1)]
    gaps, subints, hist_hours, hist_nstep = [], [], {}, {}
    for i, d in enumerate(deltas):
        nstep = round(d / base_ms)
        h = round(d / 3_600_000)
        hist_hours[h] = hist_hours.get(h, 0) + 1
        hist_nstep[nstep] = hist_nstep.get(nstep, 0) + 1
        if nstep >= 2:
            gaps.append({"prev_utc": ms_to_utc(times[i]), "next_utc": ms_to_utc(times[i + 1]),
                         "delta_ms": d, "delta_hours": round(d / 3_600_000, 3),
                         "missing_settlements": nstep - 1})
        elif nstep == 0:
            subints.append({"prev_utc": ms_to_utc(times[i]), "next_utc": ms_to_utc(times[i + 1]),
                            "delta_ms": d, "delta_hours": round(d / 3_600_000, 3)})
    first_ft, last_ft = times[0], times[-1]
    reaches_start = 0 <= (first_ft - win_start_ms) < base_ms
    reaches_end = (0 <= (win_end_ms - last_ft) < 1.5 * base_ms) or (0 <= (last_ft - win_end_ms) < base_ms)
    qc.update({
        "monotonic_strict": monotonic,
        "first_settlement_utc": ms_to_utc(first_ft),
        "last_settlement_utc": ms_to_utc(last_ft),
        "first_offset_ms_from_window_start": first_ft - win_start_ms,
        "last_offset_ms_from_window_end": last_ft - win_end_ms,
        "reaches_window_start": bool(reaches_start),
        "reaches_window_end": bool(reaches_end),
        "gaps": gaps, "gaps_count": len(gaps),
        "missing_settlements_total": sum(g["missing_settlements"] for g in gaps),
        "sub_interval_anomalies": subints,
        "observed_interval_hours_histogram": {str(k): v for k, v in sorted(hist_hours.items())},
        "nstep_histogram": {str(k): v for k, v in sorted(hist_nstep.items())},
        "raw_delta_ms_min": min(deltas), "raw_delta_ms_max": max(deltas),
        "contiguous": len(gaps) == 0,
    })
    return qc


def decide_verdict(qc: dict, all_requests_ok: bool, any_truncation: bool) -> str:
    """COLLECTE_COMPLETE / COLLECTE_INCOMPLETE / ABSTENTION (collecte uniquement, zéro économie)."""
    if not all_requests_ok or qc["records_after_dedup"] == 0:
        return "ABSTENTION"
    if any_truncation:
        return "COLLECTE_INCOMPLETE"     # pagination interdite -> on ne peut garantir l'exhaustivité
    if (qc["monotonic_strict"] and qc["reaches_window_start"] and qc["reaches_window_end"]
            and qc["gaps_count"] == 0 and not qc["sub_interval_anomalies"]):
        return "COLLECTE_COMPLETE"
    return "COLLECTE_INCOMPLETE"


# ---------------------------------------------------------------------------------------------------
def main() -> int:
    prov = provenance()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    raw_dir = os.path.join(HERE, "data", "raw", "funding", "binance", "phase1")  # HORS Git
    run_dir = os.path.join(HERE, "runs", f"{stamp}_phase1-binance-ethusdt-backfill")
    os.makedirs(raw_dir, exist_ok=True)
    os.makedirs(run_dir, exist_ok=True)

    windows = [
        {"name": "backfill_W1", "start": W1_START, "end": W1_END},
        {"name": "backfill_W2", "start": W2_START, "end": W2_END},
    ]
    receipts, per_window_records, abstentions = [], [], []
    all_ok, any_trunc = True, False
    for w in windows:
        url = (f"{BASE}/fapi/v1/fundingRate?symbol={SYMBOL}"
               f"&startTime={w['start']}&endTime={w['end']}&limit={LIMIT}")
        req_utc = now_utc()
        status, raw, err = fetch(url)                       # UNE requête, sans retry/pagination
        path = os.path.join(raw_dir, f"{w['name']}_{stamp}.json")
        with open(path, "wb") as f:
            f.write(raw or b"")
        recs = []
        if err or status != 200:
            all_ok = False
            abstentions.append(f"{w['name']}: {err or ('HTTP ' + str(status))}")
        else:
            try:
                recs = parse_funding(raw)
            except Exception as e:
                all_ok = False
                abstentions.append(f"{w['name']}: parse impossible ({e})")
        trunc = len(recs) >= LIMIT
        if trunc:
            any_trunc = True
            abstentions.append(f"{w['name']}: {len(recs)} >= limite {LIMIT} -> troncature possible "
                               f"(pagination INTERDITE)")
        per_window_records.append(recs)
        fts = sorted(r["fundingTime"] for r in recs)
        receipts.append({
            "name": w["name"], "url": url, "request_utc": req_utc, "http_status": status,
            "startTime": w["start"], "startTime_utc": ms_to_utc(w["start"]),
            "endTime": w["end"], "endTime_utc": ms_to_utc(w["end"]), "limit": LIMIT,
            "bytes": len(raw or b""), "sha256": hashlib.sha256(raw or b"").hexdigest(),
            "raw_path": os.path.relpath(path, HERE).replace("\\", "/"),
            "records_returned": len(recs),
            "first_fundingTime_utc": ms_to_utc(fts[0]) if fts else None,
            "last_fundingTime_utc": ms_to_utc(fts[-1]) if fts else None,
            "truncation_suspected": trunc,
        })

    non_overlap = {"w1_end_ms": W1_END, "w1_end_utc_ms": "2025-12-22T23:59:59.999Z",
                   "w2_start_ms": W2_START, "w2_start_utc": ms_to_utc(W2_START),
                   "delta_ms_between_windows": W2_START - W1_END, "overlap": W2_START <= W1_END}
    qc = qc_series(per_window_records, WIN_START_MS, WIN_END_MS, BASE_MS)
    verdict = decide_verdict(qc, all_ok, any_trunc)

    manifest = {
        "phase": "PHASE1", "source_donnees": SOURCE, "symbol": SYMBOL,
        "window": {"start_utc": ms_to_utc(WIN_START_MS), "end_utc": ms_to_utc(WIN_END_MS)},
        "created_utc": now_utc(), **prov,
        "authorization": ("Phase 1 autorisee (2026-06-23) : backfill Binance/ETHUSDT, 2 requetes "
                          "temporelles FIXES non chevauchantes, limite<=1000, AUCUNE pagination/backfill "
                          "au-dela. INTERDITS : agregation, annualisation, selection de venue, "
                          "calibration, regle d'entree, PnL, conclusion de strategie."),
        "requests": receipts, "non_overlap_check": non_overlap, "qc": qc,
        "verdict": verdict, "abstentions": abstentions,
        "note": ("Serie BRUTE certifiee (timestamps/couverture) UNIQUEMENT. Bruts hors Git, hashes. "
                 "AUCUNE agregation/annualisation/PnL/calibration/choix de venue. Aucun travail "
                 "economique sans nouvelle validation humaine."),
    }
    with open(os.path.join(run_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    lines = [f"# Rapport PHASE 1 — série certifiée {SOURCE} / {SYMBOL}", "",
             f"- **Verdict de collecte : {verdict}**",
             f"- Fenêtre figée : {manifest['window']['start_utc']} → {manifest['window']['end_utc']}",
             f"- Provenance : git `{prov['git_hash'][:10]}` ; code_versioned={prov['code_versioned']} ; "
             f"git_dirty={prov['git_dirty']} ; runner_sha256 `{prov['runner_sha256'][:16]}…`", "",
             "## Couverture & QC", "```json", json.dumps(qc, ensure_ascii=False, indent=2), "```",
             "## Requêtes (2 fenêtres fixes non chevauchantes) — reçus bruts hors Git, hashés"]
    for r in receipts:
        lines.append(f"- `{r['name']}` — {r['startTime_utc']} → {r['endTime_utc']} — HTTP "
                     f"{r['http_status']} — {r['records_returned']} règlements — {r['bytes']} o — sha256 "
                     f"`{r['sha256'][:16]}…`")
        lines.append(f"  - premier={r['first_fundingTime_utc']} dernier={r['last_fundingTime_utc']} "
                     f"troncature={r['truncation_suspected']}")
        lines.append(f"  - `{r['raw_path']}`")
    lines += ["", f"- Non-chevauchement : delta W2.start − W1.end = "
              f"{non_overlap['delta_ms_between_windows']} ms (overlap={non_overlap['overlap']})"]
    lines += ["", "## Abstentions / motifs"] + ([f"- {a}" for a in abstentions] or ["- (aucune)"])
    lines += ["", "> Série **brute** certifiée (timestamps/couverture) **uniquement** — **aucune** "
              "agrégation, annualisation, PnL, calibration ni choix de venue. **Aucun travail économique "
              "sans nouvelle validation humaine.**"]
    with open(os.path.join(run_dir, "report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print(json.dumps({"verdict": verdict, "provenance": prov,
                      "run_dir": os.path.relpath(run_dir, HERE).replace("\\", "/"),
                      "records_after_dedup": qc["records_after_dedup"],
                      "first": qc.get("first_settlement_utc"), "last": qc.get("last_settlement_utc"),
                      "gaps_count": qc["gaps_count"], "duplicates_removed": qc["duplicates_removed"],
                      "contiguous": qc.get("contiguous"), "abstentions": abstentions},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
