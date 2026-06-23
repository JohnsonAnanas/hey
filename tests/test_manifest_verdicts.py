"""Tests de la taxonomie de verdict des manifests (manifest.py) — MISSION RESET §2.

'VALIDE' est INTERDIT (jamais pour un triage/mediane/quote isolee). La nouvelle taxonomie a paliers
gouverne les NOUVEAUX runs ; les manifests deja ecrits restent immuables (non relus). L'interdiction
est appliquee A L'ECRITURE (pas seulement au CLI argparse) via _check_verdict.
"""
import pytest

from manifest import VERDICTS, FORBIDDEN_VERDICTS, build, write_manifest


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


def _args(verdict):
    from argparse import Namespace
    return Namespace(slug="t", hypothesis="h", command="c", period="p", source=[], input=[],
                     universe="u", costs="0", result="r", verdict=verdict, notes="")


def test_ecriture_refuse_verdict_interdit():
    # write_manifest (API runners) doit LEVER avant toute ecriture sur un verdict banni (pas de
    # dossier runs/ cree : _check_verdict leve dans build, avant persist).
    with pytest.raises(ValueError, match="INTERDIT|VALIDE"):
        write_manifest(slug="t", hypothesis="h", command="c", period="p", sources=[], inputs=[],
                       universe="u", costs="0", result="r", verdict="VALIDE")


def test_ecriture_refuse_verdict_inconnu():
    with pytest.raises(ValueError, match="inconnu"):
        build(_args("INTERESSANT"))


def test_build_accepte_verdict_valide():
    m = build(_args("REJETE"))
    assert m["verdict"] == "REJETE"
