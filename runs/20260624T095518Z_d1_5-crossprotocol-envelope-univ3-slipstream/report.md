# Rapport D1.5 — enveloppe atomique cross-protocole Uni v3 ↔ SlipStream (Base)

- **Verdict : NON_CONCLUANT** (enveloppe atomique EXACTE non constructible read-only).
- Provenance : git `ec26823891` ; code_versioned=True ; git_dirty=False
- Infra SlipStream **vérifiée on-chain** : factory `0x5e7BB104…`, quoter `0x254cF9E1…`, router `0xBE6D8f0d…` ; pool WETH/USDC tickSpacing=100.
- **Mêmes contrats WETH/USDC certifiés** dans les deux protocoles.

## Round-trip BRUT cross-protocole (quotes seules, AUCUN gas — INDICATIF)
```json
{
  "250": {
    "uni_then_slip_usd": -0.1595,
    "slip_then_uni_usd": -0.3066
  },
  "1000": {
    "uni_then_slip_usd": -0.6578,
    "slip_then_uni_usd": -1.2463
  },
  "2500": {
    "uni_then_slip_usd": -1.7432,
    "slip_then_uni_usd": -3.2143
  },
  "5000": {
    "uni_then_slip_usd": -3.8154,
    "slip_then_uni_usd": -6.7571
  },
  "10000": {
    "uni_then_slip_usd": -8.9469,
    "slip_then_uni_usd": -14.8281
  }
}
```
## Pourquoi NON_CONCLUANT (précis)
Aucun routeur canonique ne chaîne un pool Uniswap v3 ET un pool SlipStream dans une seule transaction : SwapRouter02 résout ses pools via la factory Uniswap (path = fee tiers), le SlipStream Router via la factory SlipStream (tickSpacing). Un round-trip atomique cross-protocole exigerait un contrat EXÉCUTEUR déployé (INTERDIT : aucun déploiement). Donc le calldata atomique EXACT n'existe pas read-only -> estimateGas L2 et coût L1/data sur OCTETS EXACTS impossibles.

> Capture atomique cross-protocole = territoire MEV-exécuteur (contrat déployé) par construction. Hors périmètre non-MEV / no-deploy. **Ce NON_CONCLUANT BLOQUE tout scanner cible.** Aucun token cible, aucun PnL, aucun bot.
