#!/usr/bin/env python
"""Point d'entree unique du controle d'integrite (Phase 5) : tests + health-check live.

A lancer AVANT de croire un run de scan. Les tests sont bloquants (sortie non-zero si echec) ;
le health-check live depend du reseau et reste informatif. Cf docs/data_integrity.md.

Usage : python checks.py
"""
from __future__ import annotations

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable


def run(title: str, cmd: list[str]) -> int:
    print("\n" + "=" * 64)
    print(title)
    print("=" * 64)
    return subprocess.run(cmd, cwd=HERE).returncode


def main() -> int:
    rc_tests = run("1) Tests unitaires (math / pricing / fraicheur RPC / validation pool)",
                   [PY, "-m", "pytest", "tests/", "-q"])
    rc_health = run("2) Health-check live (quorum RPC / same-block / prix vs Binance / log)",
                    [PY, "verify_data.py"])
    print("\n" + "=" * 64)
    ok = (rc_tests == 0)   # tests = bloquants ; health-check = informatif (reseau)
    print(f"RESULTAT : tests {'OK' if rc_tests == 0 else 'ECHEC'} | health-check rc={rc_health}")
    print("(Les tests sont bloquants ; le health-check depend du reseau et reste informatif.)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
