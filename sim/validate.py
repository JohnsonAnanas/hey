"""Porte de validation POOL/TOKEN (Phase 2) — un pool doit la franchir avant d'entrer au scan.

Echec -> QUARANTAINE loggee (jamais d'inclusion muette). On valide ce qu'on PEUT prouver on-chain :
- token0 ET token1 == paire attendue triee (orientation correcte -> reserves non inversees) ;
- type constant-product : Aerodrome -> `stable()==False` (sinon math `x*y=k` invalide) ;
- frais : Aerodrome lus on-chain (`getFee`, PAS de fallback muet) ; forks UniV2 canoniques = 0.30%
  fixe par le contrat -> `fee_verified=True` ; un fork a frais non garanti reste `fee_verified=False` ;
- frais dans des bornes saines ; dedup par adresse.

La DECISION par pool est isolee en fonction PURE `judge_pool` (testee). `validate_pools` ne fait que
le batch de lectures on-chain. Limites assumees (cf docs/data_integrity.md) : recoupement quoter
universel + detection fee-on-transfer programmatique = durcissements suivants ; ici on ne fait
JAMAIS confiance en silence -> les metadonnees `type_verified` / `fee_verified` sont explicites.
"""
from __future__ import annotations

from .chain import addr_from, uint_from, SEL_TOKEN0, SEL_TOKEN1, SEL_STABLE

# Forks dont les frais 0.30% sont fixes par le contrat (verifies dans la litterature/les sources).
CANONICAL_030 = {"UniV2", "SushiV2"}


def judge_pool(exp_t0: str, exp_t1: str, got_t0: str | None, got_t1: str | None,
               is_aero: bool, stable_flag: bool | None, fee, fee_canonical: bool) -> tuple[bool, list, dict]:
    """Verdict PUR d'un pool. Renvoie (ok, raisons, meta). Aucune lecture reseau ici."""
    reasons: list[str] = []
    meta: dict = {}
    if got_t0 is None or got_t1 is None:
        reasons.append("token0/token1 illisible")
    else:
        meta["t0"], meta["t1"] = got_t0, got_t1
        if got_t0 != exp_t0 or got_t1 != exp_t1:
            reasons.append("orientation inattendue (token0/token1 != paire triee)")
    if is_aero:
        if stable_flag is None:
            reasons.append("stable() illisible")
        elif stable_flag is True:
            reasons.append("pool Aerodrome STABLE (math x*y=k invalide)")
    if fee is None:
        reasons.append("frais illisibles")
    elif not (0.0 <= fee < 0.1):
        reasons.append(f"frais hors bornes ({fee})")
    meta["fee"] = fee
    meta["type_verified"] = (len(reasons) == 0)
    meta["fee_verified"] = bool(is_aero or fee_canonical)   # aero lu on-chain ; forks canoniques 0.30%
    return (len(reasons) == 0, reasons, meta)


def validate_pools(rpc, pools: list[dict], addr_of: dict) -> tuple[list[dict], list[tuple[dict, list]]]:
    """Valide une liste de pools resolus. Renvoie (valides, quarantaine=[(pool, raisons), ...]).

    `addr_of` : symbole -> adresse checksummee. Chaque pool a `pair=(s0,s1)`, `address`, `method`,
    `venue`, et `fee` (deja lu pour Aerodrome). Lectures batchees (token0/token1 ; stable pour aero).
    """
    if not pools:
        return [], []
    res01 = rpc.multicall([c for p in pools for c in ((p["address"], SEL_TOKEN0), (p["address"], SEL_TOKEN1))])
    aero = [p for p in pools if p["method"] == "getPoolBool"]
    res_stable = rpc.multicall([(p["address"], SEL_STABLE) for p in aero]) if aero else []
    stable_by_addr = {}
    for i, p in enumerate(aero):
        ok, d = res_stable[i]
        stable_by_addr[p["address"]] = (uint_from(d) == 1) if (ok and d) else None

    valid, quarantined, seen = [], [], set()
    for i, p in enumerate(pools):
        ok0, d0 = res01[2 * i]
        ok1, d1 = res01[2 * i + 1]
        got_t0 = addr_from(d0) if ok0 else None
        got_t1 = addr_from(d1) if ok1 else None
        s0, s1 = p["pair"]
        is_aero = (p["method"] == "getPoolBool")
        stable_flag = stable_by_addr.get(p["address"]) if is_aero else None
        okv, reasons, meta = judge_pool(addr_of[s0], addr_of[s1], got_t0, got_t1,
                                        is_aero, stable_flag, p.get("fee"), p["venue"] in CANONICAL_030)
        if p["address"] in seen:
            okv = False
            reasons = reasons + ["doublon d'adresse"]
        seen.add(p["address"])
        if okv:
            p.update(meta)
            valid.append(p)
        else:
            quarantined.append((p, reasons))
    return valid, quarantined
