"""Evaluateur de route par QUOTES executables (v3 via QuoterV2, v2 via getAmountOut entier) — Phase v3.

Round-trip exact au bloc sur une GRILLE de tailles USD. Conforme au gel du contrat (docs/route_evaluator.md) :
- #1 CALIBRATION : statut CANDIDAT_FORWARD INTERDIT ici (jamais produit, meme si PnL>0).
- #2 gas = `gas_estime_conservateur` SEPARE (exec / L1-data / marge), jamais 'exact'.
- #3 la persistance CLASSE (REJETE / MEV_RACE / A_OBSERVER_COURT / A_OBSERVER), ne rejette JAMAIS un PnL>0.
- #4 la conversion USD vient d'une ancre INDEPENDANTE (passee en usd0), jamais du pool candidat.
PUR : `quote_leg` et `gas_model` sont injectes -> testable avec des mocks. Borne SUPERIEURE (pas de MEV vu).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass


def round_trip(quote_leg, pool_a, pool_b, dx: int):
    """X->Y sur A puis Y->X sur B. dx en wei de X. -> (x_back_wei, gas_units_total) ou None si abstention.
    quote_leg(pool, x_to_y, amount_in) -> (amount_out_wei, gas_units) ou None."""
    if dx <= 0:
        return None
    qa = quote_leg(pool_a, True, dx)            # X->Y sur A
    if qa is None:
        return None
    dy, ga = qa
    if dy <= 0:
        return 0, ga                            # rien recu -> x_back 0 (perte de dx)
    qb = quote_leg(pool_b, False, dy)           # Y->X sur B
    if qb is None:
        return None
    x_back, gb = qb
    return x_back, ga + gb


@dataclass(frozen=True)
class QuotedDecision:
    pair: str
    venue_a: str
    venue_b: str
    direction: str
    status: str               # REJETE | POSITIF  (le runner reclasse POSITIF via la persistance)
    reason: str
    pnl_quote_usd: float      # apres frais de pool (embarques dans la quote executable)
    gas_exec_usd: float       # gas d'execution (gasEstimate quoteur/forfait) x baseFee
    gas_l1_usd: float         # cout L1/data OP-Stack (estime conservateur)
    gas_marge_usd: float      # marge de securite
    gas_total_usd: float      # = gas_estime_conservateur (somme) — JAMAIS 'exact'
    pnl_net_usd: float        # = pnl_quote - gas_total
    opt_size_usd: float
    max_net_usd: float
    breakeven_size_usd: float
    size_90_usd: float
    capacity_usd: float
    fixed_net_usd: float      # net a la taille FIXE de reference (pour la persistance)
    n_sizes: int
    n_abstain_sizes: int

    def to_dict(self) -> dict:
        return asdict(self)


_NAN = float("nan")


def _eval_dir(pair, va, vb, direction, p_first, p_second, sizes_usd, fixed_size_usd,
              usd0, dec_x, gas_model, quote_leg) -> QuotedDecision:
    scale = 10 ** dec_x
    pts = {}                                    # size_usd -> {net, gross, gas:(e,l,m,t)} ou None
    n_abs = 0
    sizes = list(sizes_usd)                     # CROISSANTES : une taille non-remplie => les + grandes non plus
    for i, s in enumerate(sizes):
        dx = int(s / usd0 * scale)
        rt = round_trip(quote_leg, p_first, p_second, dx)
        if rt is None:                          # monotonie : on n'interroge pas (cher) les tailles supérieures
            for s2 in sizes[i:]:
                pts[s2] = None; n_abs += 1
            break
        x_back, gas_units = rt
        gross = (x_back - dx) / scale * usd0
        ge, gl, gm, gt = gas_model(gas_units)
        pts[s] = {"net": gross - gt, "gross": gross, "gas": (ge, gl, gm, gt)}
    fixed_net = pts.get(fixed_size_usd, {}).get("net", _NAN) if pts.get(fixed_size_usd) else _NAN
    valid = {s: d for s, d in pts.items() if d is not None}
    if not valid:
        return QuotedDecision(pair, va, vb, direction, "REJETE", "toutes tailles abstenues",
                              _NAN, _NAN, _NAN, _NAN, _NAN, _NAN, _NAN, _NAN, _NAN, _NAN, _NAN,
                              fixed_net, len(sizes_usd), n_abs)
    best_s = max(valid, key=lambda s: valid[s]["net"])
    b = valid[best_s]
    ge, gl, gm, gt = b["gas"]
    if b["net"] <= 0:
        return QuotedDecision(pair, va, vb, direction, "REJETE", "pnl_net<=0",
                              b["gross"], ge, gl, gm, gt, b["net"], best_s, b["net"],
                              _NAN, _NAN, _NAN, fixed_net, len(sizes_usd), n_abs)
    pos = {s: d for s, d in valid.items() if d["net"] > 0}
    breakeven = max(pos)                                                   # plus grande taille net>0 = capacite
    size_90 = max((s for s, d in pos.items() if d["net"] >= 0.9 * b["net"]), default=best_s)
    return QuotedDecision(pair, va, vb, direction, "POSITIF", "",
                          b["gross"], ge, gl, gm, gt, b["net"], best_s, b["net"],
                          breakeven, size_90, breakeven, fixed_net, len(sizes_usd), n_abs)


def evaluate_route_quoted(pair, va, vb, pool_a, pool_b, sizes_usd, fixed_size_usd,
                          usd0, dec_x, gas_model, quote_leg) -> QuotedDecision:
    """Evalue les DEUX sens d'une route par quotes ; garde le meilleur net. Statut REJETE|POSITIF
    (jamais FORWARD : interdit en calibration, gel #1)."""
    da = _eval_dir(pair, va, vb, "A->B", pool_a, pool_b, sizes_usd, fixed_size_usd, usd0, dec_x, gas_model, quote_leg)
    db = _eval_dir(pair, vb, va, "B->A", pool_b, pool_a, sizes_usd, fixed_size_usd, usd0, dec_x, gas_model, quote_leg)
    cand = [d for d in (da, db) if d.status == "POSITIF"]
    if cand:
        return max(cand, key=lambda d: d.max_net_usd)
    return max((da, db), key=lambda d: (d.max_net_usd if d.max_net_usd == d.max_net_usd else -1e30))


def classify_calibration(frac_positive: float, longest_streak: int, min_blocks_ok: bool,
                         p_min: float, streak_min: int) -> str:
    """POSITIF -> statut DESCRIPTIF (gel #3). JAMAIS CANDIDAT_FORWARD en calibration (gel #1)."""
    if frac_positive <= 0:
        return "REJETE"                          # net jamais > 0 a la taille fixe
    if longest_streak <= 1:
        return "MEV_RACE"                        # isole (1 bloc) -> course probable, invisible a notre cadence
    if frac_positive >= p_min and longest_streak >= streak_min and min_blocks_ok:
        return "A_OBSERVER"                      # persistance mesuree suffisante (a notre cadence horaire)
    return "A_OBSERVER_COURT"                    # PnL>0 mais persistance sous le seuil long
