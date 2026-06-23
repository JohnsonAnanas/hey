# DECISIONS — journal des décisions humaines (MISSION RESET §3)

> Trace des décisions **humaines** : date, décision, raison, preuve. Ce que la machine ne tranche pas
> seule (choix de track, reclassements, passages de niveau de preuve) se consigne **ici**, daté.

| Date | Décision | Raison | Preuve / référence |
|---|---|---|---|
| 2026-06-23 | Adopter **Option 1** pour le rangement (documenter, **ne rien déplacer**). | Lisibilité sans casser imports/tests/runners ; pas de refactor avant état de référence testé (§1.10). | `docs/TIDY_PLAN.md` ; structure cible notée comme **aspirationnelle** dans `README.md`. |
| 2026-06-23 | Périmètre du passage MISSION RESET = **docs + code des contrats** (sans aucun moteur). | Mettre en place Evidence Ledger + contrats de données + registre d'identité, en respectant §13. | Plan approuvé ; modules `sim/contracts.py`, `sim/economic_identity.py`, `config/economic_identity.json`. |
| 2026-06-23 | **Orienter** la carte des mécanismes vers le track **C (funding / cash-and-carry)**. | Dernière thèse non conclue restante ; A/B/D rejetés au net exécutable. Build **gelé** jusqu'à validation du mémo. | `docs/MECHANISM_MAP.md` (track C ⭐). |
| 2026-06-23 | Reclasser **VELVET** `REJECTED` → **REJETÉ_PRÉLIMINAIRE**. | Le test LI.FI −160 bps n'a **pas de reçu archivé/hashé** ; sans reçu reproductible, pas de rejet final (§0). | `docs/EVIDENCE_LEDGER.md §2` ; `data/collected/QUARANTINE.md`. |
| 2026-06-23 | Reclasser **CTM** « non-bridgeable/REJETÉ » → **LEAD_NON_RENOUVELABLE_POSSIBLE**. | Même adresse ≠ identité économique prouvée ; **absence d'OFT ≠ absence de tout bridge** → rejet final non justifié. | `config/economic_identity.json` (ctm) ; `docs/EVIDENCE_LEDGER.md`. |
| 2026-06-23 | Reclasser les deux manifests **`VALIDE`** (triage, calibration v3) → **LEAD** / **NON_CONCLUANT**. | `VALIDÉ` est interdit pour un triage / une calibration technique (§2). | `docs/run_manifest_standard.md` ; `manifest.py` (`VERDICTS` sans `VALIDE`). |
| 2026-06-23 | Remplacer la taxonomie de verdict des manifests par celle du MISSION RESET. | Statuts à paliers avec artefacts ; manifests existants **immuables** (non relus). | `manifest.py::VERDICTS/FORBIDDEN_VERDICTS` ; `tests/test_manifest_verdicts.py`. |
| 2026-06-23 | Exiger un **`evidence_hash`** réel pour `ECONOMIC_IDENTITY_CONFIRMED`+ et les gates inventory ; ajouter le plancher **`IDENTITY_PRELIMINARY`**. | Un `evidence_url` est un pointeur, pas un reçu : une identité affirmée en live sans reçu hashé reste préliminaire (§0). **VELVET y retombe → hors inventory** jusqu'au reçu LI.FI archivé+hashé. | `sim/economic_identity.py` (load_registry, gates) ; `config/economic_identity.json` (velvet) ; `tests/test_economic_identity.py`. |
| 2026-06-23 | **Réconcilier la formule de PnL net à 7 termes** (+ hedge, + provision de risque opérationnel) partout. | Aligner la formule unique sur MISSION RESET §7 ; le track funding (C) a le hedge comme coût central. **Pas de zéro silencieux** : None ⇒ abstention, `0.0` explicite par le caller. | `sim/contracts.py::compute_net_pnl` ; `docs/STATE.md §6` ; `docs/GLOSSARY.md`. |
| 2026-06-23 | **Imposer le refus d'un verdict interdit à l'écriture** d'un manifeste (pas seulement au CLI). | `write_manifest` (API runners) écrivait le verdict sans contrôle ; `VALIDE`/hors-taxonomie doivent lever (§2). | `manifest.py::_check_verdict` (appelé par `build`) ; `tests/test_manifest_verdicts.py`. |

## En attente de décision humaine (après validation du mémo)
- **Valider l'Evidence Ledger** (`docs/EVIDENCE_LEDGER.md`) — porte avant tout nouveau moteur (§2).
- **Archiver le reçu VELVET** (LI.FI brut + hash via manifest) pour figer `REJETÉ_PRÉLIMINAIRE`.
- **Activer le track C** (funding) et écrire son mécanisme de convergence avant tout code perp.
- **Un unique `QuotePair` test** sur le track choisi, avec reçus archivés (§12.6).
