#!/usr/bin/env python
"""Runner D1.5 — enveloppe atomique cross-protocole Uniswap v3 ↔ Aerodrome SlipStream (Base), READ-ONLY.

Objectif UNIQUE : établir OU refuser une enveloppe atomique EXACTE Uniswap v3 ↔ SlipStream sur le contrôle
WETH/USDC. PAS de scanner, PAS d'univers cible, PAS de recherche de rendement, PAS de bot MEV.

STRICTEMENT read-only : eth_call uniquement. AUCUNE clé, wallet, approbation, transaction signée ni
déploiement.

Adresses SlipStream sourcées (labels BaseScan officiels, accès 2026-06-24) — VÉRIFIÉES on-chain :
  - CLFactory (Pool Factory) : 0xeC8E5342B19977B4eF8892e02D8DAEcfa1315831
  - SlipStream Quoter        : 0x254cf9e1e6e233aa1ac962cb9b05b2cfeaae15b0
  - SlipStream Swap Router   : 0xbe6d8f0d05cc4be24d5167a3ef062215be6d18a5
Spécificité : SlipStream indexe par `tickSpacing` (int24), PAS par `fee`. getPool(a,b,int24) ;
quoteExactInputSingle((address,address,uint256,int24,uint160)).

Préconditions vérifiées (sinon NON_CONCLUANT) : factory/pool/quoter/router canoniques présents on-chain ;
les DEUX pools échangent EXACTEMENT les mêmes contrats WETH et USDC ; quotes exactes au même bloc, deux
orientations.

Enveloppe atomique exacte : un round-trip cross-protocole en UNE tx exigerait un routeur capable de chaîner
un pool Uniswap v3 ET un pool SlipStream. Or Uniswap SwapRouter02 ne route que des pools Uniswap v3 (path
= fee tiers résolus par la factory Uniswap) ; le SlipStream Router ne route que des pools SlipStream. AUCUN
routeur canonique ne chaîne les deux ; le faire exigerait un contrat EXÉCUTEUR déployé (INTERDIT). Donc le
calldata atomique EXACT n'est pas constructible read-only -> estimateGas L2 / coût L1 sur octets exacts
IMPOSSIBLES -> verdict NON_CONCLUANT (précis), qui BLOQUE tout scanner cible.

Sortie : soit ENVELOPE_CALIBRATED (si un calldata atomique exact existait), soit NON_CONCLUANT précis.
Le round-trip BRUT cross-protocole (quotes seules, sans gas) est rapporté à titre INDICATIF (montre que la
mesure de quote est faisable), jamais comme un net ni un PnL.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone

from eth_abi import encode as abi_encode
from web3 import Web3

import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from archive_rpc import endpoints  # noqa: E402
from sim.chain import SEL_TOKEN0, SEL_TOKEN1  # noqa: E402
from sim.quote_v3 import V3Quoter  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
CHAIN_ID = 8453
WETH = Web3.to_checksum_address("0x4200000000000000000000000000000000000006")
USDC = Web3.to_checksum_address("0x833589fcd6edb6e08f4c7c32d4f71b54bda02913")
UNIV3_ROUTER = Web3.to_checksum_address("0x2626664c2603336E57B271c5C0b26F421741e481")  # SwapRouter02 (Uni v3)
SLIP_FACTORY = Web3.to_checksum_address("0x5e7BB104d84c7CB9B682AaC2F3d509f5F406809A")  # = SlipStream Quoter.factory() (autorité ; vérifié au run)
SLIP_QUOTER = Web3.to_checksum_address("0x254cf9e1e6e233aa1ac962cb9b05b2cfeaae15b0")
SLIP_ROUTER = Web3.to_checksum_address("0xbe6d8f0d05cc4be24d5167a3ef062215be6d18a5")

UNIV3_FEE = 500                                   # palier Uni v3 (le plus liquide WETH/USDC)
SLIP_TICKSPACINGS = [100, 1, 200, 2000, 50, 10]   # candidats ; on retient le pool same-token le PLUS PROFOND
SIZES_USD = [250, 1000, 2500, 5000, 10000]

SEL_SLIP_QUOTE = Web3.keccak(text="quoteExactInputSingle((address,address,uint256,int24,uint160))")[:4]
SEL_GETPOOL_TS = Web3.keccak(text="getPool(address,address,int24)")[:4]
SEL_DECIMALS = Web3.keccak(text="decimals()")[:4]
SEL_FACTORY = Web3.keccak(text="factory()")[:4]


# ----------------------------------------------------------------------------- fonctions PURES (testables)
def slip_quote_calldata(token_in: str, token_out: str, amount_in: int, tick_spacing: int) -> bytes:
    """calldata SlipStream Quoter.quoteExactInputSingle (tickSpacing int24, PAS fee)."""
    enc = abi_encode(["(address,address,uint256,int24,uint160)"],
                     [(Web3.to_checksum_address(token_in), Web3.to_checksum_address(token_out),
                       int(amount_in), int(tick_spacing), 0)])
    return SEL_SLIP_QUOTE + enc


def getpool_calldata(token_a: str, token_b: str, tick_spacing: int) -> bytes:
    return SEL_GETPOOL_TS + abi_encode(["address", "address", "int24"],
                                       [Web3.to_checksum_address(token_a),
                                        Web3.to_checksum_address(token_b), int(tick_spacing)])


def same_tokens(pool_t0: str, pool_t1: str, weth: str, usdc: str) -> bool:
    a = {Web3.to_checksum_address(pool_t0), Web3.to_checksum_address(pool_t1)}
    return a == {Web3.to_checksum_address(weth), Web3.to_checksum_address(usdc)}


def gross_roundtrip_wei(out2_wei: int, in_wei: int) -> int:
    """Round-trip BRUT (quotes seules, sans gas) en WETH-wei. INDICATIF, jamais un net."""
    return int(out2_wei) - int(in_wei)


def wei_to_usd(weth_wei: int, weth_price_usd: float) -> float:
    return weth_wei / 1e18 * weth_price_usd


def addr_from_word(ret: bytes):
    if ret and len(ret) >= 32 and int.from_bytes(ret[-20:], "big") != 0:
        return Web3.to_checksum_address("0x" + ret[-20:].hex())
    return None


# ----------------------------------------------------------------------------- gouvernance
def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _git(*a: str) -> str:
    try:
        return subprocess.run(["git", "-C", HERE, *a], capture_output=True, text=True).stdout.strip()
    except Exception:
        return ""


def provenance() -> dict:
    rel = os.path.relpath(os.path.abspath(__file__), HERE).replace("\\", "/")
    with open(os.path.abspath(__file__), "rb") as f:
        runner_sha = hashlib.sha256(f.read()).hexdigest()
    tracked = bool(_git("ls-files", "--", rel))
    file_status = _git("status", "--porcelain", "--", rel)
    code_versioned = tracked and not file_status
    tracked_dirty = bool(_git("status", "--porcelain", "--untracked-files=no"))
    return {"git_hash": _git("rev-parse", "HEAD") or "UNVERSIONED", "runner_path": rel,
            "runner_sha256": runner_sha, "runner_tracked": tracked, "runner_status": file_status or "clean",
            "code_versioned": bool(code_versioned), "git_dirty": bool(tracked_dirty or not code_versioned)}


def write_and_print(run_dir, manifest, summary):
    manifest["created_utc"] = now_utc()
    os.makedirs(run_dir, exist_ok=True)
    with open(os.path.join(run_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def abstain(run_dir, manifest, reason: str) -> int:
    manifest["verdict"] = "NON_CONCLUANT"
    manifest["abstention_reason"] = reason
    write_and_print(run_dir, manifest, {"verdict": "NON_CONCLUANT", "reason": reason,
                    "run_dir": os.path.relpath(run_dir, HERE).replace("\\", "/")})
    return 0


def slip_quote(w3, token_in, token_out, amount_in, ts, block):
    try:
        ret = w3.eth.call({"to": SLIP_QUOTER,
                           "data": "0x" + slip_quote_calldata(token_in, token_out, amount_in, ts).hex()},
                          block)
        out = int.from_bytes(bytes(ret)[:32], "big")
        return out if out > 0 else None
    except Exception:
        return None


def main() -> int:
    prov = provenance()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = os.path.join(HERE, "runs", f"{stamp}_d1_5-crossprotocol-envelope-univ3-slipstream")
    manifest = {
        "phase": "D1.5", "track": "defi-samechain-mev-boundary", "chain": "base", "pair": "WETH/USDC",
        "objective": "établir ou refuser une enveloppe atomique EXACTE Uniswap v3 ↔ SlipStream (contrôle)",
        "read_only": True, "no_key_no_wallet_no_tx_no_deploy": True,
        "sources_basescan": {"slip_factory": SLIP_FACTORY, "slip_quoter": SLIP_QUOTER,
                             "slip_router": SLIP_ROUTER, "univ3_quoter": "0x3d4e44Eb1374240CE5F1B871ab261CD16335B76a",
                             "univ3_router": UNIV3_ROUTER},
        "params": {"sizes_usd": SIZES_USD, "univ3_fee": UNIV3_FEE,
                   "slip_tickspacings_candidats": SLIP_TICKSPACINGS},
        **prov, "created_utc": now_utc(),
    }

    w3 = None
    for url in endpoints("base"):
        try:
            cand = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 30}))
            if cand.eth.chain_id == CHAIN_ID and cand.eth.block_number > 0:
                w3 = cand
                break
        except Exception:
            continue
    if w3 is None:
        return abstain(run_dir, manifest, "RPC/archive insuffisant : aucun endpoint Base sain")
    head = w3.eth.block_number
    manifest["head_block"] = head

    # --- Vérification on-chain : code présent (factory/quoter/router) ---
    for name, addr in [("slip_factory", SLIP_FACTORY), ("slip_quoter", SLIP_QUOTER),
                       ("slip_router", SLIP_ROUTER), ("univ3_router", UNIV3_ROUTER)]:
        try:
            if len(w3.eth.get_code(addr)) <= 2:
                return abstain(run_dir, manifest, f"adresse sans code : {name} {addr}")
        except Exception as e:
            return abstain(run_dir, manifest, f"lecture code {name} KO ({type(e).__name__})")

    # --- Uni v3 quoter vérifié + prix WETH de tête ---
    uq = V3Quoter(w3, "univ3")
    ok, why = uq.verify(WETH, USDC, block=head)
    if not ok:
        return abstain(run_dir, manifest, f"quoteur Uni v3 non vérifié : {why}")
    u_price = uq.quote(WETH, USDC, 10 ** 18, UNIV3_FEE, head)
    if u_price is None:
        return abstain(run_dir, manifest, "Uni v3 : 1 WETH→USDC ne quote pas (palier 500)")
    weth_price = u_price[0] / 1e6

    # --- Intégrité : le quoter doit pointer vers SLIP_FACTORY (paire appariée, autorité sur le label) ---
    try:
        qf = addr_from_word(bytes(w3.eth.call({"to": SLIP_QUOTER, "data": "0x" + SEL_FACTORY.hex()}, head)))
    except Exception as e:
        return abstain(run_dir, manifest, f"quoter.factory() illisible ({type(e).__name__})")
    if qf != SLIP_FACTORY:
        return abstain(run_dir, manifest, f"quoter.factory()={qf} != SLIP_FACTORY attendu -> non fiable")
    manifest["quoter_factory_verified"] = qf

    # --- Découverte du pool SlipStream WETH/USDC : on retient le plus PROFOND (same-token, quotable) ---
    slip_pool, slip_ts, best_out, candidates = None, None, -1, []
    for ts in SLIP_TICKSPACINGS:
        try:
            ret = w3.eth.call({"to": SLIP_FACTORY, "data": "0x" + getpool_calldata(WETH, USDC, ts).hex()}, head)
        except Exception:
            continue
        pool = addr_from_word(bytes(ret))
        if pool is None or len(w3.eth.get_code(pool)) <= 2:
            continue
        try:
            t0 = addr_from_word(bytes(w3.eth.call({"to": pool, "data": "0x" + SEL_TOKEN0.hex()}, head)))
            t1 = addr_from_word(bytes(w3.eth.call({"to": pool, "data": "0x" + SEL_TOKEN1.hex()}, head)))
        except Exception:
            continue
        if not (t0 and t1 and same_tokens(t0, t1, WETH, USDC)):
            continue
        q = slip_quote(w3, WETH, USDC, 10 ** 18, ts, head)
        if q is None or not (100.0 < q / 1e6 < 100_000.0):
            continue
        candidates.append({"tick_spacing": ts, "pool": pool, "weth_price_usd": round(q / 1e6, 2)})
        if q > best_out:                       # on retient le pool le plus profond (slippage minimal a 1 WETH)
            best_out, slip_pool, slip_ts = q, pool, ts
            manifest["slipstream_pool"] = {"pool": pool, "tick_spacing": ts, "token0": t0, "token1": t1,
                                           "weth_price_usd": round(q / 1e6, 2)}
    manifest["slipstream_pool_candidates"] = candidates
    if slip_pool is None:
        return abstain(run_dir, manifest,
                       "pool SlipStream WETH/USDC introuvable/non quotable (factory/quoter/tickSpacing non fiables)")

    # --- Certification : mêmes contrats WETH et USDC dans les deux protocoles ---
    manifest["same_contracts_certified"] = {
        "weth": WETH, "usdc": USDC,
        "univ3_uses": [WETH, USDC], "slipstream_pool_tokens": sorted([slip_pool and manifest["slipstream_pool"]["token0"],
                                                                      manifest["slipstream_pool"]["token1"]]),
        "identical": True}

    # --- Quotes EXACTES cross-protocole au MÊME bloc, deux orientations (round-trip BRUT, indicatif) ---
    in_weth = {s: int(s / weth_price * 1e18) for s in SIZES_USD}
    gross = {}
    for s in SIZES_USD:
        gross[str(s)] = {}
        # uni_then_slip : WETH->USDC (Uni v3), USDC->WETH (SlipStream)
        u1 = uq.quote(WETH, USDC, in_weth[s], UNIV3_FEE, head)
        s2 = slip_quote(w3, USDC, WETH, u1[0], slip_ts, head) if u1 else None
        gross[str(s)]["uni_then_slip_usd"] = (round(wei_to_usd(gross_roundtrip_wei(s2, in_weth[s]), weth_price), 4)
                                              if (u1 and s2) else None)
        # slip_then_uni : WETH->USDC (SlipStream), USDC->WETH (Uni v3)
        s1 = slip_quote(w3, WETH, USDC, in_weth[s], slip_ts, head)
        u2 = uq.quote(USDC, WETH, s1, UNIV3_FEE, head) if s1 else None
        gross[str(s)]["slip_then_uni_usd"] = (round(wei_to_usd(gross_roundtrip_wei(u2[0], in_weth[s]), weth_price), 4)
                                              if (s1 and u2) else None)
    manifest["gross_roundtrip_usd_INDICATIF"] = gross
    manifest["gross_note"] = ("Round-trip BRUT (quotes seules, AUCUN gas) — INDICATIF que la mesure de quote "
                              "cross-protocole est faisable. JAMAIS un net ni un PnL (l'enveloppe gas exacte "
                              "n'est pas constructible, cf verdict).")

    # --- Enveloppe atomique EXACTE : déterminisme architectural ---
    any_quote = any(v.get("uni_then_slip_usd") is not None or v.get("slip_then_uni_usd") is not None
                    for v in gross.values())
    manifest["envelope_atomic_exact"] = {
        "constructible_read_only": False,
        "routers": {"univ3_swaprouter02": UNIV3_ROUTER + " (route UNIQUEMENT des pools Uniswap v3)",
                    "slipstream_router": SLIP_ROUTER + " (route UNIQUEMENT des pools SlipStream)"},
        "reason": ("Aucun routeur canonique ne chaîne un pool Uniswap v3 ET un pool SlipStream dans une "
                   "seule transaction : SwapRouter02 résout ses pools via la factory Uniswap (path = fee "
                   "tiers), le SlipStream Router via la factory SlipStream (tickSpacing). Un round-trip "
                   "atomique cross-protocole exigerait un contrat EXÉCUTEUR déployé (INTERDIT : aucun "
                   "déploiement). Donc le calldata atomique EXACT n'existe pas read-only -> estimateGas L2 "
                   "et coût L1/data sur OCTETS EXACTS impossibles."),
        "consequence": "Enveloppe atomique cross-protocole EXACTE NON ÉTABLIE -> NON_CONCLUANT (bloque le scanner)."}

    manifest["verdict"] = "NON_CONCLUANT"
    manifest["verdict_detail"] = ("Préconditions VÉRIFIÉES (infra SlipStream canonique on-chain ; mêmes "
                                  "contrats WETH/USDC ; quotes exactes cross-protocole faisables) MAIS "
                                  "enveloppe atomique EXACTE non constructible read-only (aucun routeur "
                                  "cross-protocole ; exécuteur = déploiement interdit). NON_CONCLUANT précis : "
                                  "BLOQUE tout scanner cible. Capture atomique cross-protocole = territoire "
                                  "MEV-exécuteur par construction, hors périmètre.")
    manifest["abstention_reason"] = "enveloppe atomique exacte cross-protocole non constructible (aucun routeur canonique ; déploiement interdit)"

    # --- Reçu brut (quotes) hors Git, hashé ---
    raw_dir = os.path.join(HERE, "data", "raw", "defi", "d1_5")
    os.makedirs(raw_dir, exist_ok=True)
    raw = json.dumps({"head": head, "weth_price": weth_price, "slip_ts": slip_ts, "gross": gross},
                     ensure_ascii=False).encode()
    raw_path = os.path.join(raw_dir, f"quotes_{stamp}.json")
    with open(raw_path, "wb") as f:
        f.write(raw)
    manifest["receipts"] = [{"name": "quotes", "sha256": hashlib.sha256(raw).hexdigest(),
                             "raw_path": os.path.relpath(raw_path, HERE).replace("\\", "/")}]

    os.makedirs(run_dir, exist_ok=True)
    rep = [f"# Rapport D1.5 — enveloppe atomique cross-protocole Uni v3 ↔ SlipStream (Base)", "",
           "- **Verdict : NON_CONCLUANT** (enveloppe atomique EXACTE non constructible read-only).",
           f"- Provenance : git `{prov['git_hash'][:10]}` ; code_versioned={prov['code_versioned']} ; "
           f"git_dirty={prov['git_dirty']}",
           f"- Infra SlipStream **vérifiée on-chain** : factory `{SLIP_FACTORY[:10]}…`, quoter "
           f"`{SLIP_QUOTER[:10]}…`, router `{SLIP_ROUTER[:10]}…` ; pool WETH/USDC tickSpacing={slip_ts}.",
           f"- **Mêmes contrats WETH/USDC certifiés** dans les deux protocoles.",
           "", "## Round-trip BRUT cross-protocole (quotes seules, AUCUN gas — INDICATIF)", "```json",
           json.dumps(gross, ensure_ascii=False, indent=2), "```",
           "## Pourquoi NON_CONCLUANT (précis)",
           manifest["envelope_atomic_exact"]["reason"],
           "", "> Capture atomique cross-protocole = territoire MEV-exécuteur (contrat déployé) par "
           "construction. Hors périmètre non-MEV / no-deploy. **Ce NON_CONCLUANT BLOQUE tout scanner cible.** "
           "Aucun token cible, aucun PnL, aucun bot."]
    with open(os.path.join(run_dir, "report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(rep) + "\n")

    write_and_print(run_dir, manifest, {
        "verdict": "NON_CONCLUANT",
        "envelope_constructible": False,
        "preconditions_verified": {"slipstream_infra": True, "same_weth_usdc": True,
                                   "crossprotocol_quotes_feasible": any_quote},
        "slip_pool": slip_pool, "slip_tickspacing": slip_ts,
        "gross_roundtrip_usd_indicatif": gross,
        "run_dir": os.path.relpath(run_dir, HERE).replace("\\", "/")})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
