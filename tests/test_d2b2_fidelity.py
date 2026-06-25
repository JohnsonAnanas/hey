"""Tests OFFLINE de la REGLE 3 corrigee (fidelite). Couvre le CHEMIN D'ECHEC que le benchmark byte-a-byte
sur le chemin de succes ne pouvait pas reveler : un echec transport ne devient JAMAIS un faux 'absent' ni
gas=0 ; WINDOW_UNAVAILABLE seulement sur absence CONFIRMEE (getCode reussi = 0x)."""
from d2b2_measure import (pool_state, exec_state, classify_cycle2,
                          CAT_OK, CAT_CAPACITY, CAT_WINDOW, CAT_INFRA)


def test_pool_state_present_absent_infra():
    assert pool_state("0x60806040", None, False) == "present"
    assert pool_state("0x", None, False) == "absent"              # getCode REUSSI + 0x -> absence CONFIRMEE
    assert pool_state(None, None, True) == "infra"                # echec transport (infra=True)
    assert pool_state(None, {"message": "boom"}, False) == "infra"   # erreur RPC -> presence indeterminee
    assert pool_state(None, None, False) == "infra"               # resultat absent sans 0x -> indetermine


def test_exec_state():
    assert exec_state("0xabc", None, False) == "ok"
    assert exec_state(None, {"message": "execution reverted: STF"}, False) == "revert"
    assert exec_state(None, {"message": "exceeded its compute units per second"}, False) == "infra"
    assert exec_state(None, None, True) == "infra"
    assert exec_state(None, None, False) == "infra"


def test_classify_getcode_infra_JAMAIS_window():
    # LE bug d'origine : un getCode echoue NE DOIT PAS devenir WINDOW_UNAVAILABLE
    assert classify_cycle2("infra", "present", "ok", True, True) == CAT_INFRA
    assert classify_cycle2("present", "infra", "ok", True, True) == CAT_INFRA


def test_classify_window_seulement_si_absent_confirme():
    assert classify_cycle2("absent", "present", "ok", True, True) == CAT_WINDOW
    assert classify_cycle2("present", "absent", "ok", True, True) == CAT_WINDOW


def test_classify_capacity_et_ok():
    assert classify_cycle2("present", "present", "revert", True, True) == CAT_CAPACITY
    assert classify_cycle2("present", "present", "ok", True, True) == CAT_OK


def test_classify_oracle_ou_gas_manquant_infra():
    assert classify_cycle2("present", "present", "ok", False, True) == CAT_INFRA   # ancre manquante -> infra
    assert classify_cycle2("present", "present", "ok", True, False) == CAT_INFRA   # gas manquant -> infra (jamais gas=0)


def test_infra_prime_sur_absent():
    # information incomplete (un pool infra) -> on ne CONCLUT pas l'absence : infra, jamais WINDOW
    assert classify_cycle2("infra", "absent", "ok", True, True) == CAT_INFRA
