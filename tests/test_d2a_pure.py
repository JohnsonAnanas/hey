"""Tests OFFLINE du runner D2A (registre cross-protocole) — AUCUN reseau.

Verifie le decodage des evenements PoolCreated des DEUX factories (Uni v3 : fee+tickSpacing ; SlipStream :
tickSpacing seul) et la logique de candidats (meme paire ORDONNEE sur les deux factories).
"""
from d2a_crossprotocol_registry import (
    TOPIC_UNI, TOPIC_SLIP, decode_uni_log, decode_slip_log, candidates_from_maps,
)
from web3 import Web3

WETH = "0x4200000000000000000000000000000000000006"
USDC = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
POOL = "0x1111111111111111111111111111111111111111"


def _topic_addr(a):
    return "0x" + "00" * 12 + a[2:].lower()


def _w(n):
    return n.to_bytes(32, "big").hex()


def test_topics_distincts_et_corrects():
    assert TOPIC_UNI == "0x" + Web3.keccak(text="PoolCreated(address,address,uint24,int24,address)").hex()
    assert TOPIC_SLIP == "0x" + Web3.keccak(text="PoolCreated(address,address,int24,address)").hex()
    assert TOPIC_UNI != TOPIC_SLIP


def test_decode_uni_log():
    log = {"topics": [TOPIC_UNI, _topic_addr(WETH), _topic_addr(USDC), "0x" + _w(500)],
           "data": "0x" + _w(10) + _w(int(POOL, 16)), "blockNumber": hex(1_500_000)}
    d = decode_uni_log(log)
    assert d["token0"] == Web3.to_checksum_address(WETH)
    assert d["token1"] == Web3.to_checksum_address(USDC)
    assert d["fee"] == 500 and d["tickSpacing"] == 10
    assert d["pool"] == Web3.to_checksum_address(POOL) and d["block"] == 1_500_000


def test_decode_slip_log():
    log = {"topics": [TOPIC_SLIP, _topic_addr(WETH), _topic_addr(USDC), "0x" + _w(100)],
           "data": "0x" + _w(int(POOL, 16)), "blockNumber": hex(14_000_000)}
    d = decode_slip_log(log)
    assert d["token0"] == Web3.to_checksum_address(WETH)
    assert d["token1"] == Web3.to_checksum_address(USDC)
    assert d["tickSpacing"] == 100
    assert d["pool"] == Web3.to_checksum_address(POOL) and d["block"] == 14_000_000


def test_candidates_intersection_ordonnee():
    A = Web3.to_checksum_address(WETH)
    B = Web3.to_checksum_address(USDC)
    C = Web3.to_checksum_address("0x0000000000000000000000000000000000000abc")
    uni = {(A, B): [{}], (A, C): [{}]}     # WETH/USDC et WETH/C sur Uni
    slip = {(A, B): [{}], (B, C): [{}]}    # WETH/USDC et USDC/C sur Slip
    cands = candidates_from_maps(uni, slip)
    assert cands == [(A, B)]               # seule WETH/USDC est sur LES DEUX
    # ordre des contrats compte (pas ticker) : (A,C) != (C,A)
    assert candidates_from_maps({(A, C): [{}]}, {(C, A): [{}]}) == []
