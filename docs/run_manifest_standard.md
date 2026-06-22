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
| `verdict` | humain | **VALIDE / REJETE / NON_CONCLUANT** |

## Verdict — trois valeurs, pas plus
- **VALIDE** : l'hypothèse tient, **net de coûts**, sur la couverture mesurée.
- **REJETE** : l'hypothèse est fausse / le signal est un artefact (ex. les $20M CEX↔CEX).
- **NON_CONCLUANT** : couverture / puissance insuffisante pour trancher (à ré-observer).

Jamais « intéressant », « prometteur » : un manifeste **tranche** ou dit explicitement qu'il ne peut pas.

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
