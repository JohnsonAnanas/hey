# D2B2-v2 — transport async borné (limiteur CUPS) + fidélité REGLE 3 corrigée

> **Pourquoi cette révision.** La première tentative v2 (JSON-RPC **batch**) a contaminé le lot 0 (~68 %) :
> les gros batchs override-heavy saturaient le **rate-limit PAR SECONDE** d'Alchemy (CUPS) → réponses vides +
> 429 « compute units per second ». Pire, un **bug de fidélité latent (partagé avec v1)** transformait
> **silencieusement** un `getCode` échoué en faux « pool absent » (WINDOW_UNAVAILABLE). Les deux sont corrigés
> ici (réouverture validée de la règle 3). Lot 0 v2 reste en quarantaine `NON_CONCLUANT`, jamais fusionné.

## Correction 1 — FIDÉLITÉ (jamais de compensation silencieuse)
Fonctions **pures** partagées (`d2b2_measure.py`), utilisées par **v1 et v2** :
- `pool_state(result, error, infra)` → `present` / `absent` / **`infra`**. `absent` **uniquement** si `getCode`
  réussit et renvoie explicitement `0x`. Tout échec transport/CUPS/erreur RPC/résultat absent → `infra`.
- `exec_state(result, error, infra)` → `ok` / `revert` (échec déterministe = capacité) / `infra`.
- `classify_cycle2(uni, slip, exec, anchor_ok, gas_ok)` → `ok` / `CAPACITY` / `WINDOW_UNAVAILABLE` /
  **`NON_CONCLUANT_INFRA`**. L'**infra prime** : on ne conclut jamais absence/capacité sur information
  incomplète. Oracle/gas/getBlock/getL1Fee manquant → `NON_CONCLUANT_INFRA` (**jamais gas=0**).

## Correction 2 — TRANSPORT (`cups_transport.py`)
Plus de batch burst. Chaque appel passe par :
- un **limiteur token-bucket CU/seconde** (`CupsLimiter`) réglé **avant** le run (par benchmark) ;
- une **concurrence bornée** : `concurrency=1` = référence séquentielle, `K` = production. Le résultat d'un
  appel ne dépend que de `(method, params, blockTag)` → **identique quelle que soit la concurrence**.
- détection CUPS/vide/429 → **retries avec backoff, toujours archivés** ; après épuisement → `infra=True`
  (le cycle devient `NON_CONCLUANT_INFRA`, **jamais** un faux « absent »).

`measure_cycles(...)` (unifiée, dans `d2b2v2_measure.py`) : 3 rounds/bloc au **même `blockTag=b`** —
R1 `getCode`+`getBlock`+oracle ; R2 `eth_call`(exec)+`estimateGas` (cycles 2 pools présents) ; R3 `getL1Fee`.

## Politique de lot (règle 3)
Un **seul** cycle `NON_CONCLUANT_INFRA` (après retries) ⇒ verdict **`LOT_NON_CONCLUANT_RETRY_REQUIRED`**.
Jamais de lot partiellement contaminé accepté. Reprise = **re-run ENTIER** du lot (mêmes blocs/params/endpoint,
throttle plus bas) ; **jamais** de fusion partiel ↔ reprise. Namespace distinct (`data/raw/defi/d2b2v2/`).

## Benchmark durci AVANT toute série (`d2b2_bench.py`)
- **Chemin succès + équivalence** : `measure_cycles` concurrency=1 vs K → résultats byte/identiques.
- **B1 connu vivant** : au bloc B1, les routes du lot 0 (prouvées vivantes en D2B-1) ne deviennent **jamais**
  WINDOW_UNAVAILABLE.
- **Débit soutenable sans erreur** : rampe de `(cups, concurrency)` → plus haut débit avec **0 erreur / 0
  infra** → throttle recommandé + **ETA réelle** (par lot / 29 lots) + CUPS observée (estimée).
- **Chemin d'échec** (`getCode` None/0x/empty/CUPS → INFRA, jamais faux absent/gas=0) couvert par les tests
  **offline** `test_d2b2_fidelity.py` + `test_cups_transport.py` (injection déterministe).

Aucun résultat économique n'est interprété pendant le benchmark. La série complète (29 lots, ordre gelé) ne
relance **que sur nouvelle validation**.
