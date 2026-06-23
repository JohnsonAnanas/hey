# Rapport PHASE 0B — source données Binance-USDM / ETHUSDT

- **Verdict : SOURCE_CAPABLE**
- Provenance : git `89284681d0` ; code_versioned=True ; git_dirty=False ; runner_sha256 `2d3c3cdccffca621…`
- Fenêtre figée : 2025-06-23T00:00:00Z → 2026-06-23T00:00:00Z

## A.3 — métadonnées reçues (fundingInfo ETHUSDT)
```json
{
  "funding_info": {
    "symbol": "ETHUSDT",
    "adjustedFundingRateCap": "0.00300",
    "adjustedFundingRateFloor": "-0.00300",
    "fundingIntervalHours": 8,
    "disclaimer": true
  }
}
```
## A.4 — sonde historique (startTime/endTime, NON ambiguë)
```json
{
  "source": "Binance GET /fapi/v1/fundingRate",
  "probe_param": "symbol=ETHUSDT&startTime=1750636800000(2025-06-23T00:00:00Z)&endTime=1750809600000(2025-06-25T00:00:00Z)&limit=10",
  "window_start_utc": "2025-06-23T00:00:00Z",
  "window_end_utc": "2026-06-23T00:00:00Z",
  "records_returned": 6,
  "fundingTimes_utc": [
    "2025-06-23T00:00:00Z",
    "2025-06-23T08:00:00Z",
    "2025-06-23T16:00:00Z",
    "2025-06-24T00:00:00Z",
    "2025-06-24T08:00:00Z",
    "2025-06-24T16:00:00Z"
  ],
  "covers_window_start": true
}
```
## Reçus (bruts hors Git, hashés)
- `funding_info_A3` — HTTP 200 — 115547 o — sha256 `7e04737b2a891e3c…` — `data/raw/funding/binance/phase0b/funding_info_A3_20260623T205103Z.json`
  - https://fapi.binance.com/fapi/v1/fundingInfo
- `funding_history_probe_A4` — HTTP 200 — 626 o — sha256 `13216fe2eded4bc6…` — `data/raw/funding/binance/phase0b/funding_history_probe_A4_20260623T205103Z.json`
  - https://fapi.binance.com/fapi/v1/fundingRate?symbol=ETHUSDT&startTime=1750636800000&endTime=1750809600000&limit=10

## Abstentions / motifs
- (aucune)

> Reçus de validation params/capacité **uniquement** — pas une série certifiée, non agrégés, ni calibration ni test, **ni choix de venue de trading**. **Phase 1 INTERDITE.**
