"""Math AMM v2 (constant-product `x*y=k`) — PUR, sans reseau. Coeur testable du simulateur MAV.

Convention du cycle 2 pools (cf docs/formulas.md) :
- token X = token0, token Y = token1.
- Direction "A->B" : X->Y sur pool A=(a,b), puis Y->X sur pool B=(c,d). Profit exprime en token X.
- Reserves en unites HUMAINES (deja divisees par 10**decimals) pour la stabilite numerique.

Domaine de validite : pools constant-product UNIQUEMENT (Uniswap-v2, Sushi, Aerodrome *volatile*).
Pas v3 / Curve / Aerodrome-stable (math differente).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, asdict

FEE_MAX = 0.10        # garde : frais >= 10% = decodage suspect -> abstain
RESERVE_MAX = 1e15    # garde : au-dela, reserve aberrante / perte de precision float64 -> abstain


def get_amount_out(amount_in: float, reserve_in: float, reserve_out: float, fee: float) -> float:
    """Sortie d'un swap v2 unique. fee = taux (0.003 = 0.30%). γ = 1 - fee."""
    g = 1.0 - fee
    return (amount_in * g * reserve_out) / (reserve_in + amount_in * g)


def two_pool_x_out(dx: float, a: float, b: float, c: float, d: float, g1: float, g2: float) -> float:
    """X recupere apres X->Y sur A=(a,b) puis Y->X sur B=(c,d). Forme fermee (== 2 swaps enchaines)."""
    if dx <= 0:
        return 0.0
    return (b * c * g1 * g2 * dx) / (a * d + g1 * dx * (d + b * g2))


def optimal_dx(a: float, b: float, c: float, d: float, g1: float, g2: float) -> float:
    """Taille optimale Δx* du cycle X->Y(A)->X(B). Peut etre <= 0 (pas d'arb dans ce sens)."""
    den = g1 * (d + b * g2)
    if den <= 0:
        return float("nan")
    return (math.sqrt(a * b * c * d * g1 * g2) - a * d) / den


def arb_exists(a: float, b: float, c: float, d: float, g1: float, g2: float) -> bool:
    """Vrai si le cycle X->Y(A)->X(B) a un optimum > 0 (apres frais). <=> Δx* > 0."""
    return (b * c * g1 * g2) > (a * d)


@dataclass(frozen=True)
class CycleEval:
    direction: str        # "A->B" | "B->A"
    dx_star: float        # token0 (humain)
    x_out: float          # token0
    gross_profit: float   # token0
    gas_cost: float       # token0
    net_profit: float     # token0
    status: str           # ACCEPTED | REJECTED
    reason: str

    def to_dict(self) -> dict:
        return asdict(self)


def evaluate_cycle(direction: str, a: float, b: float, c: float, d: float,
                   g1: float, g2: float, gas_token0: float) -> CycleEval:
    """Evalue un sens du cycle (reserves humaines, token0=X). gas_token0 = cout du gas en token0.

    Filtre en cascade avec raison de rejet explicite : dx*<=0 -> profit_brut<=0 -> profit_net<=0.
    """
    dxs = optimal_dx(a, b, c, d, g1, g2)
    if not math.isfinite(dxs) or dxs <= 0:
        return CycleEval(direction, 0.0, 0.0, 0.0, gas_token0, -gas_token0,
                         "REJECTED", "dx*<=0 (pas d'arb dans ce sens)")
    xo = two_pool_x_out(dxs, a, b, c, d, g1, g2)
    gross = xo - dxs
    net = gross - gas_token0
    if gross <= 0:
        return CycleEval(direction, dxs, xo, gross, gas_token0, net, "REJECTED", "profit_brut<=0")
    if net <= 0:
        return CycleEval(direction, dxs, xo, gross, gas_token0, net, "REJECTED", "profit_net<=0 (gas)")
    return CycleEval(direction, dxs, xo, gross, gas_token0, net, "ACCEPTED", "")


def _pool_sane(p: dict) -> tuple[bool, str]:
    """Garde d'integrite : frais et reserves dans des bornes saines (sinon abstain, pas de calcul)."""
    f, rx, ry = p.get("fee"), p.get("reserve_x"), p.get("reserve_y")
    if f is None or not (0.0 <= f < FEE_MAX):
        return False, f"frais invalides ({f})"
    for r in (rx, ry):
        if not (isinstance(r, (int, float)) and math.isfinite(r) and 0.0 < r < RESERVE_MAX):
            return False, f"reserve invalide ({r})"
    return True, ""


def evaluate_pair(pool_a: dict, pool_b: dict, gas_token0: float) -> list[CycleEval]:
    """Evalue les DEUX sens entre deux pools v2 de la meme paire (token0=X, token1=Y).

    pool = {"reserve_x": ..., "reserve_y": ..., "fee": ...} en unites humaines.
    Garde : entree invalide -> deux verdicts ABSTAIN (jamais un calcul sur donnee douteuse).
    """
    for p in (pool_a, pool_b):
        ok, why = _pool_sane(p)
        if not ok:
            ab = CycleEval("?", 0.0, 0.0, 0.0, gas_token0, 0.0, "ABSTAIN", f"entree invalide: {why}")
            return [ab, ab]
    a, b, g1 = pool_a["reserve_x"], pool_a["reserve_y"], 1.0 - pool_a["fee"]
    c, d, g2 = pool_b["reserve_x"], pool_b["reserve_y"], 1.0 - pool_b["fee"]
    return [
        evaluate_cycle("A->B", a, b, c, d, g1, g2, gas_token0),   # X->Y sur A, Y->X sur B
        evaluate_cycle("B->A", c, d, a, b, g2, g1, gas_token0),   # X->Y sur B, Y->X sur A
    ]
