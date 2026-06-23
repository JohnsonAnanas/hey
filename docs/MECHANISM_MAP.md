# MECHANISM MAP — carte des mécanismes (MISSION RESET §4/§6)

> On ne scanne pas au hasard. Chaque mécanisme = une **convergence économique explicite** (pourquoi
> deux prix devraient se rejoindre), un **risque**, et un **test minimal**. Une hypothèse est un
> **mécanisme**, jamais un token (§1.2). Un seul track actif à la fois (§1.3).
>
> **Orientation actuelle : track C (funding / cash-and-carry)** — décision utilisateur 2026-06-23
> (`docs/DECISIONS.md`). **Build gelé** jusqu'à validation humaine du mémo (`EVIDENCE_LEDGER.md`).

| Track | Convergence | Risque principal | Test minimal | État |
|---|---|---|---|---|
| **A. Arbitrage atomique intra-chaîne** | Même actif, mêmes pools, dislocation temporaire qui recolle (borne R1). | Course MEV (mort en 1 bloc) ; gaps restent < frais. | 1 `QuotePair` round-trip net à taille, sur paire ancrée. | **REJETÉ_SCOPÉ** (Base majors : 0 net/42k routes). Contrôle, pas priorité. |
| **B. Inventory cross-chain renouvelable** | Bridge/redemption **réel et utilisable** ferme l'écart ; mean-reversion du basis. | Coût/délai de rebalancing ; écart d'exécution ≫ gap mid ; capital immobilisé. | Identité ≥ `ECONOMIC_IDENTITY_CONFIRMED` + 1 `QuotePair` net ≥ coûts de rebalancing. | **REJETÉ_PRÉLIMINAIRE** (VELVET −160 bps, reçu non archivé). CTM = lead. |
| **C. Funding / cash-and-carry** ⭐ | Funding du perp + basis spot↔perp : le **carry** rémunère la détention couverte. | Liquidation, marge, contrepartie/plateforme, retournement de funding, capital immobilisé. | Mécanisme écrit → basis & funding **net** de frais/marge/liquidation/contrepartie/capital sur ≥ 1 régime ; **pas** un AR(1). | **NON_CONCLUANT** — **ORIENTÉ, prochain candidat**. Build gelé (pas d'intégration perp ici). |
| **D. Redemption / peg / wrappers** | Redemption ou ratio **contractuel vérifiable** (le contrat garantit la conversion). | Délai, frais, liquidité, risque du mécanisme/dépeg. | Décote vs ratio contractuel, net du délai et des frais. | Non exploré (CBBTC : redemption à documenter). |
| **E. Event-driven DeFi** | Migration / changement d'incentive / unlock / fin de rewards / dépeg / changement de pool **documenté avant** que le marché le price. | Timing ; le marché a déjà pricé ; exécution. | Le mécanisme est-il documenté **avant** l'événement ? Sinon non éligible. | Non exploré. |
| **F. LP / market-making** | On **encaisse** les frais au lieu de les payer. | **Adverse selection**, volatilité, **impermanent loss** — porte un risque réel. | Modèle de risque dédié (pas un fallback d'arb). | **Projet séparé** (§6.F). Pas adopté comme « autre côté gagnant » d'un arb. |

## Track C — test minimal (décrit, non implémenté)

Avant tout code (perp, executor : **gelés**, §13), le test minimal funding s'écrit ainsi :

1. **Mécanisme de convergence** : long spot + short perp (ou inverse) ; le PnL vient du **funding net**
   du basis, pas d'un signal statistique.
2. **PnL net canonique** (`compute_net_pnl`) = carry encaissé − frais (entrée/sortie spot + perp) −
   coût de marge − provision de liquidation − coût de capital immobilisé − coût de hedge.
3. **Taille** : $100 / $1k / $5k / $10k (courbe capacité → PnL).
4. **Risque** : drawdown mark-to-market, distance à la liquidation, dépendance plateforme/contrepartie.
5. **Verdict** : `NON_CONCLUANT` tant qu'aucun régime hors échantillon n'est mesuré ; jamais
   `QUOTE_POSITIVE` sur un funding moyen historique (~4 %/an) sans série nette de risque.

**Garde-fous** (§13) : pas de nouveau scanner, pas de cross-chain engine, **pas de modèle AR(1) comme
preuve**, pas de LP en fallback, pas d'executor, pas de capital réel. L'activation effective du track
attend la **validation humaine** de l'Evidence Ledger.
