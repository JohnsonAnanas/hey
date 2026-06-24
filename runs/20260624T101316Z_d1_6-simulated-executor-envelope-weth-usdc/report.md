# Rapport D1.6 — enveloppe atomique cross-protocole par executeur simule (Base)

- **Verdict edge : NO_ATOMIC_EDGE**
- Provenance : git `0b7950b7f7` ; code_versioned=True ; git_dirty=False ; executeur src sha `53417e9788fd2747…`
- Fenetre : blocs 47753026-47753325 (300 ; echecs 0)
- Enveloppe (tete) : out(1 WETH, uni->slip)=0.600910 ; gas_units_L2=400484 ; l1Fee=1649464144 wei ; code-override estimateGas VERIFIE

## Courbes taille -> upper_bound_atomique (USD)
```json
{
  "250": {
    "uni_then_slip": {
      "n": 300,
      "median_usd": -0.2771,
      "max_usd": -0.0449,
      "min_usd": -0.3492
    },
    "slip_then_uni": {
      "n": 300,
      "median_usd": -0.2432,
      "max_usd": -0.0662,
      "min_usd": -0.4029
    }
  },
  "1000": {
    "uni_then_slip": {
      "n": 300,
      "median_usd": -1.1221,
      "max_usd": -0.1932,
      "min_usd": -1.4092
    },
    "slip_then_uni": {
      "n": 300,
      "median_usd": -0.9834,
      "max_usd": -0.276,
      "min_usd": -1.6266
    }
  },
  "2500": {
    "uni_then_slip": {
      "n": 300,
      "median_usd": -2.9051,
      "max_usd": -0.5944,
      "min_usd": -3.6293
    },
    "slip_then_uni": {
      "n": 300,
      "median_usd": -2.556,
      "max_usd": -0.7894,
      "min_usd": -4.1845
    }
  },
  "5000": {
    "uni_then_slip": {
      "n": 300,
      "median_usd": -6.1548,
      "max_usd": -1.5808,
      "min_usd": -7.6263
    },
    "slip_then_uni": {
      "n": 300,
      "median_usd": -5.4858,
      "max_usd": -1.9222,
      "min_usd": -8.7744
    }
  },
  "10000": {
    "uni_then_slip": {
      "n": 300,
      "median_usd": -13.6861,
      "max_usd": -4.7711,
      "min_usd": -16.733
    },
    "slip_then_uni": {
      "n": 300,
      "median_usd": -12.4803,
      "max_usd": -5.2276,
      "min_usd": -19.1804
    }
  }
}
```
> Enveloppe atomique cross-protocole CALIBREE (executeur SIMULE, read-only ; aucun deploiement/cle/wallet/tx). Priorite MEV exclue = borne superieure. Controle ; aucun PnL tradable, aucun token cible, aucun bot. Le brut negatif n'est PAS un rejet universel.
