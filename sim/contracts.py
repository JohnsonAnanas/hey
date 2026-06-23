"""Contrats de donnees normalises (MISSION RESET — Phase 2). Toute observation economique future
passe par CES objets, jamais par un dict ad hoc : une quote brute hashee (`RawQuote`), une paire
achat/vente chiffree au net (`QuotePair`), un etat d'inventaire (`InventoryState`).

Deux principes du cahier des charges sont CODES ici, pas seulement documentes :
- Formule de PnL net UNIQUE et canonique (docs/STATE.md §6 == MISSION RESET §7) : `compute_net_pnl`,
  7 termes (gross - fees - gas - rebalancing - capital - hedge - provision_risque_op). Aucun autre chemin.
- ABSTENTION jamais fallback silencieux (regle non negociable §7) : un champ de cout manquant (None)
  ou une jambe sans `amount_out` (>0) => net = NaN, confidence = 0, `missing_fields` peuple. On
  n'invente JAMAIS un 0 a la place d'une donnee absente. `hedge_usd` / `op_risk_provision_usd` n'ont
  AUCUN defaut a zero : un cout applicable mais inconnu se passe en None (abstention), un 0.0 doit
  etre explicite et justifie par le caller.

PUR / testable (aucun reseau). Style aligne sur les dataclasses frozen existantes
(`QuotedDecision` dans sim/route_quoted.py, `CycleEval` dans sim/amm_v2.py).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass

_NAN = float("nan")


def content_hash(payload) -> str:
    """sha256 deterministe d'un payload (request/response brut). Canonicalise (cles triees, compact)
    pour que la MEME donnee donne TOUJOURS la meme empreinte — meme role que sha256_file dans
    manifest.py, porte aux objets en memoire (la brute fait foi par son hash)."""
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


# === 1. RawQuote : une quote executable brute, archivable et hashee =============================

@dataclass(frozen=True)
class RawQuote:
    """Quote brute d'UNE jambe (venue, sens, taille). Identite par ADRESSE (jamais ticker, cf
    sim/identity.py). `amount_*` en wei. Aucune statistique de basis ne doit etre calculee avant
    qu'une quote soit ainsi stockee/hashee (cahier des charges §4)."""
    venue: str
    venue_type: str               # 'dex' | 'cex' | 'aggregator' | 'bridge'
    chain: str
    asset_in_address: str
    asset_in_decimals: int
    asset_out_address: str
    asset_out_decimals: int
    amount_in: int                # wei
    amount_out: int               # wei (<= 0 => jambe non remplie / revert => ABSTENTION)
    source: str                   # provenance brute (URL / endpoint / RPC)
    wall_clock_utc: str
    request_hash: str
    response_hash: str
    block_number: int | None = None
    server_timestamp: str | None = None
    route: str = ""
    pool_or_market_id: str = ""
    fee: float | None = None      # frais connus de la jambe (fraction, ex. 0.0005), ou None si inconnu
    gas_estimate: int | None = None

    def to_dict(self) -> dict:
        return asdict(self)


# === 2. QuotePair : le SEUL resultat economique recevable (deux quotes, net de tout) ============

# Champs de cout REQUIS pour conclure : leur absence (None) declenche l'abstention (jamais un 0).
# hedge_usd / op_risk_provision_usd y figurent => le caller DOIT les fournir (0.0 explicite ou valeur),
# jamais un defaut silencieux a zero (MISSION RESET §7).
_REQUIRED_COSTS = ("gross_pnl_usd", "fees_usd", "gas_usd", "hedge_usd", "op_risk_provision_usd")


@dataclass(frozen=True)
class QuotePair:
    """Resultat economique canonique : meme actif certifie + buy executable + sell executable, net de
    TOUS les couts. `net_pnl_usd` provient EXCLUSIVEMENT de `compute_net_pnl`. Construire via
    `build_quote_pair` (applique la garde d'abstention)."""
    asset_economic_id: str
    buy: RawQuote
    sell: RawQuote
    direction: str
    size_usd: float
    same_time_tolerance: float    # ecart tolere (s ou blocs) entre les deux quotes
    gross_pnl_usd: float          # vente executable - achat executable (pre-couts)
    fees_usd: float
    gas_usd: float
    rebalancing_usd: float        # bridge amorti (0 explicite pour l'atomique mono-chaine)
    capital_usd: float            # cout du capital immobilise
    hedge_usd: float              # cout de couverture (central pour le track funding ; 0.0 explicite sinon)
    op_risk_provision_usd: float  # provision de risque operationnel (liquidation/plateforme/incident)
    net_pnl_usd: float            # = compute_net_pnl(...) ; NaN si abstention
    confidence: float             # 1.0 complet, 0.0 si un champ requis manque
    missing_fields: tuple[str, ...]

    def to_dict(self) -> dict:
        return asdict(self)


def compute_net_pnl(gross_pnl_usd: float, fees_usd: float, gas_usd: float,
                    rebalancing_usd: float = 0.0, capital_usd: float = 0.0, *,
                    hedge_usd: float, op_risk_provision_usd: float) -> float:
    """Formule de PnL net UNIQUE et canonique (docs/STATE.md §6 == MISSION RESET §7) :

        net = gross - frais - gas - rebalancing - capital - hedge - provision_risque_operationnel

    `gross_pnl_usd` = (vente - achat) executables. `hedge_usd` et `op_risk_provision_usd` sont REQUIS
    (keyword-only, AUCUN defaut a zero) : un cout applicable mais inconnu se passe en None et declenche
    l'abstention (cf build_quote_pair) ; un 0.0 doit etre explicite et justifie par le caller. Aucun
    autre chemin de calcul du net n'est legitime.
    """
    return (gross_pnl_usd - fees_usd - gas_usd - rebalancing_usd - capital_usd
            - hedge_usd - op_risk_provision_usd)


def build_quote_pair(*, asset_economic_id: str, buy: RawQuote, sell: RawQuote, direction: str,
                     size_usd: float, same_time_tolerance: float,
                     gross_pnl_usd: float | None, fees_usd: float | None, gas_usd: float | None,
                     hedge_usd: float | None, op_risk_provision_usd: float | None,
                     rebalancing_usd: float | None = 0.0, capital_usd: float | None = 0.0) -> QuotePair:
    """Construit un `QuotePair` en appliquant la garde d'ABSTENTION (§7). Si un champ de cout requis
    est None, OU si une jambe n'a pas de sortie (`amount_out <= 0`) : net = NaN, confidence = 0,
    `missing_fields` liste les manques — jamais un 0 invente. Sinon : net = `compute_net_pnl`,
    confidence = 1.0. `hedge_usd` / `op_risk_provision_usd` sont requis (pas de defaut) : un 0.0 est
    une decision EXPLICITE du caller, un None (cout applicable mais inconnu) declenche l'abstention."""
    comp = {"gross_pnl_usd": gross_pnl_usd, "fees_usd": fees_usd, "gas_usd": gas_usd,
            "hedge_usd": hedge_usd, "op_risk_provision_usd": op_risk_provision_usd,
            "rebalancing_usd": rebalancing_usd, "capital_usd": capital_usd}
    missing = [k for k in _REQUIRED_COSTS if comp[k] is None]
    if comp["rebalancing_usd"] is None:
        missing.append("rebalancing_usd")
    if comp["capital_usd"] is None:
        missing.append("capital_usd")
    if buy.amount_out is None or buy.amount_out <= 0:
        missing.append("buy.amount_out")
    if sell.amount_out is None or sell.amount_out <= 0:
        missing.append("sell.amount_out")
    missing = tuple(dict.fromkeys(missing))   # dedup en gardant l'ordre

    def _v(x):
        return _NAN if x is None else x

    if missing:
        return QuotePair(asset_economic_id, buy, sell, direction, size_usd, same_time_tolerance,
                         _v(gross_pnl_usd), _v(fees_usd), _v(gas_usd), _v(rebalancing_usd),
                         _v(capital_usd), _v(hedge_usd), _v(op_risk_provision_usd), _NAN, 0.0, missing)
    net = compute_net_pnl(gross_pnl_usd, fees_usd, gas_usd, rebalancing_usd, capital_usd,
                          hedge_usd=hedge_usd, op_risk_provision_usd=op_risk_provision_usd)
    return QuotePair(asset_economic_id, buy, sell, direction, size_usd, same_time_tolerance,
                     gross_pnl_usd, fees_usd, gas_usd, rebalancing_usd, capital_usd,
                     hedge_usd, op_risk_provision_usd, net, 1.0, ())


# === 3. InventoryState : soldes/capacite/rebalancing reels d'une venue ==========================

@dataclass(frozen=True)
class InventoryState:
    """Etat d'inventaire d'un actif sur une venue/chaine : ce qui CONTRAINT reellement une capture
    (un signal sans solde disponible, sans profondeur ou sans route de rebalancing est rejete — §10)."""
    asset: str
    chain: str
    venue: str
    stable_balance: float
    token_balance: float
    available_capacity: float
    rebalancing_path: str
    rebalancing_cost: float
    rebalancing_delay: str
    inventory_imbalance: float
    maximum_adverse_exposure: float

    def to_dict(self) -> dict:
        return asdict(self)
