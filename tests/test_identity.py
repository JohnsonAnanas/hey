"""Tests de la couche d'identite d'actif (PURE) — Phase 6 integrite.

Epingle le bug de classe trouve sur data reelle (2026-06-22) : appariement par TICKER -> 'profits'
fantomes inter-venue. On documente le bug ET le fix :
  - le walk NU se fait avoir (rend un profit enorme dans les DEUX sens : le mensonge HYPE $20.6M) ;
  - le garde directionnel s'ABSTIENT sur ce meme cas ;
  - un vrai arb a sens unique passe ;
  - l'identite cross-chain distingue meme-adresse (VERIFIED) de adresses-differentes-hors-registre
    (UNVERIFIED), sur les adresses REELLES CTM (meme contrat bsc/eth) et VELVET (contrats differents).
"""
from sim.identity import (
    walk_extractable, directional_inconsistency, scale_divergence, implausible_magnitude,
    cex_extractable_guarded, crosschain_identity,
)

# Adresses REELLES (data/collected/crosschain_obs.csv, 2026-06-22).
CTM_BSC = "0xc8fb80fcc03f699c70ff0cc08c09106288888888"   # vanity-address, IDENTIQUE sur bsc et eth
CTM_ETH = "0xc8fb80fcc03f699c70ff0cc08c09106288888888"
VELVET_BASE = "0xbf927b841994731c573bdf09ceb0c6b0aa887cdd"
VELVET_BSC = "0x8b194370825e37b33373e74a41009161808c1488"   # adresse DIFFERENTE -> non prouvable


# --- 1. Le falsifieur directionnel (coeur du fix) -----------------------------------------------

def test_walk_nu_se_fait_avoir_dans_les_deux_sens():
    """REPRO du bug HYPE : deux carnets internes CROISES (bid > ask) -> le walk nu 'rend' un profit
    enorme dans les DEUX sens. C'est le mensonge que l'ancien cex_monitor logguait ($20.6M, 0.6 bps).
    """
    asks_a = [(40.0, 1_000_000.0)]; bids_a = [(40.5, 1_000_000.0)]   # carnet corrompu (bid>ask)
    asks_b = [(40.0, 1_000_000.0)]; bids_b = [(40.5, 1_000_000.0)]
    p_ab = walk_extractable(asks_a, bids_b, taker=0.001)
    p_ba = walk_extractable(asks_b, bids_a, taker=0.001)
    assert p_ab > 100_000 and p_ba > 100_000           # le walk nu est dupe des DEUX cotes


def test_garde_sabstient_sur_arb_deux_sens():
    """Le fix : sur le meme cas, cex_extractable_guarded s'ABSTIENT (motif explicite, pas de chiffre)."""
    asks_a = [(40.0, 1_000_000.0)]; bids_a = [(40.5, 1_000_000.0)]
    asks_b = [(40.0, 1_000_000.0)]; bids_b = [(40.5, 1_000_000.0)]
    profit, direction, reason = cex_extractable_guarded(
        asks_a, bids_a, asks_b, bids_b, taker=0.001, min_usd=50.0)
    assert profit is None and direction is None
    assert reason is not None and "DEUX sens" in reason


def test_directional_inconsistency_pure():
    assert directional_inconsistency(1000.0, 800.0, floor=50.0) is not None   # deux sens -> abstain
    assert directional_inconsistency(1000.0, 0.0, floor=50.0) is None         # un seul sens -> OK
    assert directional_inconsistency(10.0, 10.0, floor=50.0) is None          # sous le floor (bruit)


# --- 2. Un VRAI arbitrage (a sens unique) doit passer -------------------------------------------

def test_arbitrage_reel_a_sens_unique_passe():
    """A est moins cher que B : acheter A / vendre B est rentable ; le sens inverse ne l'est pas."""
    asks_a = [(100.0, 10.0)]; bids_a = [(99.9, 10.0)]     # A ~100
    asks_b = [(101.0, 10.0)]; bids_b = [(100.9, 10.0)]    # B ~101 (plus cher)
    profit, direction, reason = cex_extractable_guarded(
        asks_a, bids_a, asks_b, bids_b, taker=0.0005, min_usd=1.0)
    assert reason is None and direction == "A->B" and profit > 0


# --- 3. Defenses en profondeur : echelle et magnitude -------------------------------------------

def test_scale_divergence():
    assert scale_divergence(40.0, 40.1) is None                  # ~25 bps : meme actif plausible
    assert scale_divergence(40.0, 80.0) is not None              # +10000 bps : actif/echelle different
    assert scale_divergence(0.0, 40.0) is not None               # prix non positif


def test_implausible_magnitude():
    assert implausible_magnitude(50_000.0) is None               # plausible
    assert implausible_magnitude(20_600_000.0) is not None       # le $20.6M HYPE : carnet a reconcilier


def test_garde_sabstient_sur_magnitude_type_mega():
    """Famille MEGA : un seul sens profitable mais ~$20M (notional impossible) -> abstention magnitude."""
    asks_a = [(1.0, 200_000_000.0)]; bids_a = [(0.99, 200_000_000.0)]   # A ~1.0, TAILLE corrompue (200M)
    asks_b = [(1.02, 200_000_000.0)]; bids_b = [(1.015, 200_000_000.0)]  # B ~1.02 (un seul sens A->B)
    profit, direction, reason = cex_extractable_guarded(
        asks_a, bids_a, asks_b, bids_b, taker=0.001, min_usd=50.0)
    assert profit is None and reason is not None and "reconcilier" in reason


# --- 4. Identite cross-chain par adresse (donnees reelles CTM / VELVET) -------------------------

def test_crosschain_meme_adresse_verified():
    """CTM : MEME contrat (0x..88888888) sur bsc et eth -> identite prouvee par la donnee."""
    verdict, reason = crosschain_identity(CTM_BSC, CTM_ETH, "bsc", "eth")
    assert verdict == "VERIFIED" and reason is None


def test_crosschain_adresses_differentes_unverified():
    """VELVET : contrats DIFFERENTS base/bsc, hors registre -> on NE PEUT PAS prouver -> UNVERIFIED."""
    verdict, reason = crosschain_identity(VELVET_BASE, VELVET_BSC, "base", "bsc")
    assert verdict == "UNVERIFIED" and reason is not None


def test_crosschain_adresse_manquante_unverified():
    """L'ancien collector jetait l'adresse -> ce cas DOIT etre UNVERIFIED (pas un candidat reel)."""
    verdict, reason = crosschain_identity("", VELVET_BSC, "base", "bsc")
    assert verdict == "UNVERIFIED"
