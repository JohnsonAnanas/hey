"""Tests LOCAUX du parsing/QC du runner Phase 1 (phase1_binance_backfill) — AUCUN réseau.

Exigés par l'autorisation Phase 1 : « teste localement son parsing/QC ». Les fixtures reproduisent la
GIGUE millimétrique des `fundingTime` observée dans le brut Phase 0B (p.ex. 08:00:00.004) pour vérifier
que la QC raisonne en PAS arrondis (jamais en deltas ms stricts) : pas de faux gap dû à la gigue,
détection des vrais gaps, déduplication par fundingTime exact, monotonie, bornes de fenêtre, et que la
collecte ne remplit/n'interpole JAMAIS une valeur.
"""
import json

import pytest

from phase1_binance_backfill import (
    BASE_MS, WIN_START_MS, WIN_END_MS, W1_START, W1_END, W2_START, W2_END,
    parse_funding, qc_series, decide_verdict,
)

# Gigue déterministe par CRÉNEAU (ms), façon Phase 0B : un même créneau => mêmes ms dans toute fenêtre
# (indispensable pour fabriquer un doublon EXACT en cas de chevauchement).
_JIT = [0, 4, 13, 3, 0, 7, 11, 2, 9, 5]


def _jit(slot):
    return _JIT[slot % len(_JIT)]


def _rec(slot):
    return {"symbol": "ETHUSDT", "fundingTime": WIN_START_MS + slot * BASE_MS + _jit(slot),
            "fundingRate": "0.00001234", "markPrice": "2000.0"}


def _mk(slots):
    return [_rec(s) for s in slots]


# Borne haute demi-ouverte : dernier créneau strictement dans la fenêtre = NOMINAL-1.
NOMINAL = round((WIN_END_MS - WIN_START_MS) / BASE_MS)   # 1095 règlements (= 365 j × 3)
LAST = NOMINAL - 1                                        # créneau 1094 = 2026-06-22T16:00Z


# ----------------------------------------------------------------------------- constantes de fenêtre
def test_constantes_fenetre_et_non_chevauchement():
    assert WIN_START_MS == 1750636800000          # 2025-06-23T00:00:00.000Z
    assert WIN_END_MS == 1782172800000            # 2026-06-23T00:00:00.000Z
    assert W1_START == WIN_START_MS and W2_END == WIN_END_MS
    assert W1_END == 1766447999999                # 2025-12-22T23:59:59.999Z
    assert W2_START == 1766448000000              # 2025-12-23T00:00:00.000Z
    assert W2_START - W1_END == 1                 # 1 ms : non chevauchant ET sans trou de créneau
    assert NOMINAL == 1095


# --------------------------------------------------------------------------------------- parsing
def test_parse_liste_valide():
    raw = json.dumps([{"symbol": "ETHUSDT", "fundingTime": 1750636800000,
                       "fundingRate": "0.00002289", "markPrice": "2226.66"}]).encode()
    out = parse_funding(raw)
    assert out[0]["fundingTime"] == 1750636800000 and isinstance(out[0]["fundingTime"], int)


def test_parse_objet_erreur_binance_leve():
    # Binance renvoie un OBJET (pas une liste) en cas d'erreur -> ne JAMAIS l'avaler comme données.
    with pytest.raises(ValueError):
        parse_funding(b'{"code":-1121,"msg":"Invalid symbol."}')


def test_parse_liste_vide_ok():
    assert parse_funding(b"[]") == []


def test_parse_enregistrement_malforme_leve():
    with pytest.raises(ValueError):
        parse_funding(b'[{"symbol":"ETHUSDT"}]')   # pas de fundingTime


# ------------------------------------------------------------------------- série COMPLÈTE (2 fenêtres)
def test_serie_complete_contigue():
    w1, w2 = _mk(range(0, 548)), _mk(range(548, NOMINAL))     # 0..547 | 548..1094, contigu
    qc = qc_series([w1, w2], WIN_START_MS, WIN_END_MS, BASE_MS)
    assert qc["records_after_dedup"] == NOMINAL == 1095
    assert qc["duplicates_removed"] == 0
    assert qc["monotonic_strict"] is True
    assert qc["gaps_count"] == 0 and qc["missing_settlements_total"] == 0
    assert qc["reaches_window_start"] is True and qc["reaches_window_end"] is True
    assert qc["contiguous"] is True
    assert qc["sub_interval_anomalies"] == []
    # malgré la gigue ms : tous les intervalles observés = 8 h, tous les pas = 1
    assert qc["observed_interval_hours_histogram"] == {"8": 1094}
    assert qc["nstep_histogram"] == {"1": 1094}
    assert decide_verdict(qc, all_requests_ok=True, any_truncation=False) == "COLLECTE_COMPLETE"


def test_gigue_ne_cree_pas_de_faux_gap():
    qc = qc_series([_mk(range(0, NOMINAL)), []], WIN_START_MS, WIN_END_MS, BASE_MS)
    assert qc["gaps_count"] == 0
    # deltas bruts confinés à 8 h ± gigue (< ±100 ms), jamais interprétés comme gap
    assert BASE_MS - 100 <= qc["raw_delta_ms_min"] <= qc["raw_delta_ms_max"] <= BASE_MS + 100


# --------------------------------------------------------------------------------- GAP interne réel
def test_gap_interne_detecte():
    slots = [s for s in range(0, NOMINAL) if s != 800]       # créneau 800 manquant
    qc = qc_series([_mk(slots), []], WIN_START_MS, WIN_END_MS, BASE_MS)
    assert qc["gaps_count"] == 1
    assert qc["missing_settlements_total"] == 1
    assert qc["gaps"][0]["missing_settlements"] == 1
    assert qc["contiguous"] is False
    assert qc["records_after_dedup"] == NOMINAL - 1
    assert decide_verdict(qc, all_requests_ok=True, any_truncation=False) == "COLLECTE_INCOMPLETE"


# -------------------------------------------------------------------- DOUBLON (fenêtres chevauchantes)
def test_doublon_dedup_par_fundingtime_exact():
    w1, w2 = _mk(range(0, 549)), _mk(range(548, NOMINAL))     # créneau 548 dans LES DEUX
    qc = qc_series([w1, w2], WIN_START_MS, WIN_END_MS, BASE_MS)
    assert qc["duplicates_removed"] == 1
    assert len(qc["duplicate_fundingTimes_utc"]) == 1
    assert qc["records_after_dedup"] == NOMINAL              # 1095 après dédup
    assert qc["gaps_count"] == 0 and qc["contiguous"] is True
    assert decide_verdict(qc, all_requests_ok=True, any_truncation=False) == "COLLECTE_COMPLETE"


# ------------------------------------------------------------------- borne de fin NON atteinte
def test_borne_fin_non_atteinte():
    qc = qc_series([_mk(range(0, 1091)), []], WIN_START_MS, WIN_END_MS, BASE_MS)  # s'arrête trop tôt
    assert qc["reaches_window_start"] is True
    assert qc["reaches_window_end"] is False
    assert qc["gaps_count"] == 0                            # pas de trou interne, mais fin manquante
    assert decide_verdict(qc, all_requests_ok=True, any_truncation=False) == "COLLECTE_INCOMPLETE"


# ----------------------------------------------------------------------------- ABSTENTION / troncature
def test_abstention_si_requete_ko():
    qc = qc_series([_mk(range(0, NOMINAL)), []], WIN_START_MS, WIN_END_MS, BASE_MS)
    assert decide_verdict(qc, all_requests_ok=False, any_truncation=False) == "ABSTENTION"


def test_abstention_si_serie_vide():
    qc = qc_series([[], []], WIN_START_MS, WIN_END_MS, BASE_MS)
    assert qc["records_after_dedup"] == 0
    assert decide_verdict(qc, all_requests_ok=True, any_truncation=False) == "ABSTENTION"


def test_troncature_force_incomplete():
    qc = qc_series([_mk(range(0, NOMINAL)), []], WIN_START_MS, WIN_END_MS, BASE_MS)
    # même une série par ailleurs complète devient INCOMPLETE si troncature suspectée (pagination interdite)
    assert decide_verdict(qc, all_requests_ok=True, any_truncation=True) == "COLLECTE_INCOMPLETE"


def test_aucune_interpolation_invariant():
    qc = qc_series([_mk(range(0, NOMINAL)), []], WIN_START_MS, WIN_END_MS, BASE_MS)
    assert qc["no_interpolation"] is True
