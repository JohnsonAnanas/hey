#!/usr/bin/env python
"""Runner PHASE 0 (one-shot, BORNÉ) — OKX / ETH-USDT-SWAP. PAS un collecteur, PAS un backfill.

Autorisation humaine (2026-06-23), STRICTEMENT limitée :
  - appels PUBLICS strictement nécessaires aux métadonnées A.3 + à la sonde de capacité A.4 ;
  - AUCUN backfill paginé, AUCUNE boucle, AUCUN agrégat, AUCUNE annualisation, AUCUN PnL ;
  - au plus 1 requête bornée par source candidate A.4 + les requêtes de métadonnées requises ;
  - réponses brutes archivées HORS Git (data/** est gitignoré), hashées (sha256), avec URL/params/ts ;
  - un manifeste Phase 0 + un rapport (verdict PHASE0_PASS / PHASE0_PARTIEL / PHASE0_REJETE).
Réf : docs/mechanisms/funding_acquisition_spec.md — Annexe A (A.3/A.4/A.5).

Reçus de validation paramètres/capacité UNIQUEMENT : PAS une série certifiée, non agrégés, ni
calibration ni test. Phase 1 (backfill) INTERDITE sans nouvelle validation humaine.

GOUVERNANCE (corrections) :
- Provenance honnête : un run NE PEUT JAMAIS déclarer git_dirty=false si son propre code n'est pas
  versionné (suivi + propre). `code_versioned` et `runner_sha256` sont consignés ; git_dirty est forcé
  à true si le runner n'est pas versionné.
- Sémantique de pagination OKX `before`/`after` : NON encore établie de façon certaine. Le résumé de
  doc obtenu en reconnaissance était AMBIGU. **Tant que `SEMANTICS_CONFIRMED` est False, un lot vide
  n'est PAS interprété** (ni "couvre" ni "rétention insuffisante") -> A.4 = non concluant.
  Convention OKX usuelle (À CONFIRMER depuis docs-v5, section "Get funding rate history") :
    `after`=ts  -> enregistrements PLUS ANCIENS que ts ;
    `before`=ts -> enregistrements PLUS RÉCENTS que ts ; tri décroissant ; limit max 100.
  Sonde CORRECTE (une fois la sémantique confirmée), bornée, 1 requête : paramètre "plus ancien que"
  ancré à (début_fenêtre + 1 intervalle), limit petit -> non vide avec fundingTime ~ début => la
  source couvre le début ; vide => le plus ancien retenu est PLUS RÉCENT que le début (NE conclure
  qu'après confirmation de la sémantique).
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
VENUE = "OKX"
INST = "ETH-USDT-SWAP"
BASE = "https://www.okx.com"
WIN_START_MS = 1750636800000  # 2025-06-23T00:00:00Z
WIN_END_MS = 1782172800000    # 2026-06-23T00:00:00Z
DAY = 86_400_000

# Passe à True UNIQUEMENT après avoir établi la sémantique exacte de before/after depuis la doc
# officielle docs-v5. Sinon, un lot vide de la sonde A.4 reste NON CONCLUANT.
SEMANTICS_CONFIRMED = False


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
    """Provenance HONNÊTE : un run ne peut PAS se déclarer propre si son propre code n'est pas versionné."""
    rel = os.path.relpath(os.path.abspath(__file__), HERE).replace("\\", "/")
    with open(os.path.abspath(__file__), "rb") as f:
        runner_sha = hashlib.sha256(f.read()).hexdigest()
    tracked = bool(_git("ls-files", "--", rel))
    file_status = _git("status", "--porcelain", "--", rel)   # '' propre ; '??' non suivi ; ' M' modifié
    code_versioned = tracked and not file_status
    tracked_dirty = bool(_git("status", "--porcelain", "--untracked-files=no"))
    return {
        "git_hash": _git("rev-parse", "HEAD") or "UNVERSIONED",
        "runner_path": rel, "runner_sha256": runner_sha,
        "runner_tracked": tracked, "runner_status": file_status or "clean",
        "code_versioned": bool(code_versioned),
        # RÈGLE : git_dirty est vrai si modifs suivies OU si le code du runner n'est pas versionné.
        "git_dirty": bool(tracked_dirty or not code_versioned),
    }


def fetch(url: str, timeout: int = 25):
    """UNE requête GET (aucun retry, aucune boucle). -> (status, raw_bytes, err)."""
    req = urllib.request.Request(url, headers={"User-Agent": "arb-phase0-recon/1.0"})
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
    raw_dir = os.path.join(HERE, "data", "raw", "funding", "okx", "phase0")  # HORS Git (data/** ignoré)
    run_dir = os.path.join(HERE, "runs", f"{stamp}_phase0-okx-eth-usdt-swap")
    os.makedirs(raw_dir, exist_ok=True)
    os.makedirs(run_dir, exist_ok=True)

    # --- 3 appels BORNÉS : 2 métadonnées (A.3) + 1 sonde A.4 REST. AUCUNE pagination. ---
    # NB sonde A.4 : paramètre "plus ancien que" = `after` selon la convention OKX usuelle, À CONFIRMER
    # (cf SEMANTICS_CONFIRMED). Tant que non confirmé, le résultat n'est PAS interprété.
    calls = [
        ("instruments_A3", f"{BASE}/api/v5/public/instruments?instType=SWAP&instId={INST}"),
        ("funding_rate_A3", f"{BASE}/api/v5/public/funding-rate?instId={INST}"),
        ("funding_history_probe_A4_REST",
         f"{BASE}/api/v5/public/funding-rate-history?instId={INST}&after={WIN_START_MS + DAY}&limit=10"),
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
            j = json.loads((raw or b"").decode("utf-8"))
        except Exception as e:
            abstentions.append(f"{name}: JSON illisible ({e})")
            continue
        if str(j.get("code")) != "0":
            abstentions.append(f"{name}: OKX code={j.get('code')} msg={j.get('msg')}")
        parsed[name] = j

    # --- A.3 : paramètres réellement reçus (lecture brute, AUCUN calcul) ---
    a3 = {}
    inst = (parsed.get("instruments_A3", {}).get("data") or [])
    if inst:
        a3["instruments"] = {k: inst[0].get(k) for k in
                             ("instId", "ctType", "ctVal", "ctValCcy", "ctMult", "settleCcy",
                              "lever", "listTime", "state")}
    frd = (parsed.get("funding_rate_A3", {}).get("data") or [])
    if frd:
        a3["funding_rate"] = {k: frd[0].get(k) for k in
                              ("instId", "fundingRate", "nextFundingRate", "fundingTime",
                               "nextFundingTime", "minFundingRate", "maxFundingRate",
                               "settFundingRate", "formulaType", "method")}

    # --- A.4 : sonde REST. Résultat consigné mais NON INTERPRÉTÉ tant que la sémantique n'est pas établie. ---
    rows = parsed.get("funding_history_probe_A4_REST", {}).get("data") or []
    times = sorted(int(r["fundingTime"]) for r in rows if r.get("fundingTime"))
    a4 = {"source_candidate": "REST funding-rate-history",
          "probe_param": f"after={WIN_START_MS + DAY} (2025-06-24T00:00:00Z), limit=10",
          "semantics_confirmed": SEMANTICS_CONFIRMED,
          "records_returned": len(rows),
          "oldest_fundingTime_utc": ms_to_utc(times[0]) if times else None,
          "newest_fundingTime_utc": ms_to_utc(times[-1]) if times else None,
          "window_start_utc": ms_to_utc(WIN_START_MS), "window_end_utc": ms_to_utc(WIN_END_MS)}
    if not SEMANTICS_CONFIRMED:
        a4["coverage"] = "non_concluant"
        a4["interpretation"] = ("sémantique before/after NON établie -> un lot (vide ou non) n'est ni "
                                "'couvre' ni 'rejet'. À reprendre après confirmation doc + sonde correcte.")
        abstentions.append("A.4 REST: sémantique de pagination non établie -> sonde NON CONCLUANTE "
                           "(ni couverture ni rejet).")
    else:  # sémantique confirmée -> interprétation (réservée à un futur run)
        covers = bool(times) and (times[-1] <= WIN_START_MS + 30 * DAY) and (times[0] <= WIN_START_MS + 7 * DAY)
        a4["coverage"] = "couvre" if covers else "ne_couvre_pas"

    # --- Verdict PHASE0 (jamais "rejeté" tant que A.4 n'est pas concluant) ---
    a3_ok = bool(a3.get("instruments") and a3.get("funding_rate"))
    if a3_ok and a4.get("coverage") == "couvre":
        verdict = "PHASE0_PASS"
    elif a3_ok:
        verdict = "PHASE0_PARTIEL"   # A.3 observé ; A.4 non concluant ; dataset non sondé
    else:
        verdict = "PHASE0_REJETE"    # échec dur sur les métadonnées

    manifest = {
        "phase": "PHASE0", "venue": VENUE, "instId": INST,
        "window": {"start_utc": ms_to_utc(WIN_START_MS), "end_utc": ms_to_utc(WIN_END_MS)},
        "created_utc": now_utc(),
        **prov,
        "authorization": ("Phase 0 explicitement autorisee (2026-06-23) : OKX/ETH-USDT-SWAP, public, "
                          "borne ; AUCUN backfill/boucle/agregat/annualisation/PnL."),
        "calls_count": len(calls), "receipts": receipts,
        "a3_params_recus": a3, "a4_probe": a4,
        "source_historique": ("REST funding-rate-history" if a4.get("coverage") == "couvre"
                              else "non concluante (REST non interprete ; dataset NON sonde)"),
        "verdict": verdict, "abstentions": abstentions,
        "note": ("Recus de validation parametres/capacite UNIQUEMENT. PAS une serie certifiee, non "
                 "agrege, ni calibration ni test. Phase 1 (backfill) INTERDITE sans nouvelle "
                 "validation humaine. Un futur run doit referencer le COMMIT (ou le runner_sha256) du runner."),
    }
    with open(os.path.join(run_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    lines = [f"# Rapport PHASE 0 — {VENUE} / {INST}", "",
             f"- Verdict : **{verdict}**",
             f"- Provenance : git `{prov['git_hash'][:10]}` ; code_versioned={prov['code_versioned']} ; "
             f"git_dirty={prov['git_dirty']} ; runner_sha256 `{prov['runner_sha256'][:16]}…`",
             f"- Fenêtre : {manifest['window']['start_utc']} -> {manifest['window']['end_utc']}",
             f"- Source historique : {manifest['source_historique']}",
             "", "## A.3 — paramètres réellement reçus", "```json",
             json.dumps(a3, ensure_ascii=False, indent=2), "```",
             "## A.4 — sonde (NON interprétée si sémantique non établie)", "```json",
             json.dumps(a4, ensure_ascii=False, indent=2), "```",
             "## Reçus (bruts hors Git, hashés)"]
    for r in receipts:
        lines.append(f"- `{r['name']}` — HTTP {r['http_status']} — {r['bytes']} o — sha256 "
                     f"`{r['sha256'][:16]}…` — `{r['raw_path']}`")
    lines += ["", "## Abstentions / motifs"] + ([f"- {a}" for a in abstentions] or ["- (aucune)"])
    lines += ["", "> Reçus de validation params/capacité UNIQUEMENT — pas une série certifiée, non "
              "agrégés, ni calibration ni test. **Phase 1 INTERDITE sans nouvelle validation humaine.**"]
    with open(os.path.join(run_dir, "report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print(json.dumps({"verdict": verdict, "provenance": prov, "source_historique": manifest["source_historique"],
                      "run_dir": os.path.relpath(run_dir, HERE).replace("\\", "/"),
                      "a3": a3, "a4": a4, "abstentions": abstentions}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
