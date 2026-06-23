# Mémo de mécanisme — Funding / cash-and-carry (track C)

> **Statut : `NON_CONCLUANT`.** Ce mémo **décrit le mécanisme et ce qui devra être mesuré** ; il **ne
> conclut pas** qu'une stratégie est rentable. **Aucun rendement n'est estimé ici.** Build **gelé**
> (§13 : aucun moteur, collecteur, backfill, executor, ni capital). Aligné sur `docs/MECHANISM_MAP.md`
> (track C ⭐), `docs/EVIDENCE_LEDGER.md` (funding = `NON_CONCLUANT`), `docs/GLOSSARY.md`, et la formule
> canonique `sim/contracts.py::compute_net_pnl` (7 termes).
>
> Règle dure (doctrine) : **aucun zéro implicite**. Tout terme de coût est soit **mesuré**, soit
> **`None` (inconnu) ⇒ abstention**, soit **`0.0` explicite et justifié par le caller**. Un funding
> observé est un **flux potentiel**, jamais un rendement net.

## 1. Le mécanisme unique décrit ici

Un seul mécanisme (§1.2/§1.3 : une hypothèse = un mécanisme ; un seul track actif).

- **Jambe spot** — détention **longue** de l'actif sous-jacent `S` sur une venue spot `V_spot` (DEX
  on-chain ou CEX), à notionnel `N`.
- **Jambe perp** — **short** du perpétuel du même sous-jacent `S` sur une venue `V_perp`, notionnel
  `−N` → position **delta-neutre** (`Δ ≈ 0`).
- **Sens du funding recherché** — on encaisse le funding quand **les longs paient les shorts** (funding
  **positif**, convention « long-paie-short »). Étant **short perp**, on **reçoit** ce funding. La
  **condition d'entrée** (signe + persistance exigés) n'est **pas un acquis** : elle doit être fixée par
  une **règle préenregistrée** (gate §5.3) **avant toute mesure**. Le mécanisme symétrique (shorts
  paient longs → short spot / long perp) n'est **pas décrit ici** : un seul mécanisme.
- **Conditions de convergence** — le PnL vient du **funding net encaissé pendant la détention
  couverte**, pas d'un pari directionnel (`Δ ≈ 0`). Le funding **incite** les acteurs à arbitrer le
  basis `perp − spot`, **mais ne garantit aucune convergence** : le basis peut rester non nul, voire
  diverger, à l'entrée comme à la sortie. La thèse n'est valide que si, **net de tous les coûts**, le **funding reçu + (basis_entrée −
  basis_sortie)** (avec `basis = perp − spot`) dépasse le coût de portage — **une hausse du basis à la
  sortie est une perte**.
- **Maintien du hedge** — delta-neutralité `notional_spot ≈ notional_perp` :
  - **suivi de marge** sur la jambe perp (ajout/retrait de collatéral pour tenir la distance à la
    liquidation) ;
  - **réajustement du ratio** quand le prix dérive (les notionnels des deux jambes divergent) ;
  - chaque ajustement a un **coût** (frais + gas/transferts) → terme *rebalancing* (§2.4).
- **Mode de clôture** — déboucler **les deux jambes** (vendre spot **et** clôturer le short perp),
  idéalement **simultanément** pour ne pas rouvrir de delta. Déclencheurs définis **avant** l'ouverture :
  funding devenu **négatif/instable**, basis qui dérive au-delà d'un seuil, **marge** sous tension,
  **capacité/horizon** atteints. La clôture porte son propre coût d'exécution (frais + gas/retraits +
  slippage), compté dans les termes du §2.

## 2. PnL net — formule canonique à 7 termes (appliquée)

`net = brut − frais − gas − rebalancing − capital − hedge − provision_risque_op` (`compute_net_pnl`).
Pour chaque terme : définition cash-and-carry, **statut de mesurabilité**, source. **Aucun `0` implicite ;
aucun double comptage.**

| # | Terme (champ) | Définition cash-and-carry | Mesurable / Inconnu | Source de mesure (à archiver) |
|---|---|---|---|---|
| 1 | **brut** `gross_pnl_usd` — funding + basis | `brut = funding reçu + (basis_entrée − basis_sortie)`, avec **`basis = perp − spot`** (long spot / short perp). **Une hausse du basis à la sortie est une perte.** Aucune convergence supposée | **Ex-post mesurable** ; **ex-ante INCONNU** (funding ET basis futurs non garantis) | Funding réglé **certifié+hashé** (venue, settlement, convention de signe) + basis aux **quotes d'entrée et de sortie** exécutables |
| 2 | **frais** `fees_usd` | Frais de trading des **4 ordres** (ouvrir spot, ouvrir perp, clôturer spot, clôturer perp) + frais de settlement éventuels. *(Seulement les frais d'ordres ici.)* | **Mesurable** | Barèmes taker/maker des venues au moment de la quote |
| 3 | **gas / retraits** `gas_usd` | Gas on-chain (jambe DEX) + frais de **dépôt/retrait** CEX + **transferts de collatéral** entre venues | **Mesurable mais variable** | `gas_estime_conservateur` + barèmes de retrait/transfert |
| 4 | **rebalancing** `rebalancing_usd` | Coût **amorti** des **ajustements de marge / de delta** (réinjection de collatéral, réajustement du ratio) sur l'horizon | **Partiellement mesurable** : coût unitaire connu, **nombre d'ajustements INCONNU ex-ante** (dépend de la volatilité réalisée) | Coût unitaire (frais+transfert) × fréquence **mesurée** sur fenêtre, jamais supposée |
| 5 | **capital** `capital_usd` | **Coût total de financement de la position** : coût d'opportunité du **capital propre** **+** (le cas échéant) **intérêts sur les fonds empruntés**. Sources **non exclusives** ; **chaque dollar alloué UNE SEULE FOIS** (pas de double comptage) | **Mesurable** une fois `capital`, `durée` et **taux** fixés | Σ par tranche : taux applicable (référence propre **et/ou** taux d'**emprunt mesuré**) × montant × durée ; **taux EXPLICITE et non nul** |
| 6 | **hedge** `hedge_usd` | **Réservé à une couverture additionnelle EFFECTIVEMENT ACHETÉE** (ex. option/protection réellement acquise contre gap/dépeg). **Pas** l'emprunt (→ capital), **pas** les ajustements (→ rebalancing) | **À décider** | Prime/coût **réel** de l'instrument acheté ; si **aucune** couverture achetée ⇒ **`0.0` EXPLICITE et justifié**, jamais implicite |
| 7 | **provision risque op.** `op_risk_provision_usd` | **Réservée au risque opérationnel RÉSIDUEL NON couvert** (ce qu'aucune couverture achetée ne protège) : retard/refus de retrait, halt plateforme, slippage de clôture, reorg, erreur d'exécution | **INCONNU** | **Provision explicite** (méthode à écrire) — jamais 0 implicite |

> **Synthèse mesurable / inconnu.** Mesurables à la quote : **frais (2)**, **gas/retraits (3)**,
> **capital (5)** (coût total de financement : propre **et/ou** emprunté, taux explicite **non nul**). Mesurable **ex-post seulement** :
> **brut = funding reçu + (basis_entrée − basis_sortie) (1)**. **À décider explicitement** : **rebalancing (4)**
> (fréquence), **hedge (6)** (couverture achetée ou `0.0` justifié), **provision risque op. (7)**
> (résiduel non couvert). Tant qu'un terme **applicable** est `None`, `build_quote_pair` **s'abstient**
> (`net = NaN`, `confidence = 0`, `missing_fields` peuplé).

## 3. Ce qui peut casser le mécanisme (risques)

| Risque | Comment il casse le mécanisme | À mesurer / gate associé |
|---|---|---|
| **Funding négatif ou instable** | Le brut (1) disparaît ou s'inverse : on **paie** au lieu d'encaisser | Signe + stabilité du funding sur fenêtre **certifiée** (gate §5.3) |
| **Basis** | Variation de basis défavorable entre entrée et sortie → perte sur le terme (1), aucune convergence garantie | Distribution du basis entrée/sortie ; seuil de clôture |
| **Liquidation / marge** | Mouvement de prix → appel de marge / **liquidation** de la jambe perp → hedge cassé, perte directionnelle | Distance à la liquidation à taille cible ; règles de marge de `V_perp` (gate §5.5) |
| **Emprunt** | Si une jambe nécessite un **borrow** : taux qui explose, **rappel** de prêt | Taux d'emprunt + disponibilité (terme **capital 5**) |
| **Exécution des deux jambes** | Une seule jambe remplie → position **non couverte** (delta ouvert) ; slippage asymétrique | Quotes exécutables **synchronisées** des 2 jambes (gate §5.4) |
| **Contrepartie / plateforme** | Halt, insolvabilité, gel de la venue → capital bloqué, hedge figé | Vetting plateforme ; limites d'exposition par venue (gate §5.6) |
| **Retrait** | Retrait/transfert **lent ou bloqué** → capital immobilisé plus longtemps, hedge non rééquilibrable | Délai/fiabilité de retrait **mesurés** (termes 3 + 5) |
| **Depeg** | Si `S` est wrappé/stable : **dépeg** spot vs sous-jacent du perp → basis structurel, identité économique rompue | Identité économique (mapping canonique) ; surveillance de peg (gate §5.2) |
| **Capacité** | La taille où `net > 0` s'effondre (profondeur des 2 jambes + marge) → poussière, pas une stratégie | Courbe **capacité → net** ; `CAPACITY_INSUFFICIENT` si meurt à petite taille (gate §5.8) |

## 4. Contrat de données minimal (avant tout test)

Rien ne se calcule avant que ces données soient **archivées, horodatées et hashées** (objets
`sim/contracts.py`). Aucune statistique de funding/basis avant stockage des quotes brutes (§4).

- **Identité économique** — spot et perp référencent le **même sous-jacent** (mapping économique
  canonique : actif + réseau + contrat/decimals si applicable + **transférabilité effective**). Cf
  `config/economic_identity.json`.
- **Funding** — série **certifiée** : venue, actif, **convention de signe**, **calendrier de
  settlement**, provenance, **hash**. *(La série actuelle `data/logs/funding_regime.csv` est **non
  certifiée** : `breadth=0`, plafond suspect ~10,9 % → à lever d'abord.)*
- **Jambe spot** (`RawQuote`) — venue, actif (adresse/decimals), taille, `amount_out` exécutable,
  frais, gas estimé, `wall_clock_utc`, `request_hash`/`response_hash`.
- **Jambe perp** — venue, mark price, **funding courant + calendrier**, exigences de **marge** +
  **formule/prix de liquidation**, **levier max**, frais.
- **Emprunt** (si applicable) — taux, disponibilité, conditions de rappel.
- **Retrait / transfert** — frais **et délai** par venue (dépôt, retrait, transfert de collatéral).
- **Capital** — capital total immobilisé (collatéral spot + marge perp), ventilé **propre et/ou
  emprunté** (chaque dollar alloué une fois) + **taux de référence explicite et non nul** par tranche
  (coût d'opportunité propre et/ou intérêts d'emprunt).
- **Cycle** (entrée → funding → sortie) — **deux** instantanés de jambes **synchronisées**
  (`same_time_tolerance`), **entrée et sortie**, plus le **funding réglé** sur la durée entre les deux ;
  `size_usd` ; les **7 termes** sur le cycle ; abstention (`confidence`/`missing_fields`) si un terme
  manque. **Modéliser ce cycle — étendre/composer `QuotePair` ou un nouvel objet — est une décision
  humaine ultérieure** (pas de réutilisation forcée du contrat existant).

## 5. Gates de rejet (à passer AVANT le premier test)

Tout gate non passé ⇒ **abstention** (jamais un faux 0) ou **REJET** explicite ; aucun test sinon.

1. **Certification des données** — funding/marge/retrait non **certifiés+hashés** ⇒ **abstention**
   (bloque tant que `funding_regime.csv` reste non certifié).
2. **Identité économique** — spot et perp ne désignent pas le **même** sous-jacent (mapping canonique)
   ⇒ **REJET**.
3. **Règle d'entrée funding — à PRÉENREGISTRER avant toute mesure** : fixer explicitement **fenêtre
   historique certifiée**, **convention de signe**, **seuil**, **condition d'entrée**. **Tant que cette
   règle n'est pas définie, le gate reste NON SPÉCIFIÉ et BLOQUE le test** (aucun « structurellement
   positif » présumé).
4. **Exécutabilité des deux jambes** — une jambe non remplissable à taille (quote archivée) ⇒
   **abstention** (position non couverte interdite).
5. **Marge / liquidation** — distance à la liquidation à taille cible sous seuil ⇒ **REJET**.
6. **Contrepartie / retrait** — venue non vettée (ToS, retrait fonctionnel, limites) ⇒ **REJET**.
7. **Coûts complets** — un terme de coût **applicable** reste `None` (dont hedge / provision risque op.)
   ⇒ **abstention** (jamais un 0 implicite).
8. **Capacité** — la taille où `net > 0` s'effondre (`CAPACITY_INSUFFICIENT`) ⇒ documenter comme
   poussière, **pas** une stratégie.

Le premier test n'est tenté **que si tous les gates passent**. Ce n'est **pas un unique `QuotePair`**,
mais un **cycle complet** à **taille définie** et **période préenregistrée** : (a) **paire de quotes
d'entrée synchronisées** (spot+perp), (b) **funding réellement réglé** sur la durée préenregistrée,
(c) **paire de quotes de sortie synchronisées**. Résultat = **tableau de PnL net (7 termes) sur le
cycle** — jamais un annualisé séduisant. **Le contrat `QuotePair` existant (`sim/contracts.py`) ne doit
pas être étendu ni réutilisé de force pour ce cycle sans décision humaine ultérieure.**

## 6. Statut & suite

**`NON_CONCLUANT`.** Ce mémo **définit le mécanisme et le protocole de mesure** ; il **n'établit aucun
PnL** et **n'estime aucun rendement**. Ordre de preuve (cf `EVIDENCE_LEDGER`, claim funding) :

① mémo **écrit et validé** (ce document) → ② **contrat/provenance des données funding certifiés et
hashés** + **règle d'entrée préenregistrée** (gate §5.3) → ③ **un cycle complet** spot/perp (entrée
synchronisée → funding réglé sur durée préenregistrée → sortie synchronisée ; taille fixe, gates §5
passés) → ④ **PnL 7-termes + capacité + stress**. **Aucun code, collecteur ni backfill** tant que ②
n'est pas fait et ce mémo validé humainement.
