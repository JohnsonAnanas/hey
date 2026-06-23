"""Tests de la taxonomie de verdict des manifests (manifest.py) — MISSION RESET §2.

'VALIDE' est INTERDIT (jamais pour un triage/mediane/quote isolee). La nouvelle taxonomie a paliers
gouverne les NOUVEAUX runs ; les manifests deja ecrits restent immuables (non relus).
"""
from manifest import VERDICTS, FORBIDDEN_VERDICTS


def test_valide_est_interdit():
    assert "VALIDE" not in VERDICTS
    assert "VALIDE" in FORBIDDEN_VERDICTS


def test_nouvelle_taxonomie_presente():
    for v in ("INVALIDE", "REJETE", "NON_CONCLUANT", "LEAD", "MECANISME_CONFIRME",
              "QUOTE_POSITIVE", "PAPER_ELIGIBLE"):
        assert v in VERDICTS


def test_paliers_positifs_ordonnes():
    # les niveaux positifs se gagnent par paliers croissants
    assert VERDICTS.index("MECANISME_CONFIRME") < VERDICTS.index("QUOTE_POSITIVE") \
        < VERDICTS.index("PAPER_ELIGIBLE")
