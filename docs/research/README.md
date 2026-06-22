# Recherches de référence (R1, R2, R3)

> PDFs locaux (dans ce dossier, **non redistribués**, gitignorés). Résumés + usage projet.
> Le cœur quantitatif est repris et vérifié dans [`../formulas.md`](../formulas.md).

## R1 — Angeris, Kao, Chiang, Noyes, Chitra — *An Analysis of Uniswap Markets* (2019, 25 p.)

Analyse formelle des marchés constant-product. Résultat clé : sous des conditions courantes,
le prix d'un AMM **suit de près le prix de référence** grâce aux **arbitragistes** ; bornes de
déviation ; simulation agent-based montrant la stabilité sur une large gamme de conditions.

**Usage projet :** comprendre *pourquoi* l'arbitrage existe et pourquoi `x·y=k` suffit à créer
un marché exploitable. **Implication directe :** c'est la **borne de non-arbitrage** qu'on a
redécouverte empiriquement (2026-06-22) — les écarts qui *persistent* restent **< frais**,
donc incapturables ; les écarts capturables meurent vite. Mesurer le **MAV net**, pas le mid.

## R2 — Angeris, Chitra, Evans, Boyd — *Optimal Routing for CFMMs* (2021, 16 p.)

Router un ordre sur un **réseau de CFMMs** = **optimisation convexe** (tractable) sans coûts
fixes ; **MIP convexe** avec coûts fixes. Point central : **la détection d'arbitrage est un cas
particulier** du routing optimal (trouver l'arb, ou *certifier* l'absence).

**Usage projet :** passer proprement de « 2 pools » à « réseau de pools » ; voir le bot comme
un **moteur d'optimisation**, pas un comparateur de prix. Pour la phase multi-hop / multi-pool.

## R3 — Gogol, Messias, Miori, Tessone, Livshits — *Quantifying Arbitrage in AMMs* (2024, 19 p.)

Introduit le **Maximal Arbitrage Value (MAV)** : profit max extractible tenant compte de
l'écart de prix **et** de la liquidité. Formule (constant-product, AMM↔CEX) :
`MAV = y·(Pa−Pc)²/(4·Pa)` → **linéaire en liquidité, quadratique en écart**. Étude empirique
zkSync Era (SyncSwap) vs Binance : MAV total juil.→sept. 2023 = **104,96 K$ (0,24 % du
volume)** ; mesure le **temps de décroissance** (*decay time*) des écarts + impact
frais / slippage / gas.

**Usage projet :** **métrique centrale** du bot. Un spread affiché = signal ; seul le **MAV net**
= opportunité. Le *decay time* de R3 = notre **persistance** (le chiffre qui dit « capturable
par un solo » vs « déjà pris par les bots »).
