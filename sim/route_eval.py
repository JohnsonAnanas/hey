"""Evaluateur de route UNIQUE et reutilisable (Phase B) — lecture seule, intra-chaine.

Ne remonte un candidat que s'il passe les 7 PORTES du contrat (docs/route_evaluator.md) ; chaque
porte manquante => REJETE avec MOTIF explicite (jamais de skip muet). Sortie = ligne de TABLEAU DE
DECISION (statut), pas une 'opportunite'.

Conservateur (exige de l'utilisateur) :
- identite = appartenance a l'UNIVERS CERTIFIE par ADRESSE (jamais un ticker, jamais un seuil) ;
- classement du PnL en math ENTIERE EVM (sim/amm_v2_int) — le float n'a servi qu'a explorer ;
- gas compte UNE seule fois ; PnL brut / frais de pool / gas / net / marge separes ;
- v3 -> REJETE explicite (quoter non implemente), jamais ignore ;
- persistance = proxy de competition/MEV mesure a TAILLE FIXE, PAS une preuve de capturabilite ;
- CANDIDAT_FORWARD ne nait JAMAIS d'un seul bloc (la persistance, multi-blocs, est requise).
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace

from sim.amm_v2_int import pnl_curve, two_pool_profit


# === Univers certifie (config versionnee, par adresse) ==========================================

def load_universe(path: str) -> dict:
    """Charge config/universe_base.json -> {addr_lower: {symbol, decimals}}. Identifiant = ADRESSE."""
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    return {a.lower(): {"symbol": v["symbol"], "decimals": v["decimals"]}
            for a, v in cfg["tokens"].items()}


# === Decision de route (une ligne du tableau) ===================================================

@dataclass(frozen=True)
class RouteDecision:
    pair: str
    venue_a: str
    venue_b: str
    direction: str            # "A->B" | "B->A" | ""
    status: str               # REJETE | A_OBSERVER | CANDIDAT_FORWARD
    reason: str               # motif explicite si REJETE
    # decomposition (USD) — gas compte UNE seule fois (dans pnl_net_usd)
    pnl_gross_usd: float      # PnL si frais de pool NULS (la dislocation brute)
    pool_fees_usd: float      # cout des frais des 2 pools
    gas_usd: float            # gas estime a ce bloc
    pnl_net_usd: float        # = gross - pool_fees - gas
    status_margin_usd: float  # marge de securite requise pour FORWARD
    # courbe taille->PnL (#5)
    opt_size_x: float
    opt_notional_usd: float
    max_net_usd: float
    breakeven_size_x: float   # capacite : derniere taille net>=0
    size_90_x: float          # plus grande taille gardant 90% du PnL max
    min_viable_x: float       # 1re taille couvrant le gas
    capacity_usd: float       # notionnel max deployable net>0

    def to_dict(self) -> dict:
        return asdict(self)


_NAN = float("nan")


def _reject(pair, va, vb, reason, gas_usd=_NAN) -> RouteDecision:
    return RouteDecision(pair, va, vb, "", "REJETE", reason,
                         _NAN, _NAN, gas_usd, _NAN, _NAN,           # gross, fees, gas, net, marge
                         _NAN, _NAN, _NAN, _NAN, _NAN, _NAN, _NAN)  # opt, notional, max_net, be, 90%, min, capacite


def evaluate_route(pool_a: dict, pool_b: dict, usd0: float, gas_usd: float,
                   universe: dict, status_margin_usd: float) -> RouteDecision:
    """Evalue UNE route (2 pools meme paire, meme chaine, meme bloc). Statut single-bloc :
    REJETE ou A_OBSERVER (FORWARD est attribue par assign_forward apres mesure de persistance).

    pool = {"venue","kind"('univ2'|'solidly'|'v3'),"pair"(s0,s1),"t0_addr","t1_addr","dec0","dec1",
            "r0","r1"(wei), ("fee_num","fee_den")|"fee_bps"}.  usd0 = prix USD de token0 (=X).
    """
    s0, s1 = pool_a["pair"]
    pair = f"{s0}/{s1}"
    va, vb = pool_a["venue"], pool_b["venue"]

    # Porte 7 (kind) : v3 -> REJETE EXPLICITE, jamais ignore silencieusement
    for p in (pool_a, pool_b):
        if p["kind"] == "v3":
            return _reject(pair, va, vb, "v3_quoter_non_implemente", gas_usd)

    # Porte 1 : identite CERTIFIEE par adresse (jamais ticker, jamais seuil)
    key_a = (pool_a["t0_addr"].lower(), pool_a["t1_addr"].lower())
    key_b = (pool_b["t0_addr"].lower(), pool_b["t1_addr"].lower())
    if key_a != key_b:
        return _reject(pair, va, vb, "identite: adresses de paire differentes entre venues", gas_usd)
    a0, a1 = key_a
    if a0 not in universe or a1 not in universe:
        return _reject(pair, va, vb, "identite_non_certifiee (token hors univers)", gas_usd)
    if universe[a0]["decimals"] != pool_a["dec0"] or universe[a1]["decimals"] != pool_a["dec1"]:
        return _reject(pair, va, vb, "identite: decimals != univers certifie", gas_usd)

    # Portes 2-6 : quote executable ENTIERE + courbe, dans les DEUX sens ; on garde le meilleur net
    dec_x = pool_a["dec0"]
    cands = [(d, pa, pb, pnl_curve(pa, pb, usd0, gas_usd, dec_x))
             for d, (pa, pb) in (("A->B", (pool_a, pool_b)), ("B->A", (pool_b, pool_a)))]
    direction, pa, pb, c = max(cands, key=lambda t: t[3]["max_net_usd"])

    # Decomposition (#3) a la taille optimale — gas UNE seule fois
    scale = 10 ** dec_x
    dx = c["opt_size_x_wei"]
    gross_usd = two_pool_profit(dx, pa, pb, no_fee=True) / scale * usd0
    after_fee_usd = two_pool_profit(dx, pa, pb) / scale * usd0
    pool_fees_usd = gross_usd - after_fee_usd
    net_usd = after_fee_usd - gas_usd

    if net_usd <= 0:                                     # Porte 7 : motif explicite, decomposition gardee
        reason = "pnl_net<=0 (gas)" if after_fee_usd > 0 else "pnl_brut<=0 apres frais de pool"
        return RouteDecision(pair, va, vb, direction, "REJETE", reason,
                             gross_usd, pool_fees_usd, gas_usd, net_usd, status_margin_usd,
                             c["opt_size_x"], c["opt_notional_usd"], c["max_net_usd"],
                             _NAN, _NAN, _NAN, _NAN)

    return RouteDecision(pair, va, vb, direction, "A_OBSERVER", "",
                         gross_usd, pool_fees_usd, gas_usd, net_usd, status_margin_usd,
                         c["opt_size_x"], c["opt_notional_usd"], c["max_net_usd"],
                         c["breakeven_size_x"], c["size_90_x"], c["min_viable_x"], c["capacity_usd"])


# === Persistance (contrat #4) — FIGEE avant le 1er run ==========================================

@dataclass(frozen=True)
class Persistence:
    fixed_size_x: float       # TAILLE OBSERVEE FIXE (humain) — la meme a chaque bloc, pour comparabilite
    n_blocks: int             # blocs observes (couverture)
    n_abstain: int            # blocs abstenus (lecture impossible / invariant non tenu)
    frac_positive: float      # part de blocs avec PnL net > 0 a taille fixe
    longest_streak: int       # plus longue sequence CONSECUTIVE de blocs net>0
    min_blocks_ok: bool       # n_blocks >= minimum requis

    def to_dict(self) -> dict:
        return asdict(self)


def persistence_stats(net_series: list[float], fixed_size_x: float, min_blocks: int,
                      n_abstain: int = 0) -> Persistence:
    """Mesure de persistance a TAILLE FIXE (contrat #4). net_series = PnL net (USD) par bloc.
    PROXY de competition/MEV, PAS une preuve de capturabilite (un gap qui dure peut juste etre
    inexecutable ; un gap qui meurt en 1 bloc = course MEV perdue par un solo)."""
    n = len(net_series)
    pos = [x > 0 for x in net_series]
    longest = streak = 0
    for p in pos:
        streak = streak + 1 if p else 0
        longest = max(longest, streak)
    frac = (sum(pos) / n) if n else 0.0
    return Persistence(fixed_size_x, n, n_abstain, frac, longest, n >= min_blocks)


def assign_forward(decision: RouteDecision, persistence: Persistence, *,
                   p_min: float, streak_min: int, cap_min_usd: float) -> RouteDecision:
    """A_OBSERVER -> CANDIDAT_FORWARD si persistance ET capacite tiennent ET net >= marge. Sinon
    inchange. FORWARD ne nait JAMAIS d'un seul bloc (la persistance multi-blocs est requise)."""
    if decision.status != "A_OBSERVER":
        return decision
    cap_ok = decision.capacity_usd == decision.capacity_usd and decision.capacity_usd >= cap_min_usd
    if (persistence.min_blocks_ok and persistence.frac_positive >= p_min
            and persistence.longest_streak >= streak_min
            and decision.pnl_net_usd >= decision.status_margin_usd and cap_ok):
        return replace(decision, status="CANDIDAT_FORWARD")
    return decision
