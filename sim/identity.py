"""Identite d'actif transversale (Phase 6) : un ecart inter-venue n'est valide que si les deux
jambes sont LE MEME actif a la MEME echelle. Sinon -> ABSTENTION (motif logge), comme
sim/integrity.py et sim/validate.py. On traite une CLASSE (l'identite), pas des instances.

Bug de classe tue ici (verifie sur data reelle, 2026-06-22) :
- CEX<->CEX (cex_monitor) groupait par TICKER -> 'HYPE' htx/okx profitable dans les DEUX sens,
  ~$20.6M a 0.6 bps ; 3352/3363 lignes >= $1M = mensonge systematique.
- cross-chain (collector) regroupait par symbole en JETANT l'adresse -> VELVET base(0xbf92..) vs
  bsc(0x8b19..) apparies sans preuve que c'est le meme projet bridge.

Invariant central, MECANISME-AGNOSTIQUE : un VRAI arbitrage est DIRECTIONNEL. Si les deux sens sont
profitables au meme instant, c'est incoherent -> abstention. Meme principe que
sim.amm_v2.arb_exists ('exactement un sens rentable'), porte inter-venue.
"""
from __future__ import annotations


# === 1. Carnet : profit extractible (pur, donc testable) ========================================

def walk_extractable(asks: list, bids: list, taker: float) -> float:
    """Profit USDT extractible en ACHETANT les asks et VENDANT dans les bids, net de taker des deux
    cotes, en marchant les carnets tant que c'est profitable. asks/bids = [(prix, taille), ...].
    Retour >= 0. (Deplace depuis cex_monitor pour etre TESTABLE et garde par les fonctions ci-dessous.)
    """
    profit = 0.0
    ai = bi = 0
    ra = asks[0][1] if asks else 0.0
    rb = bids[0][1] if bids else 0.0
    while ai < len(asks) and bi < len(bids):
        buy_p = asks[ai][0] * (1 + taker)
        sell_p = bids[bi][0] * (1 - taker)
        if sell_p <= buy_p:
            break
        q = min(ra, rb)
        profit += q * (sell_p - buy_p)
        ra -= q
        rb -= q
        if ra <= 1e-12:
            ai += 1
            ra = asks[ai][1] if ai < len(asks) else 0.0
        if rb <= 1e-12:
            bi += 1
            rb = bids[bi][1] if bi < len(bids) else 0.0
    return profit


# === 2. Gardes d'identite / d'echelle (chacune renvoie un motif d'abstention, ou None) ==========

def directional_inconsistency(profit_ab: float, profit_ba: float, floor: float = 0.0) -> str | None:
    """Motif d'abstention si l'arb parait profitable dans les DEUX sens (> floor), sinon None.

    Acheter-A/vendre-B ET acheter-B/vendre-A ne peuvent pas etre profitables en meme temps pour le
    MEME actif : les carnets se chevaucheraient des deux cotes au-dela des frais — ce qui n'arrive
    que si A et B ne cotent PAS le meme actif/echelle (collision de ticker, decimals, taille de
    contrat). Falsifieur DIRECT du resultat, sans hypothese sur la cause. Tue le HYPE $20.6M 2-sens.
    """
    if profit_ab > floor and profit_ba > floor:
        return (f"profitable dans les DEUX sens (A->B=${profit_ab:.0f}, B->A=${profit_ba:.0f}) : "
                f"identite/echelle incoherente, pas un arbitrage")
    return None


def scale_divergence(price_a: float, price_b: float, max_bps: float = 500.0) -> str | None:
    """Motif d'abstention si deux prix 'du meme actif' divergent de plus de max_bps, sinon None.

    Deux venues liquides cotant le MEME actif ne s'ecartent pas de centaines de bps (l'arb recolle).
    Un ecart enorme = quasi toujours un actif different (ticker reutilise) ou une echelle differente
    (decimals). Defense en profondeur du falsifieur directionnel (cas ou un seul sens 'sort' mais
    a une magnitude absurde).
    """
    if price_a <= 0 or price_b <= 0:
        return "prix non strictement positif"
    lo, hi = sorted((price_a, price_b))
    div_bps = (hi - lo) / lo * 1e4
    if div_bps > max_bps:
        return f"divergence {div_bps:.0f} bps > {max_bps:.0f} -> actif/echelle probablement different"
    return None


def implausible_magnitude(profit: float, max_usd: float = 1_000_000.0) -> str | None:
    """Motif d'abstention si le profit extractible d'un carnet (20 niveaux) depasse un plafond de
    plausibilite, sinon None.

    Un walk de ~20 niveaux d'un carnet public ne 'rend' pas des millions : au-dela, c'est une
    taille de carnet corrompue (unite/contrat) ou un actif different. Implemente litteralement le
    verdict de l'audit : '$20M n'est pas une decouverte tant que le carnet n'est pas reconcilie'.
    Tue la famille MEGA (un seul sens, mais ~$20M a 100 bps => notional ~$2B impossible).
    """
    if profit > max_usd:
        return f"extractible ${profit:.0f} > plafond ${max_usd:.0f} sur ~20 niveaux -> carnet a reconcilier"
    return None


def cex_extractable_guarded(asks_a, bids_a, asks_b, bids_b, taker: float, min_usd: float,
                            max_usd: float = 1_000_000.0):
    """Evalue l'extractible A->B et B->A, applique les gardes, renvoie (profit, direction, reason).

    direction 'A->B' = acheter sur A (asks_a), vendre sur B (bids_b).
    - reason != None  -> ABSTENTION (profit None) : incoherence directionnelle / divergence d'echelle
      / magnitude implausible. L'appelant DOIT logguer le motif (pas de skip muet).
    - sinon -> (profit, 'A->B'|'B->A', None) du seul sens profitable (>= min_usd), ou (0.0, None, None).
    """
    p_ab = walk_extractable(asks_a, bids_b, taker)   # acheter A, vendre B
    p_ba = walk_extractable(asks_b, bids_a, taker)   # acheter B, vendre A

    r = directional_inconsistency(p_ab, p_ba, floor=min_usd)
    if r:
        return None, None, r

    mid_a = (asks_a[0][0] + bids_a[0][0]) / 2 if asks_a and bids_a else None
    mid_b = (asks_b[0][0] + bids_b[0][0]) / 2 if asks_b and bids_b else None
    if mid_a and mid_b:
        r = scale_divergence(mid_a, mid_b)
        if r:
            return None, None, r

    profit, direction = (p_ab, "A->B") if p_ab >= p_ba else (p_ba, "B->A")
    r = implausible_magnitude(profit, max_usd)
    if r:
        return None, None, r
    if profit >= min_usd:
        return profit, direction, None
    return 0.0, None, None


# === 3. Identite cross-chain (par adresse de contrat) ===========================================

# Registre canonique : project_id -> {chaine: adresse(lower)}. A COMPLETER depuis les docs de bridge
# OFFICIELLES (jamais devine ; une adresse fausse serait elle-meme un bug d'identite). Defaut
# PRUDENT : adresse inconnue + adresses differentes -> UNVERIFIED (on n'affirme pas une identite
# qu'on ne peut pas prouver). NB : beaucoup de tokens partagent la MEME adresse entre chaines EVM
# (deploiement deterministe) -> identite alors prouvable DIRECTEMENT par la donnee, sans table.
CANONICAL: dict[str, dict[str, str]] = {
    # Exemple de SCHEMA a remplir (USDC n'a PAS la meme adresse partout -> doit etre tabule) :
    # "usd-coin": {"eth": "0xa0b86991...", "base": "0x833589fc...", "bsc": "0x8ac76a51..."},
}

_BY_ADDR = {(chain, addr.lower()): proj
            for proj, chains in CANONICAL.items() for chain, addr in chains.items()}


def crosschain_identity(addr_lo, addr_hi, chain_lo: str, chain_hi: str) -> tuple[str, str | None]:
    """Verdict d'identite d'un candidat cross-chain (memes lettres, 2 chaines) -> (verdict, motif).

    - 'VERIFIED'          : meme adresse entre chaines EVM (deploiement deterministe), ou meme projet
                            canonique tabule. Identite PROUVEE.
    - 'COLLISION_SUSPECT' : adresses connues mais de projets DIFFERENTS (ticker reutilise). MENSONGE.
    - 'UNVERIFIED'        : au moins une adresse inconnue du registre ET adresses differentes. On NE
                            PEUT PAS prouver -> pas un candidat reel (defaut prudent).
    """
    if not addr_lo or not addr_hi:
        return "UNVERIFIED", "adresse manquante sur au moins une jambe"
    a_lo, a_hi = addr_lo.lower(), addr_hi.lower()
    if a_lo == a_hi:
        return "VERIFIED", None   # meme contrat entre chaines = meme token (deploiement deterministe)
    p_lo = _BY_ADDR.get((chain_lo, a_lo))
    p_hi = _BY_ADDR.get((chain_hi, a_hi))
    if p_lo and p_hi:
        if p_lo == p_hi:
            return "VERIFIED", None
        return "COLLISION_SUSPECT", f"adresses de projets differents ({p_lo} vs {p_hi})"
    return "UNVERIFIED", "adresse(s) hors registre canonique -> identite non prouvee"
