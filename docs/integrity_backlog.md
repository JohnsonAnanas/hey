# Backlog d'intégrité — à revisiter

> Reports **assumés** lors de la construction de la couche d'intégrité (cf [`data_integrity.md`](data_integrity.md)).
> Chaque point : pourquoi reporté, le **DÉCLENCHEUR** (l'évènement qui oblige à y revenir), et le
> garde-fou intérimaire. **Rien n'est caché** : tout est flaggé dans les métadonnées (`fee_verified`,
> `fresh_ok`, …) pour ne jamais mordre en silence. Statut : ouvert tant que non traité.

## A. Vraiment reportés (prématuré ET non exposé aujourd'hui)

| # | Sujet | Pourquoi reporté | DÉCLENCHEUR — y revenir quand… | Garde-fou intérimaire |
|---|---|---|---|---|
| **I1** | Quoter cross-check des frais (forks non canoniques) | routers hétérogènes (UniV2 `getAmountsOut` vs Aerodrome `Route[]`) + adresses incertaines = fragile ; venues liquides actuelles déjà vérifiées (UniV2 0.30% fixe, Aerodrome lu on-chain) | on utilise un **fork non canonique** (ex. BaseSwap) comme venue **liquide** | abstain sur toute opp. impliquant `fee_verified=False` (~5 lignes, dispo) |
| **I2** | Détection fee-on-transfer | exige une **simulation de swap** (state-override `eth_call`) ; panier actuel = ERC-20 standard sans taxe | on **élargit aux tokens long-tail / risqués** | panier vetté + denylist curée |
| **I3** | Lecture à **bloc confirmé** (reorg) | en lecture seule l'impact d'un reorg est borné (loggé + régression détectée) | on passe à l'**EXÉCUTION** (envoi de tx réelle) | reorg → abstain du poll (déjà en place) |
| **I6** | **Registre canonique d'identité** (`sim.identity.CANONICAL`) à remplir | une **table de bridge fausse** serait elle-même un bug d'identité → ne rien deviner ; le défaut prudent (UNVERIFIED) ne ment pas | on veut **trader un pair cross-chain à adresses différentes** (ex. VELVET base↔bsc) ou un actif CEX au ticker ambigu | adresse inconnue → `UNVERIFIED` (pas un candidat) ; même contrat cross-EVM → `VERIFIED` sans table |

## B. Limite structurelle (pas un TODO — scope assumé)

| # | Sujet | Nature | Y revenir si… | Garde-fou |
|---|---|---|---|---|
| **I4** | Aveugle au **sub-bloc** | inhérent au polling ; le mempool = autre architecture (searcher MEV) ; ces arbs = course de vitesse perdue pour un solo | on décide de **jouer le jeu MEV** (= changement de projet) | documenté : ne jamais sur-conclure (« 0 dans notre scan » ≠ « 0 existe ») |

## C. Déjà mitigé (cas-limite résiduel)

| # | Sujet | Mitigation en place | Résiduel | Durcissement possible |
|---|---|---|---|---|
| **I5** | Fraîcheur **mono-source** | quorum ≥ 2 (un périmé est attrapé par comparaison) + `fresh_ok=False` par ligne en mode dégradé | un seul RPC ne peut pas s'auto-déclarer périmé | référence externe absolue (explorer / Chainlink) pour le cas 1-source |

---

**Règle de reprise** : avant d'élargir le périmètre (nouveaux forks, tokens risqués, exécution),
relire ce backlog — un déclencheur franchi = le point correspondant **redevient bloquant**.
