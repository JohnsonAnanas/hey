# Standard de manifeste de run — OBLIGATOIRE

> Aucun run / expérience n'est **cru** sans manifeste. Le manifeste rattache durablement
> **donnée ↔ conclusion ↔ version de code** : sans lui, on recrée du doute en quelques semaines
> (« d'où venait ce chiffre ? quel code ? quelles données ? »). Même rôle que `checks.py` pour
> l'intégrité : une **porte**, pas une option. Outil : [`../manifest.py`](../manifest.py).

## Quand
À **chaque** run produisant un chiffre destiné à informer une décision (scan, backtest, mesure de
persistance, évaluation de route…). Un run sans manifeste = un résultat **non recevable**.

## Champs (tous requis)
| Champ | Source | Sens |
|---|---|---|
| `hypothesis` | humain | la question testée, **falsifiable** |
| `git_hash` | **auto** | version exacte du code (HEAD) |
| `git_dirty` | **auto** | arbre sale ⟹ le hash ne pin pas tout (à éviter) |
| `command` | humain | commande + paramètres exacts |
| `period` | humain | période des données |
| `sources` | humain | provenance (RPC, exchange, API…) |
| `inputs` + `sha256` | **auto** | empreinte de chaque fichier d'entrée (la brute n'est pas dans Git, son **hash** l'est) |
| `universe` | humain | univers étudié (tokens, venues…) |
| `assumed_costs` | humain | coûts supposés (frais, gas, slippage, capital immobilisé…) |
| `result` | humain | résultat mesuré |
| `verdict` | humain | un statut de la **taxonomie MISSION RESET** (ci-dessous) |

## Verdict — taxonomie MISSION RESET (§2)
`VALIDE` est **interdit** : jamais pour un triage, une médiane ou une quote isolée. Les statuts :
- **INVALIDE** : artefact démontré (ex. les $20M CEX↔CEX = identité par ticker).
- **REJETE** : hypothèse fausse / négative **net de coûts**, sur la couverture mesurée (souvent `REJETE_SCOPE`).
- **NON_CONCLUANT** : couverture / puissance insuffisante pour trancher (à ré-observer).
- **LEAD** : piste retenue (ex. triage, identité partielle) — **pas** un résultat économique.
- **MECANISME_CONFIRME** : mécanisme de convergence prouvé (identité + route), avant tout PnL.
- **QUOTE_POSITIVE** : une `QuotePair` nette positive à taille définie (niveau de preuve ≥ 2).
- **PAPER_ELIGIBLE** : éligible au paper trading (rebalancing confirmé, série hors échantillon).

Les niveaux positifs se gagnent **par paliers**, chacun avec artefacts (cf `EVIDENCE_LEDGER.md`,
niveaux de preuve 0→6). Jamais « intéressant »/« prometteur » : un manifeste **tranche** ou dit
explicitement qu'il ne peut pas. **Les manifests déjà écrits restent immuables** ; cette liste ne
gouverne que les **nouveaux** runs (l'outil `manifest.py` la fait respecter).

## Usage
```bash
python manifest.py --slug <kebab> --hypothesis "…" --command "…" --period "…" \
  --source "…" [--source "…"] --input <fichier> [--input <fichier>] \
  --universe "…" --costs "…" --result "…" --verdict REJETE
# -> runs/<UTC>_<slug>/manifest.json  (+ manifest.md lisible)
```
Les manifestes (`runs/**`) sont **suivis par Git**. La donnée brute hashée ne l'est pas (régénérable,
licences) — c'est l'**empreinte** qui fait foi. Si `git_dirty=true`, le run a été lancé sur du code non
committé : à proscrire pour tout résultat qu'on veut défendre.
