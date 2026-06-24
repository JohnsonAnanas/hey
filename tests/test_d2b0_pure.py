"""Tests OFFLINE du runner D2B-0 (cohorte USDC + routes + ordre gele) — AUCUN reseau."""
from d2b0_cohort_routes import (
    USDC, usdc_cohort, enumerate_routes, route_descriptor, route_hash, frozen_order,
)
from web3 import Web3

WETH = "0x4200000000000000000000000000000000000006"
OTHER = "0x00000000000000000000000000000000000000Ab"


def _entry(t0, t1, uni_pools, slip_pools):
    return {"token0": t0, "token1": t1, "decimals0": 6, "decimals1": 18,
            "uni_pools": uni_pools, "slip_pools": slip_pools}


def test_usdc_cohort_filtre_par_contrat():
    reg = [
        _entry(USDC, WETH, [{"pool": OTHER, "fee": 500, "tickSpacing": 10}], [{"pool": OTHER, "tickSpacing": 100}]),
        _entry(WETH, OTHER, [{"pool": OTHER, "fee": 500, "tickSpacing": 10}], [{"pool": OTHER, "tickSpacing": 1}]),
    ]
    coh = usdc_cohort(reg, USDC)
    assert len(coh) == 1                                   # seule la paire avec USDC
    assert Web3.to_checksum_address(coh[0]["token0"]) == Web3.to_checksum_address(USDC)


def test_enumerate_routes_produit_cartesien():
    e = _entry(USDC, WETH,
               [{"pool": "0x1111111111111111111111111111111111111111", "fee": 500, "tickSpacing": 10},
                {"pool": "0x2222222222222222222222222222222222222222", "fee": 3000, "tickSpacing": 60}],
               [{"pool": "0x3333333333333333333333333333333333333333", "tickSpacing": 100}])
    routes = enumerate_routes(e)
    assert len(routes) == 2 * 1                            # 2 pools Uni x 1 pool Slip
    assert {r["uni_fee"] for r in routes} == {500, 3000}


def test_route_hash_deterministe():
    r = {"token0": Web3.to_checksum_address(USDC), "token1": Web3.to_checksum_address(WETH),
         "uni_pool": "0x1111111111111111111111111111111111111111", "uni_fee": 500,
         "slip_pool": "0x3333333333333333333333333333333333333333", "slip_tickSpacing": 100}
    h1, h2 = route_hash(r), route_hash(dict(r))
    assert h1 == h2 and len(h1) == 64                      # deterministe, sha256
    assert "uni:" in route_descriptor(r) and "slip:" in route_descriptor(r)


def test_frozen_order_trie_par_hash_et_stable():
    e = _entry(USDC, WETH,
               [{"pool": "0x1111111111111111111111111111111111111111", "fee": 500, "tickSpacing": 10},
                {"pool": "0x2222222222222222222222222222222222222222", "fee": 3000, "tickSpacing": 60}],
               [{"pool": "0x3333333333333333333333333333333333333333", "tickSpacing": 100},
                {"pool": "0x4444444444444444444444444444444444444444", "tickSpacing": 1}])
    routes = enumerate_routes(e)
    o1 = frozen_order(list(routes))
    o2 = frozen_order(list(reversed(routes)))
    hashes = [r["route_hash"] for r in o1]
    assert hashes == sorted(hashes)                        # trie par hash croissant
    assert [r["route_hash"] for r in o1] == [r["route_hash"] for r in o2]   # ordre independant de l'entree
