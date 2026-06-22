"""Tests de la valorisation de reference (anti dust-mirage).

Le point cle : un pool desequilibre/stale doit etre value PETIT au prix de REFERENCE,
pas a son propre mid delirant (qui etait la source du faux signal).
"""
from sim.pricing import anchor_usd, reference_usd, pool_liquidity_usd

STABLES = {"USDC", "USDbC", "DAI"}


def test_anchor_usd():
    assert anchor_usd("USDC", 2000.0, STABLES) == 1.0
    assert anchor_usd("WETH", 2000.0, STABLES) == 2000.0
    assert anchor_usd("VIRTUAL", 2000.0, STABLES) is None


def test_both_legs_anchored():
    # USDC/WETH : les deux ancres -> prix directs, pas besoin de pool.
    assert reference_usd("USDC", "WETH", [], 2000.0, STABLES) == (1.0, 2000.0)


def test_reference_filters_one_sided_dust():
    eth = 2000.0
    deep = (1_000_000.0, 200.0)   # 1M VIRTUAL, 200 WETH -> VIRTUAL ~ $0.40
    dust = (10.0, 15.0)           # pool desequilibre/stale (mid delirant)
    usd0, usd1 = reference_usd("VIRTUAL", "WETH", [deep, dust], eth, STABLES)
    assert abs(usd0 - 0.40) < 1e-9 and usd1 == 2000.0
    # pool profond : ~ $400k de liquidite, correctement value
    assert abs(pool_liquidity_usd(*deep, usd0, usd1) - 400_000) < 1.0
    # pool dust : PETIT au prix de reference = min(10*0.40, 15*2000) = $4
    assert pool_liquidity_usd(*dust, usd0, usd1) < 100.0
    # (a son PROPRE mid, VIRTUAL vaudrait (15/10)*2000 = $3000 -> jambe $30k = le faux signal)
    own_mid_usd0 = (dust[1] / dust[0]) * eth
    assert pool_liquidity_usd(*dust, own_mid_usd0, usd1) > 25_000.0   # ce que faisait l'ancien code


def test_deepest_pool_sets_reference():
    eth = 2000.0
    # deux pools au meme prix profond + un pool stale a prix decale : la reference vient du profond.
    p_deep = (500_000.0, 100.0)   # VIRTUAL ~ $0.40
    p_stale = (1000.0, 0.30)      # prix decale mais peu profond
    usd0, _ = reference_usd("VIRTUAL", "WETH", [p_deep, p_stale], eth, STABLES)
    assert abs(usd0 - 0.40) < 1e-9   # dicte par le pool profond, pas le stale
