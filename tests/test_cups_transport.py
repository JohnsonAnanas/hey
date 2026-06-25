"""Tests OFFLINE du transport CUPS (AUCUN reseau) : limiteur token-bucket (horloge injectee), detection
CUPS, retries archives sur reponse vide/CUPS, revert NON retente, et ordre preserve par run_calls (conc. 1 et K)."""
import json as _json

from cups_transport import CupsLimiter, is_cups, rpc1, run_calls
from d2b2_bench import compare


def test_is_cups():
    assert is_cups({"message": "Your app has exceeded its compute units per second"})
    assert is_cups("429 Too Many Requests")
    assert not is_cups({"message": "execution reverted"})
    assert not is_cups(None)


def test_cups_limiter_capacite_et_refill():
    seq = [0.0, 0.0, 0.5]; it = iter(seq)        # init, acquire(100), acquire(40)
    lim = CupsLimiter(100, clock=lambda: next(it))
    lim.acquire(100)                              # tokens 100 -> 0 (immediat)
    assert abs(lim.tokens) < 1e-6
    lim.acquire(40)                               # +0.5s*100=50 dispo -> 50-40=10
    assert abs(lim.tokens - 10) < 1e-6


def test_cups_limiter_clamp_au_dessus_capacite():
    lim = CupsLimiter(50, clock=lambda: 0.0)
    lim.acquire(99999)                            # clampe a 50 -> ne boucle pas a l'infini
    assert lim.tokens <= 0.0 + 1e-9


class _Resp:
    def __init__(self, text, status=200):
        self.text = text; self.status_code = status


class _Sess:
    def __init__(self, scripted):
        self.scripted = list(scripted)
    def post(self, url, json=None, timeout=None):
        x = self.scripted.pop(0)
        if isinstance(x, Exception):
            raise x
        return x


class _SessByParam:
    """Reponse fonction du param[0] (l'index d'appel) -> independant de l'ordre de pop (pour conc. K)."""
    def post(self, url, json=None, timeout=None):
        return _Resp(_json.dumps({"result": "0x%x" % json["params"][0]}))


def _r(d):
    return _Resp(_json.dumps(d))


def test_rpc1_succes():
    res, err, infra = rpc1(_Sess([_r({"result": "0xabc"})]), "u", "eth_call", [], None, [], sleeper=lambda s: None)
    assert (res, err, infra) == ("0xabc", None, False)


def test_rpc1_cups_puis_succes_archive():
    arch = []
    sess = _Sess([_r({"error": {"message": "exceeded its compute units per second"}}), _r({"result": "0xok"})])
    res, err, infra = rpc1(sess, "u", "eth_call", [], None, arch, sleeper=lambda s: None)
    assert res == "0xok" and infra is False and len(arch) == 1


def test_rpc1_vide_persistant_infra():
    arch = []
    res, err, infra = rpc1(_Sess([_Resp("")] * 6), "u", "eth_getCode", [], None, arch, max_retry=6, sleeper=lambda s: None)
    assert res is None and infra is True and len(arch) == 6


def test_rpc1_429_puis_succes():
    res, err, infra = rpc1(_Sess([_Resp("", 429), _r({"result": "0x2"})]), "u", "eth_call", [], None, [], sleeper=lambda s: None)
    assert res == "0x2" and infra is False


def test_rpc1_revert_non_retente():
    arch = []
    res, err, infra = rpc1(_Sess([_r({"error": {"message": "execution reverted"}})]), "u", "eth_call", [], None, arch, sleeper=lambda s: None)
    assert res is None and infra is False and err == {"message": "execution reverted"} and arch == []


def test_run_calls_ordre_preserve_conc_1_et_K():
    calls = [("eth_call", [i]) for i in range(20)]
    for k in (1, 4):
        out = run_calls("u", calls, None, k, [], session_factory=_SessByParam)
        assert [o[0] for o in out] == ["0x%x" % i for i in range(20)]


def test_compare_egalite_et_divergence():
    a = [{"route_hash": "h", "block": 1, "size_usd": 250, "direction": "uni_then_slip", "category": "ok", "upper_bound_usd": -0.5}]
    assert compare(a, [dict(a[0])])["identiques"] is True
    c = compare(a, [dict(a[0], upper_bound_usd=-0.4)])
    assert c["identiques"] is False and c["n_mismatch"] == 1
    assert compare(a, [])["identiques"] is False
