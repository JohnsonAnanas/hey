"""Tests OFFLINE du runner D2B-1 (liveness) — AUCUN reseau."""
from d2b1_liveness import exec_calldata, classify, USDC, USDC_AMOUNT
from d1_6_simulated_executor_envelope import SEL_UNI_THEN_SLIP, SEL_SLIP_THEN_UNI
from web3 import Web3

OTHER = Web3.to_checksum_address("0x4200000000000000000000000000000000000006")  # WETH


def test_exec_calldata_usdc_in():
    cd = exec_calldata("uni_then_slip", USDC, OTHER, 500, 100, USDC_AMOUNT)
    assert cd[:4] == SEL_UNI_THEN_SLIP and len(cd) == 4 + 32 * 8
    assert int.from_bytes(cd[4 + 192:4 + 224], "big") == USDC_AMOUNT   # amountIn = $250 USDC
    cd2 = exec_calldata("slip_then_uni", USDC, OTHER, 500, 100, USDC_AMOUNT)
    assert cd2[:4] == SEL_SLIP_THEN_UNI


def test_classify_exec_fail_vs_infra_vs_ok():
    assert classify(None) == "ok"
    # echecs d'EXECUTION deterministes -> "revert" (route morte)
    assert classify({"message": "execution reverted"}) == "revert"
    assert classify({"message": "execution reverted: STF"}) == "revert"
    assert classify({"message": "EVM error: InvalidFEOpcode"}) == "revert"   # le temoin INVALID
    assert classify({"message": "out of gas"}) == "revert"
    # INFRA -> "rpcerror" (NON_CONCLUANT)
    assert classify({"message": "missing trie node"}) == "rpcerror"
    assert classify({"message": "rate limit exceeded"}) == "rpcerror"
    assert classify({"message": "request timed out"}) == "rpcerror"
    # inconnu -> conservateur (NON_CONCLUANT, jamais silencieusement 'morte')
    assert classify({"message": "quelque chose d'inattendu"}) == "rpcerror"


def test_usdc_montant_250():
    assert USDC_AMOUNT == 250 * 10 ** 6
