"""Tests OFFLINE du transport D2B-2-v2 (batch) — AUCUN reseau. La SEMANTIQUE (fonctions pures) est celle de
v1, deja testee ; ici on verifie le transport : construction de requete, reordonnancement DETERMINISTE par
id, et la comparaison byte-a-byte du benchmark."""
from d2b2v2_measure import build_request, reorder_by_id, BATCH_CHUNK
from d2b2_bench import compare


def test_build_request():
    r = build_request(7, "eth_call", [{"to": "0x"}, "0x10"])
    assert r == {"jsonrpc": "2.0", "id": 7, "method": "eth_call", "params": [{"to": "0x"}, "0x10"]}


def test_reorder_by_id_deterministe():
    # reponses dans le DESesordre -> remappe par id (resultat/erreur)
    resp = [{"id": 2, "result": "0xb"}, {"id": 0, "result": "0xa"}, {"id": 1, "error": {"message": "x"}}]
    m = reorder_by_id(resp)
    assert m[0] == ("0xa", None) and m[2] == ("0xb", None)
    assert m[1][1] == {"message": "x"}


def test_batch_chunk_conservateur():
    assert isinstance(BATCH_CHUNK, int) and 1 <= BATCH_CHUNK <= 200


def test_compare_egalite_et_divergence():
    a = [{"route_hash": "h", "block": 1, "size_usd": 250, "direction": "uni_then_slip",
          "category": "ok", "upper_bound_usd": -0.5}]
    b_ok = [dict(a[0])]
    assert compare(a, b_ok)["identiques"] is True
    b_bad = [dict(a[0], upper_bound_usd=-0.4)]                 # une valeur differe
    c = compare(a, b_bad)
    assert c["identiques"] is False and c["n_mismatch"] == 1
    assert compare(a, [])["identiques"] is False              # cycle manquant -> divergent
