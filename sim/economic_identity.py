"""Registre d'identite ECONOMIQUE (MISSION RESET — Phase 3). Une adresse ne suffit pas : trois
niveaux PROUVES DISTINCTS, jamais equivalents (cahier des charges §5), plus un plancher honnete :

  IDENTITY_PRELIMINARY       : identite AFFIRMEE (ex. en live) mais PAS encore prouvee par un recu
                               archive+hashe. N'ouvre AUCUN gate. Foyer tracable (route, prochaine
                               mesure) sans surclasser la preuve — ex. VELVET avant reçu LI.FI hashe.
  CONTRACT_SAME              : meme contrat prouvable par la donnee (meme adresse cross-EVM) ou table
                               canonique. NE PROUVE PAS que c'est le meme actif economique.
  ECONOMIC_IDENTITY_CONFIRMED: identite economique prouvee, RECU ARCHIVE+HASHE a l'appui (evidence_hash).
  REBALANCING_CONFIRMED      : route de bridge/redemption REELLE et utilisable (cout/delai/limites),
                               recu archive+hashe a l'appui.

Gardes d'usage (§5) :
  - recherche inventory  : seulement si >= ECONOMIC_IDENTITY_CONFIRMED ET evidence_hash present.
  - paper trading        : seulement si REBALANCING_CONFIRMED ET evidence_hash present.
`evidence_url` reste un pointeur utile mais n'est JAMAIS une preuve suffisante : seul un `evidence_hash`
(recu reproductible) ouvre les paliers economiques (§0 : sans recu reproductible => PRELIMINAIRE).

Lecon CTM : meme adresse (CONTRACT_SAME) n'implique NI identite economique NI rebalancing — et
l'absence d'OFT n'est PAS une preuve d'absence de tout bridge. Lecon VELVET : une identite affirmee
en live (LI.FI) sans reçu archive reste IDENTITY_PRELIMINARY (cf docs/EVIDENCE_LEDGER.md). On reutilise
sim.identity.crosschain_identity pour le niveau CONTRACT_SAME (source unique, pas de redefinition).
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass

from .identity import crosschain_identity

# Statut PLANCHER explicite : identite affirmee, PAS prouvee par un recu hashe. Rang -1 (sous tout),
# n'ouvre aucun gate. Les TROIS paliers prouves (ordonnes) suivent.
IDENTITY_PRELIMINARY = "IDENTITY_PRELIMINARY"
CONTRACT_SAME = "CONTRACT_SAME"
ECONOMIC_IDENTITY_CONFIRMED = "ECONOMIC_IDENTITY_CONFIRMED"
REBALANCING_CONFIRMED = "REBALANCING_CONFIRMED"
LEVELS = (CONTRACT_SAME, ECONOMIC_IDENTITY_CONFIRMED, REBALANCING_CONFIRMED)   # paliers PROUVES, ordonnes
ALLOWED_STATUSES = (IDENTITY_PRELIMINARY,) + LEVELS
_RANK = {s: i for i, s in enumerate(LEVELS)}   # IDENTITY_PRELIMINARY absent => rank -1 (sous tout)

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_REGISTRY = os.path.join(_HERE, "config", "economic_identity.json")


@dataclass(frozen=True)
class EconomicAsset:
    """Entree canonique versionnee (par adresse, jamais devine). `status` = plus haut niveau
    REELLEMENT prouve avec artefact ; tout le reste documente la route officielle et ses risques."""
    economic_asset_id: str
    project: str
    token_addresses: dict          # {chain: adresse(lower)}
    contract_verification_source: str
    bridge_route: str
    source_chain: str
    destination_chain: str
    bridge_fee_bps: float | None
    min_usd: float | None
    max_usd: float | None
    delay: str
    limits: str
    risks: str
    verified_utc: str
    evidence_url: str | None
    evidence_hash: str | None
    status: str
    next_measure: str = ""
    notes: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def rank(self) -> int:
        return _RANK.get(self.status, -1)

    def at_least(self, level: str) -> bool:
        return self.rank >= _RANK.get(level, -1)


def contract_same(asset: EconomicAsset) -> bool:
    """Vrai si l'identite de CONTRAT est prouvable par la donnee (meme adresse cross-EVM, ou table
    canonique), via sim.identity.crosschain_identity. NE PROUVE PAS l'identite economique (defaut
    prudent : un statut superieur exige une preuve archivee, jamais une deduction d'adresse)."""
    items = list(asset.token_addresses.items())
    if len(items) < 2:
        return False
    (c_lo, a_lo), (c_hi, a_hi) = items[0], items[1]
    verdict, _ = crosschain_identity(a_lo, a_hi, c_lo, c_hi)
    return verdict == "VERIFIED"


def load_registry(path: str = DEFAULT_REGISTRY) -> dict[str, EconomicAsset]:
    """Charge + VALIDE le registre versionne. Refuse (leve) toute entree qui affirme un statut sans la
    preuve correspondante :
      - IDENTITY_PRELIMINARY : plancher honnete (identite affirmee, non prouvee) — aucun pre-requis,
        mais n'ouvre aucun gate.
      - CONTRACT_SAME : exige une identite de CONTRAT prouvable par les adresses (meme adresse cross-EVM
        / table canonique). Reproductible depuis la donnee, donc pas de recu separe requis.
      - ECONOMIC_IDENTITY_CONFIRMED / REBALANCING_CONFIRMED : exigent un evidence_hash REEL (recu
        archive ET hashe). `evidence_url` seul est un pointeur, JAMAIS une preuve suffisante (lecon
        VELVET : identite affirmee en live sans recu hashe => reste IDENTITY_PRELIMINARY)."""
    with open(path, encoding="utf-8") as fh:
        raw = json.load(fh)
    out: dict[str, EconomicAsset] = {}
    for aid, rec in raw.get("assets", {}).items():
        rec = {k: v for k, v in rec.items() if not k.startswith("_")}
        asset = EconomicAsset(**rec)
        if asset.status not in ALLOWED_STATUSES:
            raise ValueError(f"{aid}: statut '{asset.status}' invalide (attendu un de {ALLOWED_STATUSES})")
        same = contract_same(asset)
        has_hash = bool(asset.evidence_hash)
        if asset.status == CONTRACT_SAME and not same:
            raise ValueError(
                f"{aid}: statut CONTRACT_SAME mais identite de contrat NON prouvee par les adresses "
                f"({asset.token_addresses}) -> refus (pas de statut sans preuve)")
        if asset.status in (ECONOMIC_IDENTITY_CONFIRMED, REBALANCING_CONFIRMED) and not has_hash:
            raise ValueError(
                f"{aid}: statut '{asset.status}' exige un evidence_hash reel (recu archive+hashe) ; "
                f"evidence_url seul est un pointeur, pas une preuve -> refus (identite non prouvee, "
                f"reste IDENTITY_PRELIMINARY jusqu'au recu hashe)")
        out[aid] = asset
    return out


def eligible_for_inventory_research(asset: EconomicAsset) -> bool:
    """§5 : un actif n'entre en recherche inventory que s'il est >= ECONOMIC_IDENTITY_CONFIRMED ET
    porte un recu archive+hashe (evidence_hash). Un pointeur (evidence_url) ne suffit jamais — garde
    redondante avec load_registry, pour le cas d'un EconomicAsset construit directement (lecon VELVET)."""
    return asset.at_least(ECONOMIC_IDENTITY_CONFIRMED) and bool(asset.evidence_hash)


def eligible_for_paper_trading(asset: EconomicAsset) -> bool:
    """§5 : un actif ne passe en paper trading que si le rebalancing est confirme (REBALANCING_CONFIRMED),
    recu hashe a l'appui."""
    return asset.at_least(REBALANCING_CONFIRMED) and bool(asset.evidence_hash)


def canonical_from_registry(registry: dict[str, EconomicAsset]) -> dict[str, dict[str, str]]:
    """Construit la table {project_id: {chain: adresse}} (schema de sim.identity.CANONICAL) depuis le
    registre, pour une SOURCE UNIQUE. N'altere pas les gardes existantes : a brancher explicitement
    si/quand on decide de remplir sim.identity.CANONICAL (sans jamais deviner une adresse)."""
    return {aid: {c: a.lower() for c, a in asset.token_addresses.items()}
            for aid, asset in registry.items()}
