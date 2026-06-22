"""Math AMM v2 ENTIERE, EVM-exacte (floor division), en unites BRUTES (wei). Phase B, contrat #2.

Pourquoi une couche entiere distincte de sim/amm_v2 (float) : classer un PnL MARGINAL comme
'capturable' exige la MEME arithmetique que la chaine. A l'execution l'EVM arrondit en entier
(getAmountOut = division ENTIERE) ; un profit de quelques wei survit ou meurt sur cet arrondi.
=> le float EXPLORE (Δx* approx, sim/amm_v2), l'entier TRANCHE (ici).

Deux formes exactes selon le DEX :
- UniswapV2 & forks (UniV2/Sushi/BaseSwap) : getAmountOut single-expression (997/1000).
- Aerodrome/Solidly VOLATILE : retire le fee (floor, bps) PUIS x*y=k. Arrondi different -> forme propre.
"""
from __future__ import annotations


def get_amount_out_univ2(amount_in: int, reserve_in: int, reserve_out: int,
                         fee_num: int = 997, fee_den: int = 1000) -> int:
    """getAmountOut UniswapV2 EXACT (entier, floor). Frais via (fee_num, fee_den) : 0.30% = (997, 1000).
    fee_num == fee_den -> sans frais (PnL brut). amount_in/reserves en wei. Retour en wei (>= 0)."""
    if amount_in <= 0 or reserve_in <= 0 or reserve_out <= 0:
        return 0
    amount_in_with_fee = amount_in * fee_num
    numerator = amount_in_with_fee * reserve_out
    denominator = reserve_in * fee_den + amount_in_with_fee
    return numerator // denominator                      # floor = arrondi EVM


def get_amount_out_solidly(amount_in: int, reserve_in: int, reserve_out: int, fee_bps: int) -> int:
    """getAmountOut Aerodrome/Solidly VOLATILE EXACT : retire le fee (floor, bps) puis x*y=k entier."""
    if amount_in <= 0 or reserve_in <= 0 or reserve_out <= 0:
        return 0
    amount_in_after_fee = amount_in - (amount_in * fee_bps) // 10_000
    if amount_in_after_fee <= 0:
        return 0
    return (amount_in_after_fee * reserve_out) // (reserve_in + amount_in_after_fee)


def _nofee(pool: dict) -> dict:
    """Copie du pool a frais NULS (pour le PnL brut, decomposition #3)."""
    p = dict(pool)
    if p["kind"] == "solidly":
        p["fee_bps"] = 0
    else:
        p["fee_num"] = p.get("fee_den", 1000)            # fee_num == fee_den -> gamma = 1
    return p


def leg_out(pool: dict, amount_in: int, x_to_y: bool) -> int:
    """Sortie ENTIERE d'un swap sur `pool` dans le sens X->Y (x_to_y) ou Y->X.
    pool = {"kind","r0","r1", ("fee_num","fee_den")|"fee_bps"}. r0/r1 = reserves token0/token1 (wei)."""
    r0, r1 = pool["r0"], pool["r1"]
    rin, rout = (r0, r1) if x_to_y else (r1, r0)
    if pool["kind"] == "solidly":
        return get_amount_out_solidly(amount_in, rin, rout, pool["fee_bps"])
    return get_amount_out_univ2(amount_in, rin, rout, pool.get("fee_num", 997), pool.get("fee_den", 1000))


def two_pool_profit(dx: int, pool_a: dict, pool_b: dict, no_fee: bool = False) -> int:
    """Profit ENTIER (wei de token0=X) du cycle X->Y sur A puis Y->X sur B. dx en wei de X.
    no_fee=True -> frais a zero des deux cotes (PnL brut, decomposition #3)."""
    if dx <= 0:
        return 0
    a, b = (_nofee(pool_a), _nofee(pool_b)) if no_fee else (pool_a, pool_b)
    dy = leg_out(a, dx, x_to_y=True)                      # X->Y sur A
    x_back = leg_out(b, dy, x_to_y=False)                 # Y->X sur B
    return x_back - dx                                    # gain net en X (wei) ; < 0 = perte


def optimal_size(pool_a, pool_b, lo: int = 1, hi: int | None = None) -> tuple[int, int]:
    """Taille entiere dx* (wei X) maximisant le profit APRES frais du cycle A->B, par recherche
    ternaire (profit ~unimodal/concave en dx). Retour (dx*, profit*). Profit peut etre <= 0 (pas d'arb)."""
    if hi is None:
        hi = pool_a["r0"]                                 # borne large : au-dela, price-impact -> perte
    if hi < lo:
        return lo, two_pool_profit(lo, pool_a, pool_b)
    f = lambda dx: two_pool_profit(dx, pool_a, pool_b)
    while hi - lo > 2:
        m1 = lo + (hi - lo) // 3
        m2 = hi - (hi - lo) // 3
        if f(m1) < f(m2):
            lo = m1
        else:
            hi = m2
    # balayage local (robuste aux micro-wiggles d'arrondi entier)
    a, b = max(1, lo - 2), hi + 2
    best = max(range(a, b + 1), key=f)
    return best, f(best)


def _largest_with(f, lo: int, hi: int, thr: float) -> int | None:
    """Plus grand x dans [lo,hi] tel que f(x) >= thr, f DECROISSANTE sur l'intervalle. None si f(lo)<thr."""
    if f(lo) < thr:
        return None
    if f(hi) >= thr:
        return hi
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if f(mid) >= thr:
            lo = mid
        else:
            hi = mid
    return lo


def _smallest_with(f, lo: int, hi: int, thr: float) -> int | None:
    """Plus petit x dans [lo,hi] tel que f(x) >= thr, f CROISSANTE sur l'intervalle. None si f(hi)<thr."""
    if f(hi) < thr:
        return None
    if f(lo) >= thr:
        return lo
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if f(mid) >= thr:
            hi = mid
        else:
            lo = mid
    return hi


def pnl_curve(pool_a: dict, pool_b: dict, usd0: float, gas_usd: float, decimals_x: int) -> dict:
    """Courbe taille -> PnL NET (USD) du cycle A->B et ses points-cles (contrat #5).

    PnL net(dx) = profit_apres_frais(dx wei) / 10^dec_x * usd0 - gas_usd  (gas compte UNE seule fois).
    Renvoie : taille optimale, PnL net max, taille de break-even (capacite), taille gardant 90% du max,
    taille minimale viable (gas couvert), et notionnels USD correspondants. nan si non viable.
    """
    scale = 10 ** decimals_x
    net = lambda dx: two_pool_profit(dx, pool_a, pool_b) / scale * usd0 - gas_usd

    dx_opt, _ = optimal_size(pool_a, pool_b)
    max_net = net(dx_opt)
    hi = pool_a["r0"]
    nan = float("nan")
    if max_net <= 0:                                      # aucun sens viable
        return {"opt_size_x_wei": dx_opt, "opt_size_x": dx_opt / scale, "max_net_usd": max_net,
                "breakeven_size_x": nan, "size_90_x": nan, "min_viable_x": nan,
                "opt_notional_usd": dx_opt / scale * usd0, "capacity_usd": nan}

    breakeven = _largest_with(net, dx_opt, hi, 0.0)               # capacite : dernier dx ou net >= 0
    size_90 = _largest_with(net, dx_opt, breakeven or hi, 0.9 * max_net)   # garde 90% du max (cote haut)
    min_viable = _smallest_with(net, 1, dx_opt, 0.0)             # 1er dx ou le gas est couvert
    return {
        "opt_size_x_wei": dx_opt,
        "opt_size_x": dx_opt / scale,
        "opt_notional_usd": dx_opt / scale * usd0,
        "max_net_usd": max_net,
        "breakeven_size_x": (breakeven / scale) if breakeven else nan,
        "capacity_usd": (breakeven / scale * usd0) if breakeven else nan,
        "size_90_x": (size_90 / scale) if size_90 else nan,
        "min_viable_x": (min_viable / scale) if min_viable else nan,
    }
