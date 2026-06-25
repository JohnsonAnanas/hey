# D2B2_SUSPENDU_METHODOLOGIQUE

**Statut : SUSPENDU (decision METHODOLOGIQUE, PAS un echec technique, PAS un rejet economique global).**

## Raison
Les lots 00-02 (3 des 145 routes, fenetre de 300 blocs consecutifs ~= ~10 min de Base) donnent assez
d'information pour valider l'enveloppe de mesure et constater que **cette fenetre ne porte pas de signal
evident**. Continuer les 29 lots sur la MEME fenetre ~10 min n'est plus le meilleur usage du temps.
Prochaine direction : scan temporel LEGER multi-moments / multi-jours, puis zoom profond uniquement
autour des routes/blocs candidats. La rigueur est preservee : on arrete parce que la mesure en cours
n'est plus alignee avec la vraie question, pas sur un resultat.

## Lots COMPLETS (intacts, hash verifie) -- runner FIGE 8175837, throttle 380/8

| lot | dossier | verdict | cycles ok | sha256 raw |
|---|---|---|---|---|
| 00 | `runs/20260625T012951Z_d2b2v2-measure-lot00` | LOT_MESURE | 15000 | `471d39821c808c26...` |
| 01 | `runs/20260625T030510Z_d2b2v2-measure-lot01` | LOT_MESURE | 15000 | `95c4737c02108949...` |
| 02 | `runs/20260625T044021Z_d2b2v2-measure-lot02` | LOT_MESURE | 15000 | `3d1f6fff92214a85...` |

**Agregat 00-02** : 45000 cycles `ok`, 0 CAPACITY, 0 WINDOW_UNAVAILABLE, 0 NON_CONCLUANT_INFRA.
Raw conserves (hors Git, hashes dans les manifestes ci-dessus). Manifestes versionnes.

## Meilleur upper_bound observe (FACTUEL, NON un verdict)
- **-$0.040905** (lot 01, route `0687c5b2861a...`, bloc 47762210, taille $250, slip_then_uni).
- Sur 45000 cycles : **0 positif, 45000 negatifs**.
- CES VALEURS SONT DES **BORNES SUPERIEURES** (priorite MEV/gas competitif EXCLUE) -> le PnL
  realisable est <= a ces bornes. Fenetre = 3/145 routes x 300 blocs (~10 min). **Ce n'est PAS un
  rejet global du track** : juste l'absence de borne positive dans cette fenetre etroite.

## Lot 03 (courant) -- PARTIEL
Interrompu a mi-mesure (~48 min), arret PROPRE (aucune ecriture en cours au moment de l'arret) :
**aucun manifeste, aucun raw produit** -> ecarte. JAMAIS interprete, JAMAIS fusionne a une reprise.
Une reprise eventuelle re-mesurerait le lot ENTIER (apres validation).

## Note quarantaine distincte
L'ancien run batch `runs/20260624T225645Z_d2b2v2-measure-lot00/` (transport batch, ~68% contamine)
reste en quarantaine SEPAREE (QUOTA_INCOMPLETE.flag) : sans rapport avec ces lots corriges.
