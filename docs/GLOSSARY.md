# GLOSSARY — vocabulaire économique (MISSION RESET §3)

> Définitions courtes et **non ambiguës**. Aligné sur la formule canonique (`docs/STATE.md §6`,
> `sim/contracts.py::compute_net_pnl`) et `docs/formulas.md`. Un mot mal défini = une conclusion
> fausse (leçon CBBTC : « médiane » ≠ « live exécutable »).

| Terme | Définition | Ce que ce n'est PAS |
|---|---|---|
| **gap** | Écart de prix affiché entre deux venues, en bps. Niveau de preuve **0**. | Pas un profit. Un gap durable est une **friction à expliquer** (§1.9), pas un PnL. |
| **mid** | Moyenne (bid+ask)/2 ou prix de pool sans taille. Indicatif. | Pas exécutable : on ne trade jamais au mid (cf VELVET : mid 29 bps vs exécution −160 bps). |
| **quote** | `amountOut` **réel pour une taille donnée** (quote on-chain QuoterV2, math AMM exacte, ou API agrégateur). Niveau **1**. Objet : `sim/contracts.py::RawQuote`. | Pas un mid. Une quote sans taille n'est pas une quote. |
| **PnL quote (brut)** | `vente exécutable − achat exécutable`, **avant** frais/gas/rebalancing. | Pas le résultat : le brut est presque toujours positif ; seul le **net** tranche. |
| **PnL net** | `brut − frais − gas − rebalancing amorti − coût de capital` (formule **unique**, `compute_net_pnl`). Niveau **2** si positif à taille définie. | Jamais une somme d'opportunités au même instant (capital/liquidité partagés). |
| **capacity** | Taille max (USD) où le **net reste > 0**. Une opportunité qui meurt à $200 est `CAPACITY_INSUFFICIENT` (poussière), pas une stratégie (§8). | Pas la liquidité du pool. Pas la taille optimale. |
| **inventory** | Soldes réels (stable + token) détenus par venue/chaîne qui **contraignent** une capture. Objet : `sim/contracts.py::InventoryState`. | Pas « capital infini » : un signal sans solde/route disponible est **rejeté** (§10). |
| **rebalancing** | Action de remettre l'inventaire en place après un trade (bridge / redemption / transfert), avec **coût, délai, limites**. | Pas gratuit ni instantané. Le bridge VELVET coûtait ~3 bps (pas le tueur) ; le tueur était l'exécution. |
| **same-time tolerance** | Écart maximal (s ou blocs) toléré entre la quote d'achat et celle de vente d'une `QuotePair`. | Pas « à peu près en même temps » : deux quotes décalées ne forment pas une paire valide. |
| **abstention** | Absence de donnée → on s'abstient, motif loggé. **Jamais** un fallback silencieux (§1.7). Codé : `build_quote_pair` met `net=NaN`, `confidence=0`, `missing_fields`. | Pas un 0 inventé à la place d'une valeur manquante. |
| **identité (3 niveaux)** | `CONTRACT_SAME` < `ECONOMIC_IDENTITY_CONFIRMED` < `REBALANCING_CONFIRMED` — **jamais équivalents** (`sim/economic_identity.py`). | Une même adresse ne prouve **pas** l'identité économique ni le rebalancing (leçon CTM). |
| **niveau de preuve** | Échelle 0→6 (prix → … → pilote capital). Aucun passage sans artefacts **et** décision humaine (§8). | Pas un sentiment (« prometteur ») : un cran de preuve a un artefact. |
| **borne supérieure** | Un résultat de quote/backfill ne voit ni l'intra-bloc ni le MEV : il **majore** l'edge réel. | Pas une garantie : un net positif en borne sup. peut être négatif en réel. |
