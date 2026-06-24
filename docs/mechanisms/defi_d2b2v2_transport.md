# D2B2-v2 — changement de TRANSPORT RPC (sémantique inchangée)

> Suite à l'arrêt volontaire de performance (`D2B2_ABORTED_PERFORMANCE`), D2B2-v2 accélère **uniquement le
> transport RPC**. **Sémantique strictement identique à v1** (`d2b2_measure.py` @938b6a5) : mêmes routes,
> ordre gelé, fenêtre [B1−299, B1], tailles, exécuteur, state-overrides, oracle Chainlink, catégories et
> schéma raw. **Aucune baisse de fidélité.**

## Ce qui change (transport seul)
- **JSON-RPC batch** (supporté par Alchemy : un POST = N requêtes, vérifié read-only).
- **IDs de requêtes stables** ; réponses **réordonnées de manière déterministe par id** (`reorder_by_id`).
- Chunks `≤ BATCH_CHUNK` (override-heavy → conservateur) ; **retries et erreurs de transport toujours
  archivés** dans le raw.
- 2 rounds batchés par bloc : (A) `getCode` + `getBlock` + oracle + `eth_call` + `eth_estimateGas` ;
  (B) `getL1Fee` (dépend de `gas_units` de A). **Tous au MÊME `blockTag=b`.**

## Ce qui NE change PAS (fidélité)
- Mêmes appels, mêmes paramètres, même `blockTag=b` pour `eth_call`/`estimateGas`/`getL1Fee`/oracle ; même
  `serialize_dummy_1559(gas_units, …)` → **mêmes octets, mêmes résultats**. Réutilise les **fonctions PURES
  de v1** (`window_blocks`, `anchor_eth_usd`, `gas_normal_usdc`, `upper_bound_usdc`, `classify_cycle`).
- Namespace **distinct** (`*_d2b2v2-measure-lotNN`, `data/raw/defi/d2b2v2/`) → jamais mélangé avec les
  partiels classés `D2B2_ABORTED_PERFORMANCE`.

## Garantie avant run complet
`d2b2_bench.py` compare **résultat-à-résultat** la référence séquentielle v1-exacte (`measure_seq_ref`) et
la mesure batchée v2 (`measure_batched`) sur un **petit ensemble préenregistré** ; verdict `EQUIVALENT` requis
(byte/résultat identiques) avant toute relance de la série. Le benchmark mesure aussi débit, erreurs et **ETA
réelle** ; **aucun résultat économique n'y est interprété**. La série complète (29 lots, ordre gelé) ne
relance **que sur validation**.
