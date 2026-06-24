"""Tests OFFLINE du runner D2B-2-lots (decoupage deterministe) — AUCUN reseau."""
from d2b2_lots import partition_lots, lot_digest, plan_digest, vivantes_in_order, LOT_SIZE


def _routes(n):
    return [{"route_hash": f"{i:064x}", "token0": "0xa", "token1": "0xb", "other": "0xb",
             "uni_pool": "0xu", "uni_fee": 500, "slip_pool": "0xs", "slip_tickSpacing": 100,
             "classification": "vivante"} for i in range(n)]


def test_partition_145_en_29_lots_de_5():
    lots = partition_lots(_routes(145), LOT_SIZE)
    assert LOT_SIZE == 5
    assert len(lots) == 29
    assert all(len(l) == 5 for l in lots)
    assert sum(len(l) for l in lots) == 145
    # couverture sans chevauchement : concat == liste d'origine, ordre preserve
    flat = [r for l in lots for r in l]
    assert [r["route_hash"] for r in flat] == [f"{i:064x}" for i in range(145)]


def test_dernier_lot_plus_court():
    lots = partition_lots(_routes(12), 5)
    assert [len(l) for l in lots] == [5, 5, 2]


def test_digests_deterministes():
    rs = _routes(10)
    assert plan_digest(rs) == plan_digest(list(rs)) and len(plan_digest(rs)) == 64
    lots = partition_lots(rs, 5)
    assert lot_digest(lots[0]) != lot_digest(lots[1])      # lots distincts -> digests distincts


def test_vivantes_filtre_et_ordre():
    results = [
        {"route_hash": "h0", "token0": "0xU", "token1": "0xW", "other": "0xW", "uni_pool": "0xu",
         "uni_fee": 500, "slip_pool": "0xs", "slip_tickSpacing": 100, "classification": "vivante"},
        {"route_hash": "h1", "token0": "0xU", "token1": "0xX", "other": "0xX", "uni_pool": "0xu2",
         "uni_fee": 3000, "slip_pool": "0xs2", "slip_tickSpacing": 1, "classification": "morte"},
        {"route_hash": "h2", "token0": "0xU", "token1": "0xY", "other": "0xY", "uni_pool": "0xu3",
         "uni_fee": 100, "slip_pool": "0xs3", "slip_tickSpacing": 200, "classification": "vivante"},
    ]
    v = vivantes_in_order(results)
    assert [r["route_hash"] for r in v] == ["h0", "h2"]    # mortes exclues, ordre preserve
    assert "classification" not in v[0]                    # seuls les champs de route conserves
    assert set(v[0]) == {"route_hash", "token0", "token1", "other", "uni_pool", "uni_fee",
                         "slip_pool", "slip_tickSpacing"}
