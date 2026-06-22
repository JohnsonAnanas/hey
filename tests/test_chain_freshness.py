"""Tests de la decision de fraicheur RPC (PURE, sans reseau) — Phase 1 integrite.

Le but : prouver qu'un fournisseur en retard (ex. drpc a ~45h) ou mort est ECARTE, et qu'une
regression de bloc (reorg / RPC incoherent) est detectee.
"""
from sim.chain import choose_primary, is_block_regression


def test_choose_primary_exclut_le_stale_et_le_mort():
    heights = {"good1": 1000, "good2": 999, "stale": 200, "dead": None}
    primary, info = choose_primary(heights, fresh_tol=4)
    assert primary in {"good1", "good2"}           # le plus frais, jamais le stale
    assert info["n_healthy"] == 3                   # dead exclu
    assert info["n_agree"] == 2                     # good1/good2 au tip ; stale ecarte
    assert info["max_height"] == 1000
    assert info["ok"] is True                        # quorum >= 2


def test_choose_primary_un_seul_sain_mode_degrade():
    primary, info = choose_primary({"only": 500, "dead": None}, 4)
    assert primary == "only"
    assert info["n_agree"] == 1 and info["ok"] is False   # pas de quorum -> degrade


def test_choose_primary_aucun_sain():
    primary, info = choose_primary({"a": None, "b": None}, 4)
    assert primary is None and info["ok"] is False and info["n_healthy"] == 0


def test_choose_primary_stale_juste_dans_la_tolerance():
    # 998 est a 2 blocs du max (1000) -> dans FRESH_TOL=4 -> compte dans le quorum
    primary, info = choose_primary({"a": 1000, "b": 998}, 4)
    assert info["n_agree"] == 2 and info["ok"] is True


def test_regression_de_bloc():
    assert is_block_regression(1000, 996, tol=3) is True    # 996 < 1000-3
    assert is_block_regression(1000, 997, tol=3) is False   # pile a la tolerance
    assert is_block_regression(1000, 999, tol=3) is False
    assert is_block_regression(1000, 1001, tol=3) is False  # avance = ok
    assert is_block_regression(0, 500, tol=3) is False      # pas d'historique
    assert is_block_regression(1000, None, tol=3) is False  # lecture ratee != regression
