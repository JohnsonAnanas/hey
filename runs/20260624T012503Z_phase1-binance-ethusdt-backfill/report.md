# Rapport PHASE 1 — série certifiée Binance-USDM / ETHUSDT

- **Verdict de collecte : COLLECTE_COMPLETE**
- Fenêtre figée : 2025-06-23T00:00:00Z → 2026-06-23T00:00:00Z
- Provenance : git `3582c0b21e` ; code_versioned=True ; git_dirty=False ; runner_sha256 `48948de2534636e8…`

## Couverture & QC
```json
{
  "records_raw_total": 1095,
  "raw_ascending_per_window": [
    true,
    true
  ],
  "seam_ordered": true,
  "duplicates_removed": 0,
  "duplicate_fundingTimes_utc": [],
  "records_after_dedup": 1095,
  "base_interval_ms": 28800000,
  "nominal_settlements_half_open": 1095,
  "no_interpolation": true,
  "monotonic_strict": true,
  "first_settlement_utc": "2025-06-23T00:00:00Z",
  "last_settlement_utc": "2026-06-22T16:00:00Z",
  "first_offset_ms_from_window_start": 0,
  "last_offset_ms_from_window_end": -28799998,
  "reaches_window_start": true,
  "reaches_window_end": true,
  "gaps": [],
  "gaps_count": 0,
  "missing_settlements_total": 0,
  "sub_interval_anomalies": [],
  "observed_interval_hours_histogram": {
    "8": 1094
  },
  "nstep_histogram": {
    "1": 1094
  },
  "raw_delta_ms_min": 28799984,
  "raw_delta_ms_max": 28800016,
  "contiguous": true
}
```
## Requêtes (2 fenêtres fixes non chevauchantes) — reçus bruts hors Git, hashés
- `backfill_W1` — 2025-06-23T00:00:00Z → 2025-12-22T23:59:59Z — HTTP 200 — 549 règlements — 57171 o — sha256 `3c359271842b8a1f…`
  - premier=2025-06-23T00:00:00Z dernier=2025-12-22T16:00:00Z troncature=False
  - `data/raw/funding/binance/phase1/backfill_W1_20260624T012503Z.json`
- `backfill_W2` — 2025-12-23T00:00:00Z → 2026-06-23T00:00:00Z — HTTP 200 — 546 règlements — 57006 o — sha256 `b0cb51764535ef79…`
  - premier=2025-12-23T00:00:00Z dernier=2026-06-22T16:00:00Z troncature=False
  - `data/raw/funding/binance/phase1/backfill_W2_20260624T012503Z.json`

- Non-chevauchement : delta W2.start − W1.end = 1 ms (overlap=False)

## Abstentions / motifs
- (aucune)

> Série **brute** certifiée (timestamps/couverture) **uniquement** — **aucune** agrégation, annualisation, PnL, calibration ni choix de venue. **Aucun travail économique sans nouvelle validation humaine.**
