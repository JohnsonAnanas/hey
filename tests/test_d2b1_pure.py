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


def test_classify_revert_vs_rpcerror_vs_ok():
    assert classify(None) == "ok"
    assert classify({"message": "execution reverted"}) == "revert"
    assert classify({"message": "execution reverted: STF"}) == "revert"
    assert classify({"message": "missing trie node"}) == "rpcerror"      # infra -> NON_CONCLUANT
    assert classify({"message": "rate limit exceeded"}) == "rpcerror"
    assert classify({"message": "TimeoutError: ..."}) == "rpcerror"


def test_usdc_montant_250():
    assert USDC_AMOUNT == 250 * 10 ** 6
