"""Valorisation USD COHERENTE des pools — PUR, testable. Corrige le bug "dust-mirage".

Bug d'origine : on valorisait chaque pool a SON PROPRE mid. Un pool desequilibre (une jambe en
poussiere) affiche un prix delirant (stale) et passe le filtre de liquidite -> faux ecart geant.

Fix : valoriser TOUTES les jambes au prix de REFERENCE (le pool le plus profond / un ancrage connu),
puis liquidite_pool = min(valeur_jambe0, valeur_jambe1). Un pool stale/dust devient alors
correctement PETIT et se fait filtrer. Le "signal de chasse" doit etre le MAV net, pas l'ecart mid.
"""
from __future__ import annotations

WETH_SYM = "WETH"


def anchor_usd(sym: str, eth_usd: float, stables: set) -> float | None:
    """Prix USD connu d'un token d'ancrage : stable = 1, WETH = eth_usd, sinon None."""
    if sym in stables:
        return 1.0
    if sym == WETH_SYM:
        return eth_usd
    return None


def reference_usd(s0: str, s1: str, reserves: list[tuple[float, float]],
                  eth_usd: float, stables: set) -> tuple[float, float] | None:
    """Prix USD de reference de (s0, s1). reserves = [(r0, r1), ...] humaines, une par venue.

    Le token non-ancre est price via le pool le PLUS PROFOND (cote ancre le plus gros),
    jamais via un pool stale. Retourne (usd0, usd1) ou None si aucun ancrage.
    """
    a0 = anchor_usd(s0, eth_usd, stables)
    a1 = anchor_usd(s1, eth_usd, stables)
    if a0 is not None and a1 is not None:
        return a0, a1
    if not reserves:
        return None
    if a1 is not None:                       # s1 ancre -> deriver s0 du pool le plus profond (cote s1)
        best = max(reserves, key=lambda rr: rr[1] * a1)
        if best[0] <= 0:
            return None
        return (best[1] / best[0]) * a1, a1
    if a0 is not None:                       # s0 ancre -> deriver s1
        best = max(reserves, key=lambda rr: rr[0] * a0)
        if best[1] <= 0:
            return None
        return a0, (best[0] / best[1]) * a0
    return None


def pool_liquidity_usd(r0: float, r1: float, usd0: float, usd1: float) -> float:
    """Liquidite tradable d'un pool = min des deux jambes valorisees au prix de REFERENCE.

    min (et pas somme) : un pool desequilibre est limite par sa jambe la plus faible.
    """
    return min(r0 * usd0, r1 * usd1)
