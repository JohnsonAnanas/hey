"""Tests OFFLINE des fonctions pures du runner D1 (d1_mev_boundary_control) — AUCUN réseau.

Vecteurs de contrôle = SÉLECTEURS PUBLICS CONNUS (Uniswap / OP-stack / ERC-20). Si une signature ABI du
runner est fausse, ces tests échouent AVANT tout appel réseau. Couvre aussi l'encodage du chemin v3, les
slots de mapping (override), la sérialisation EIP-1559 (getL1Fee), et toute l'arithmétique gas/upper_bound
+ verdicts D0.
"""
import rlp

from d1_mev_boundary_control import (
    SEL_EXACTINPUT, SEL_QUOTE, SEL_GETL1FEE, SEL_BALANCEOF, SEL_ALLOWANCE, SEL_DECIMALS,
    WETH, USDC, ROUTER, SENDER, MIN_NOTIONAL,
    encode_v3_path, exact_input_calldata, quote_calldata, mapping_slot, nested_mapping_slot,
    serialize_dummy_1559, gas_normal_wei, upper_bound_wei, wei_to_usd, run_length_positive,
    edge_verdict, capacity_classify,
)
from web3 import Web3


# ------------------------------------------------------------- sélecteurs publics connus (anti-erreur ABI)
def test_selecteurs_publics_connus():
    assert SEL_EXACTINPUT == bytes.fromhex("b858183f")   # Uniswap SwapRouter02.exactInput
    assert SEL_QUOTE == bytes.fromhex("c6a5026a")         # Uniswap QuoterV2.quoteExactInputSingle (struct)
    assert SEL_GETL1FEE == bytes.fromhex("49948e0e")      # OP-stack GasPriceOracle.getL1Fee(bytes)
    assert SEL_BALANCEOF == bytes.fromhex("70a08231")     # ERC-20 balanceOf(address)
    assert SEL_ALLOWANCE == bytes.fromhex("dd62ed3e")     # ERC-20 allowance(address,address)
    assert SEL_DECIMALS == bytes.fromhex("313ce567")      # ERC-20 decimals()


# --------------------------------------------------------------------------------- chemin v3
def test_encode_v3_path_structure_et_fees():
    p = encode_v3_path([WETH, USDC, WETH], [500, 3000])
    assert len(p) == 20 + 3 + 20 + 3 + 20 == 66
    assert p[0:20] == bytes.fromhex(WETH[2:])
    assert p[20:23] == (500).to_bytes(3, "big") == b"\x00\x01\xf4"
    assert p[23:43] == bytes.fromhex(USDC[2:])
    assert p[43:46] == (3000).to_bytes(3, "big") == b"\x00\x0b\xb8"
    assert p[46:66] == bytes.fromhex(WETH[2:])


def test_calldata_prefixes():
    cd = exact_input_calldata(encode_v3_path([WETH, USDC, WETH], [500, 3000]), SENDER, 10 ** 18)
    assert cd[:4] == SEL_EXACTINPUT and (len(cd) - 4) % 32 == 0
    qd = quote_calldata(WETH, USDC, 10 ** 18, 500)
    assert qd[:4] == SEL_QUOTE and len(qd) == 4 + 32 * 5   # 5 mots ABI (address,address,uint,uint24,uint160)


# --------------------------------------------------------------------------------- slots de mapping (override)
def test_mapping_slot_matches_canonical():
    expected = "0x" + Web3.keccak(
        (b"\x00" * 12 + bytes.fromhex(SENDER[2:])) + (3).to_bytes(32, "big")).hex()
    assert mapping_slot(SENDER, 3) == expected
    assert mapping_slot(SENDER, 3) != mapping_slot(ROUTER, 3)   # clés différentes -> slots différents


def test_nested_mapping_slot_matches_canonical():
    inner = Web3.keccak((b"\x00" * 12 + bytes.fromhex(SENDER[2:])) + (4).to_bytes(32, "big"))
    expected = "0x" + Web3.keccak((b"\x00" * 12 + bytes.fromhex(ROUTER[2:])) + inner).hex()
    assert nested_mapping_slot(SENDER, ROUTER, 4) == expected


# --------------------------------------------------------------------------------- sérialisation EIP-1559
def test_serialize_dummy_1559_decodable():
    data = exact_input_calldata(encode_v3_path([WETH, USDC, WETH], [500, 3000]), SENDER, 10 ** 18)
    ser = serialize_dummy_1559(8453, 250000, ROUTER, data, 2_000_000_000, 1_000_000)
    assert ser[0] == 0x02                       # type EIP-1559
    fields = rlp.decode(ser[1:])
    assert len(fields) == 12                    # chainId..s
    assert int.from_bytes(fields[0], "big") == 8453
    assert fields[5] == bytes.fromhex(ROUTER[2:])   # to
    assert fields[7] == data                    # calldata intacte


# --------------------------------------------------------------------------------- arithmétique gas/borne
def test_gas_et_upper_bound():
    assert gas_normal_wei(200000, 10, 5000) == 200000 * 10 + 5000
    # out2 < in => round-trip perdant (cas contrôle) -> borne négative
    ub = upper_bound_wei(out2_wei=99 * 10 ** 16, in_wei=10 ** 18, gas_units=200000,
                         base_fee_l2=10 ** 7, l1_fee_wei=10 ** 13)
    assert ub < 0
    # out2 > in et gas faible -> borne positive
    ub2 = upper_bound_wei(out2_wei=101 * 10 ** 16, in_wei=10 ** 18, gas_units=1, base_fee_l2=1, l1_fee_wei=1)
    assert ub2 > 0


def test_wei_to_usd():
    assert abs(wei_to_usd(10 ** 18, 2500.0) - 2500.0) < 1e-9
    assert abs(wei_to_usd(-(10 ** 17), 2000.0) - (-200.0)) < 1e-9


# --------------------------------------------------------------------------------- persistance descriptive
def test_run_length_positive():
    r = run_length_positive([True, True, False, True, True, True, False])
    assert r["blocks"] == 7 and r["positive_blocks"] == 5 and r["max_run_positive"] == 3
    assert run_length_positive([])["max_run_positive"] == 0
    assert run_length_positive([False, False])["fraction_positive"] == 0.0


# --------------------------------------------------------------------------------- verdicts D0
def test_edge_verdict():
    assert edge_verdict(any_positive=False, has_valid_quotes=True) == "NO_ATOMIC_EDGE"
    assert edge_verdict(any_positive=True, has_valid_quotes=True) == "ATOMIC_MEV_SCOPE"
    assert edge_verdict(any_positive=False, has_valid_quotes=False) == "NON_CONCLUANT"


def test_capacity_classify():
    assert capacity_classify([], MIN_NOTIONAL, has_valid=True) == "PAS_DE_CAPACITE"
    assert capacity_classify([250], MIN_NOTIONAL, has_valid=True) == "CAPACITY_INSUFFICIENT"
    assert capacity_classify([2500], MIN_NOTIONAL, has_valid=True) == "CAPACITE_DOCUMENTEE"
    assert capacity_classify([250, 5000], MIN_NOTIONAL, has_valid=True) == "CAPACITE_DOCUMENTEE"
    assert capacity_classify([], MIN_NOTIONAL, has_valid=False) == "NON_CONCLUANT"
