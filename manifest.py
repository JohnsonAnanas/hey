#!/usr/bin/env python
"""Manifeste de run/experience OBLIGATOIRE — rattache durablement DONNEE <-> CONCLUSION <-> VERSION
de code. Aucun run n'est CRU sans manifeste (meme role que checks.py pour l'integrite : une porte).

Rempli AUTOMATIQUEMENT : hash Git (HEAD), arbre sale ?, horodatage UTC, sha256 de chaque fichier
d'entree (la donnee brute n'est pas dans Git -- son EMPREINTE l'est, c'est elle qui fait foi).
A FOURNIR : hypothese, commande+params, periode, sources, univers, couts supposes, resultat, verdict.

Verdict : VALIDE / REJETE / NON_CONCLUANT (jamais "interessant" -- un verdict tranche). Cf
docs/run_manifest_standard.md.

Usage :
  python manifest.py --slug cex20m-rejection \
    --hypothesis "Les ~$20M extractibles CEX<->CEX sont-ils reels ?" \
    --command "audit identite sur data/logs/cex_monitor.csv" \
    --period "2026-06-15..2026-06-22" --source "ccxt order books binance/okx/htx" \
    --input data/logs/cex_monitor.csv --universe "91 coins /USDT, vol24h>=1M" \
    --costs "taker 10bps x2" --result "HYPE 2-sens, 3352/3363 lignes >= 1M USD" --verdict REJETE
  -> runs/<UTC>_<slug>/manifest.json (+ manifest.md lisible)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
VERDICTS = ("VALIDE", "REJETE", "NON_CONCLUANT")


def _git(*args: str) -> str:
    try:
        out = subprocess.run(["git", "-C", HERE, *args], capture_output=True, text=True)
        return out.stdout.strip()
    except Exception:
        return ""


def git_hash() -> str:
    return _git("rev-parse", "HEAD") or "UNVERSIONED"


def git_dirty() -> bool:
    return bool(_git("status", "--porcelain"))


def sha256_file(path: str) -> dict:
    """Empreinte d'un fichier d'entree (la donnee brute reste hors Git, son hash fait foi)."""
    p = path if os.path.isabs(path) else os.path.join(HERE, path)
    if not os.path.exists(p):
        return {"path": path, "sha256": None, "bytes": None, "error": "introuvable"}
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return {"path": path, "sha256": h.hexdigest(), "bytes": os.path.getsize(p)}


def build(args) -> dict:
    return {
        "slug": args.slug,
        "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "git_hash": git_hash(),
        "git_dirty": git_dirty(),
        "hypothesis": args.hypothesis,
        "command": args.command,
        "period": args.period,
        "sources": args.source,
        "inputs": [sha256_file(p) for p in (args.input or [])],
        "universe": args.universe,
        "assumed_costs": args.costs,
        "result": args.result,
        "verdict": args.verdict,
        "notes": args.notes or "",
    }


def to_md(m: dict) -> str:
    inp = "\n".join(
        f"- `{i['path']}` — sha256 `{(i['sha256'] or 'N/A')[:16]}…` ({i.get('bytes')} o)"
        for i in m["inputs"]
    ) or "- (aucun)"
    src = "\n".join(f"- {s}" for s in m["sources"]) or "- (aucune)"
    dirty = "  ⚠️ **arbre de travail SALE** au moment du run (le hash ne pin pas tout)" if m["git_dirty"] else ""
    return f"""# Manifeste de run — {m['slug']}

- **Verdict** : **{m['verdict']}**
- **Créé (UTC)** : {m['created_utc']}
- **Version de code (git)** : `{m['git_hash']}`{dirty}

## Hypothèse
{m['hypothesis']}

## Commande / paramètres
`{m['command']}`

## Période
{m['period']}

## Univers étudié
{m['universe']}

## Coûts supposés
{m['assumed_costs']}

## Sources
{src}

## Données d'entrée (hashées — la brute est hors Git, l'empreinte fait foi)
{inp}

## Résultat
{m['result']}

## Notes
{m['notes'] or '(—)'}
"""


def main() -> int:
    ap = argparse.ArgumentParser(description="Manifeste de run OBLIGATOIRE (donnée<->conclusion<->code).")
    ap.add_argument("--slug", required=True, help="identifiant court kebab-case")
    ap.add_argument("--hypothesis", required=True, help="la question testée, falsifiable")
    ap.add_argument("--command", required=True, help="commande + paramètres exacts du run")
    ap.add_argument("--period", required=True, help="période des données (ex. 2026-06-15..2026-06-22)")
    ap.add_argument("--source", action="append", default=[], help="source de données (répétable)")
    ap.add_argument("--input", action="append", default=[], help="fichier d'entrée à hasher (répétable)")
    ap.add_argument("--universe", required=True, help="univers étudié (tokens, venues…)")
    ap.add_argument("--costs", required=True, help="coûts supposés (frais, gas, slippage, capital…)")
    ap.add_argument("--result", required=True, help="résultat mesuré")
    ap.add_argument("--verdict", required=True, choices=VERDICTS)
    ap.add_argument("--notes", default="")
    args = ap.parse_args()

    m = build(args)
    stamp = m["created_utc"].replace(":", "").replace("-", "")
    run_dir = os.path.join(HERE, "runs", f"{stamp}_{m['slug']}")
    os.makedirs(run_dir, exist_ok=True)
    with open(os.path.join(run_dir, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(m, fh, ensure_ascii=False, indent=2)
    with open(os.path.join(run_dir, "manifest.md"), "w", encoding="utf-8") as fh:
        fh.write(to_md(m))
    flag = "  (⚠️ arbre SALE)" if m["git_dirty"] else ""
    print(f"Manifeste écrit -> {os.path.relpath(run_dir, HERE)}/  (verdict {m['verdict']}, git {m['git_hash'][:10]}){flag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
