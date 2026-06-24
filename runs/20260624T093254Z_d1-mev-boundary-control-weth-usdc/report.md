# Rapport D1 — contrôle WETH/USDC same-chain (Base) — calibration enveloppe

- **Verdict edge : NO_ATOMIC_EDGE** ; capacité : PAS_DE_CAPACITE
- Provenance : git `79587e5f50` ; code_versioned=True ; git_dirty=False
- Fenêtre : blocs 47751815–47752114 (300; échecs 0)
- Enveloppe : gas_units_L2(cal)=219501 ; base_fee_L2=5000000 wei ; l1Fee(head)=1687668068 wei ; override auto-vérifié OK

## Courbes taille → upper_bound_atomique (USD, par orientation)
```json
{
  "250": {
    "500_3000": {
      "n": 300,
      "median_usd": -1.4988,
      "max_usd": -1.4793,
      "min_usd": -1.5154
    },
    "3000_500": {
      "n": 300,
      "median_usd": -0.2571,
      "max_usd": -0.2408,
      "min_usd": -0.2757
    }
  },
  "1000": {
    "500_3000": {
      "n": 300,
      "median_usd": -6.0064,
      "max_usd": -5.9281,
      "min_usd": -6.0726
    },
    "3000_500": {
      "n": 300,
      "median_usd": -1.0398,
      "max_usd": -0.9748,
      "min_usd": -1.1142
    }
  },
  "2500": {
    "500_3000": {
      "n": 300,
      "median_usd": -15.0962,
      "max_usd": -14.9005,
      "min_usd": -15.2617
    },
    "3000_500": {
      "n": 300,
      "median_usd": -2.6802,
      "max_usd": -2.5177,
      "min_usd": -2.8663
    }
  },
  "5000": {
    "500_3000": {
      "n": 300,
      "median_usd": -30.4669,
      "max_usd": -30.0754,
      "min_usd": -30.7978
    },
    "3000_500": {
      "n": 300,
      "median_usd": -5.636,
      "max_usd": -5.3111,
      "min_usd": -6.0082
    }
  },
  "10000": {
    "500_3000": {
      "n": 300,
      "median_usd": -62.0376,
      "max_usd": -61.2546,
      "min_usd": -62.6988
    },
    "3000_500": {
      "n": 300,
      "median_usd": -12.3796,
      "max_usd": -11.7304,
      "min_usd": -13.1233
    }
  }
}
```
## QC gas (L2 + L1, priorité exclue → borne supérieure)
```json
{
  "gas_units_l2_by_size_orient": {
    "500_3000|250": 219513,
    "500_3000|1000": 219501,
    "500_3000|2500": 219485,
    "500_3000|5000": 219501,
    "500_3000|10000": 256471,
    "3000_500|250": 209205,
    "3000_500|1000": 209173,
    "3000_500|2500": 219566,
    "3000_500|5000": 218621,
    "3000_500|10000": 219625
  },
  "l1_included": true,
  "l2_included": true,
  "priority_excluded": true
}
```
> Borne SUPÉRIEURE (priorité MEV exclue). Contrôle ; **aucun PnL tradable**, aucun token cible, aucun bot MEV. Reçus bruts hors Git, hashés.
