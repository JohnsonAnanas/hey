"""Helpers d'integrite transversaux (Phase 4) : metadonnees de poll + decision d'abstention.

Discipline du projet : un invariant non tenu -> on s'ABSTIENT (pas de chiffre), bruyamment et
trace. Chaque ligne loggee porte sa fraicheur ; un poll incoherent (reorg / bloc illisible) est
abandonne au lieu d'emettre des chiffres douteux.
"""
from __future__ import annotations


def poll_meta(freshness: dict) -> dict:
    """Aplatit la fraicheur d'un poll pour le log : block, quorum (fresh_ok), n_sources, reorg."""
    return {
        "block": freshness.get("block"),
        "fresh_ok": bool(freshness.get("ok")),       # quorum >= 2 fournisseurs d'accord au tip
        "n_sources": freshness.get("n_agree"),
        "reorg": bool(freshness.get("reorg_suspect")),
    }


def poll_should_abstain(freshness: dict) -> str | None:
    """Motif d'abstention du poll ENTIER, ou None.

    - reorg / regression de bloc -> donnees possiblement incoherentes -> abstain.
    - bloc illisible -> on ne sait pas a quel etat on parle -> abstain.
    - quorum perdu (un seul fournisseur) = mode DEGRADE : on continue mais chaque ligne porte
      fresh_ok=False (deja signale au demarrage) ; ce n'est PAS un abstain dur.
    """
    if freshness.get("reorg_suspect"):
        return "regression de bloc (reorg / RPC incoherent)"
    if freshness.get("block") is None:
        return "bloc illisible"
    return None
