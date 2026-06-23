"""Registre d'identite ECONOMIQUE (MISSION RESET — Phase 3). Une adresse ne suffit pas : trois
niveaux DISTINCTS, jamais equivalents (cahier des charges §5) :

  CONTRACT_SAME              : meme contrat prouvable par la donnee (meme adresse cross-EVM) ou table
                               canonique. NE PROUVE PAS que c'est le meme actif economique.
  ECONOMIC_IDENTITY_CONFIRMED: identite economique prouvee (meme emetteur / redemption), reçu a l'appui.
  REBALANCING_CONFIRMED      : route de bridge/redemption REELLE et utilisable (cout/delai/limites connus).

Gardes d'usage (§5) :
  - recherche inventory  : seulement si >= ECONOMIC_IDENTITY_CONFIRMED.
  - paper trading        : seulement si REBALANCING_CONFIRMED.

Lecon CTM : meme adresse (CONTRACT_SAME) n'implique NI identite economique NI rebalancing — et
l'absence d'OFT n'est PAS une preuve d'absence de tout bridge. Lecon VELVET : une identite affirmee
en live (LI.FI) sans reçu archive reste a figer (cf docs/EVIDENCE_LEDGER.md). On reutilise
sim.identity.crosschain_identity pour le niveau CONTRACT_SAME (source unique, pas de redefinition).
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass

from .identity import crosschain_identity

CONTRACT_SAME = "CONTRACT_SAME"
ECONOMIC_IDENTITY_CONFIRMED = "ECONOMIC_IDENTITY_CONFIRMED"
REBALANCING_CONFIRMED = "REBALANCING_CONFIRMED"
LEVELS = (CONTRACT_SAME, ECONOMIC_IDENTITY_CONFIRMED, REBALANCING_CONFIRMED)
_RANK = {s: i for i, s in enumerate(LEVELS)}

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
        return self.rank >= _RANK[level]


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
      - CONTRACT_SAME : exige une identite de CONTRAT prouvable par les adresses (meme adresse cross-EVM
        / table canonique). Sinon c'est une affirmation d'identite non prouvee.
      - ECONOMIC_IDENTITY_CONFIRMED / REBALANCING_CONFIRMED : exige SOIT l'identite de contrat, SOIT une
        preuve archivee (`evidence_url`/`evidence_hash`, ex. doc de bridge officielle pour des adresses
        DIFFERENTES comme VELVET/USDC). Une preuve sans hash reste PRELIMINAIRE (cf EVIDENCE_LEDGER)
        mais n'est pas rejetee ici."""
    with open(path, encoding="utf-8") as fh:
        raw = json.load(fh)
    out: dict[str, EconomicAsset] = {}
    for aid, rec in raw.get("assets", {}).items():
        rec = {k: v for k, v in rec.items() if not k.startswith("_")}
        asset = EconomicAsset(**rec)
        if asset.status not in LEVELS:
            raise ValueError(f"{aid}: statut '{asset.status}' invalide (attendu un de {LEVELS})")
        same = contract_same(asset)
        has_proof = bool(asset.evidence_url) or bool(asset.evidence_hash)
        if asset.status == CONTRACT_SAME and not same:
            raise ValueError(
                f"{aid}: statut CONTRACT_SAME mais identite de contrat NON prouvee par les adresses "
                f"({asset.token_addresses}) -> refus (pas de statut sans preuve)")
        if asset.status in (ECONOMIC_IDENTITY_CONFIRMED, REBALANCING_CONFIRMED) and not (same or has_proof):
            raise ValueError(
                f"{aid}: statut '{asset.status}' sans identite de contrat NI preuve archivee "
                f"(evidence_url/evidence_hash) -> refus (identite economique non prouvee)")
        out[aid] = asset
    return out


def eligible_for_inventory_research(asset: EconomicAsset) -> bool:
    """§5 : un actif n'entre en recherche inventory que s'il est >= ECONOMIC_IDENTITY_CONFIRMED."""
    return asset.at_least(ECONOMIC_IDENTITY_CONFIRMED)


def eligible_for_paper_trading(asset: EconomicAsset) -> bool:
    """§5 : un actif ne passe en paper trading que si le rebalancing est confirme."""
    return asset.at_least(REBALANCING_CONFIRMED)


def canonical_from_registry(registry: dict[str, EconomicAsset]) -> dict[str, dict[str, str]]:
    """Construit la table {project_id: {chain: adresse}} (schema de sim.identity.CANONICAL) depuis le
    registre, pour une SOURCE UNIQUE. N'altere pas les gardes existantes : a brancher explicitement
    si/quand on decide de remplir sim.identity.CANONICAL (sans jamais deviner une adresse)."""
    return {aid: {c: a.lower() for c, a in asset.token_addresses.items()}
            for aid, asset in registry.items()}
