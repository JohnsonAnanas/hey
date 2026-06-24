#!/usr/bin/env python
"""Runner D1.6 — enveloppe atomique cross-protocole par EXÉCUTEUR SIMULÉ (Base), READ-ONLY.

Mesure l'enveloppe atomique EXACTE d'un round-trip Uniswap v3 (SwapRouter02, `fee`) <-> Aerodrome
SlipStream (Router, `tickSpacing`) sur le contrôle WETH/USDC, en SIMULANT le contrat exécuteur d'un searcher
(le seul moyen de chaîner les deux protocoles en une tx) — SANS déployer, signer, ni détenir de capital.

Méthode (read-only) : on injecte le bytecode de `CrossProtocolExecutor` (versionné, contracts/) comme `code`
via state-override sur une adresse FACTICE, on override sa balance WETH (slot 3) + ETH (gas) ; l'exécuteur
approuve lui-même les tokens (pas d'override d'allowance). On mesure :
  - sortie atomique EXACTE   : eth_call(executeur.run(...)) -> WETH final (les 2 swaps dans la même exécution) ;
  - gas L2 EXACT             : eth_estimateGas(...) sur les octets exacts de l'appel ;
  - coût L1/data EXACT       : OP-stack GasPriceOracle.getL1Fee(tx sérialisé exact).
gas_normal = gas_units × base_fee_L2(bloc) + l1Fee(bloc) ; priorité MEV EXCLUE -> upper_bound = BORNE SUP.
L'exécuteur REVERT si la sortie finale < minOut (modèle searcher) ; en mesure minOut=0 (sortie réelle).

STRICTEMENT read-only : eth_call / eth_estimateGas / getL1Fee + state-override. AUCUN déploiement, clé,
wallet, approbation réelle ni transaction signée. Le code-override est VÉRIFIÉ honoré pour estimateGas
(INVALID -> revert) ; sinon NON_CONCLUANT, aucun fallback approximatif.

Mêmes blocs/tailles/orientations que D1 : 300 blocs, $250/$1k/$2.5k/$5k/$10k, deux orientations
(uni->slip, slip->uni). Sortie : courbe upper_bound atomique complète + persistance, contrôle WETH/USDC seul.
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
from sim.quote_v3 import V3Quoter  # noqa: E402
from d1_mev_boundary_control import (  # noqa: E402  (helpers PURS déjà testés)
    raw_rpc, serialize_dummy_1559, upper_bound_wei, wei_to_usd, run_length_positive, mapping_slot,
    edge_verdict, WETH, USDC, CHAIN_ID, HUGE, GASORACLE, SEL_GETL1FEE, ROUTER as UNI_ROUTER)

HERE = os.path.dirname(os.path.abspath(__file__))
SLIP_ROUTER = Web3.to_checksum_address("0xbe6d8f0d05cc4be24d5167a3ef062215be6d18a5")
FAKE = Web3.to_checksum_address("0x00000000000000000000000000000000DeaDBeef")
FEE = 500          # Uniswap v3 (palier WETH/USDC le plus liquide)
TICKSPACING = 100  # SlipStream WETH/USDC (pool le plus profond, cf D1.5)
SIZES_USD = [250, 1000, 2500, 5000, 10000]
N_BLOCKS = 300
ORIENTATIONS = ["uni_then_slip", "slip_then_uni"]
EXEC_JSON = os.path.join(HERE, "contracts", "CrossProtocolExecutor.json")

SEL_UNI_THEN_SLIP = Web3.keccak(text="uniThenSlip(address,address,address,address,uint24,int24,uint256,uint256)")[:4]
SEL_SLIP_THEN_UNI = Web3.keccak(text="slipThenUni(address,address,address,address,int24,uint24,uint256,uint256)")[:4]
SEL_DECIMALS = Web3.keccak(text="decimals()")[:4]


def exec_calldata(orient: str, amount_in: int, min_out: int = 0) -> bytes:
    if orient == "uni_then_slip":
        return SEL_UNI_THEN_SLIP + abi_encode(
            ["address", "address", "address", "address", "uint24", "int24", "uint256", "uint256"],
            [UNI_ROUTER, SLIP_ROUTER, WETH, USDC, FEE, TICKSPACING, int(amount_in), int(min_out)])
    return SEL_SLIP_THEN_UNI + abi_encode(
        ["address", "address", "address", "address", "int24", "uint24", "uint256", "uint256"],
        [SLIP_ROUTER, UNI_ROUTER, WETH, USDC, TICKSPACING, FEE, int(amount_in), int(min_out)])


def override_exec(bytecode_hex: str) -> dict:
    """code = exécuteur ; balance ETH (gas) ; balance WETH (slot 3, WETH9). Pas d'override d'allowance."""
    return {FAKE: {"code": bytecode_hex, "balance": hex(HUGE)},
            WETH: {"stateDiff": {mapping_slot(FAKE, 3): "0x" + HUGE.to_bytes(32, "big").hex()}}}


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


def abstain(run_dir, manifest, reason: str) -> int:
    manifest["verdict"] = "NON_CONCLUANT"
    manifest["abstention_reason"] = reason
    manifest["created_utc"] = now_utc()
    os.makedirs(run_dir, exist_ok=True)
    with open(os.path.join(run_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(json.dumps({"verdict": "NON_CONCLUANT", "reason": reason,
                      "run_dir": os.path.relpath(run_dir, HERE).replace("\\", "/")}, ensure_ascii=False))
    return 0


def main() -> int:
    prov = provenance()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    raw_dir = os.path.join(HERE, "data", "raw", "defi", "d1_6")
    run_dir = os.path.join(HERE, "runs", f"{stamp}_d1_6-simulated-executor-envelope-weth-usdc")
    os.makedirs(raw_dir, exist_ok=True)
    os.makedirs(run_dir, exist_ok=True)
    exec_meta = json.load(open(EXEC_JSON, encoding="utf-8"))
    bytecode = exec_meta["deployed_bytecode"]
    manifest = {
        "phase": "D1.6", "track": "defi-samechain-mev-boundary", "chain": "base", "pair": "WETH/USDC",
        "method": "executeur SIMULE par state-override de code (read-only ; aucun deploiement/cle/wallet/tx)",
        "read_only": True, "no_deploy_no_key_no_wallet_no_tx": True,
        "executor": {"source_file": exec_meta["source_file"], "source_sha256": exec_meta["source_sha256"],
                     "solc_version": exec_meta["solc_version"],
                     "deployed_bytecode_sha256": exec_meta["deployed_bytecode_sha256"],
                     "bytes": (len(bytecode) - 2) // 2},
        "params": {"sizes_usd": SIZES_USD, "n_blocks": N_BLOCKS, "orientations": ORIENTATIONS,
                   "univ3_router": UNI_ROUTER, "univ3_fee": FEE, "slip_router": SLIP_ROUTER,
                   "slip_tickspacing": TICKSPACING},
        "created_utc": now_utc(), **prov,
        "note": ("Priorite MEV EXCLUE -> upper_bound = BORNE SUPERIEURE (pas un PnL). Controle WETH/USDC seul. "
                 "Aucun token cible, aucun scanner, aucun bot. Le brut negatif n'est PAS un rejet universel."),
    }

    w3, rpc_url = None, None
    for url in endpoints("base"):
        try:
            cand = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 40}))
            if cand.eth.chain_id == CHAIN_ID and cand.eth.block_number > 0:
                w3, rpc_url = cand, url
                break
        except Exception:
            continue
    if w3 is None:
        return abstain(run_dir, manifest, "RPC/archive insuffisant : aucun endpoint Base sain")
    head = w3.eth.block_number
    manifest["head_block"] = head

    # Identité : decimals + prix WETH (Uni v3) pour le sizing ; pool SlipStream ts=100 quotable
    try:
        dw = int.from_bytes(w3.eth.call({"to": WETH, "data": "0x" + SEL_DECIMALS.hex()})[-32:], "big")
        du = int.from_bytes(w3.eth.call({"to": USDC, "data": "0x" + SEL_DECIMALS.hex()})[-32:], "big")
    except Exception as e:
        return abstain(run_dir, manifest, f"identite decimals KO ({type(e).__name__})")
    if (dw, du) != (18, 6):
        return abstain(run_dir, manifest, f"decimals inattendus WETH={dw} USDC={du}")
    uq = V3Quoter(w3, "univ3")
    ok, why = uq.verify(WETH, USDC, block=head)
    if not ok:
        return abstain(run_dir, manifest, f"quoteur Uni v3 non verifie : {why}")
    pq = uq.quote(WETH, USDC, 10 ** 18, FEE, head)
    if pq is None:
        return abstain(run_dir, manifest, "Uni v3 1 WETH->USDC ne quote pas")
    weth_price = pq[0] / 1e6
    in_weth = {s: int(s / weth_price * 1e18) for s in SIZES_USD}

    # --- VÉRIFICATION du code-override pour estimateGas (sinon NON_CONCLUANT, aucun fallback) ---
    head_hex = hex(head)
    ov = override_exec(bytecode)
    # (1) INVALID -> estimateGas DOIT revert
    inv = override_exec("0xfe")
    cd0 = exec_calldata("uni_then_slip", in_weth[1000])
    tx0 = {"from": FAKE, "to": FAKE, "value": "0x0", "data": "0x" + cd0.hex()}
    _, e_inv = raw_rpc(rpc_url, "eth_estimateGas", [tx0, head_hex, inv])
    if not e_inv:
        return abstain(run_dir, manifest, "code-override NON honore par estimateGas (INVALID n'a pas revert)")
    # (2) exécuteur : eth_call sortie saine + estimateGas plausible
    c_res, c_err = raw_rpc(rpc_url, "eth_call", [tx0, head_hex, ov])
    g_res, g_err = raw_rpc(rpc_url, "eth_estimateGas", [tx0, head_hex, ov])
    if c_err or g_err or c_res is None or g_res is None:
        return abstain(run_dir, manifest, f"executeur simule KO (eth_call/estimateGas) : {c_err or g_err}")
    out0 = int(c_res, 16)
    if not (0.90 * in_weth[1000] < out0 < 1.05 * in_weth[1000]) or int(g_res, 16) < 100_000:
        return abstain(run_dir, manifest, f"executeur sortie/gas hors bande (out={out0}, gas={int(g_res,16)})")
    # (3) getL1Fee sur les octets exacts
    ser0 = serialize_dummy_1559(CHAIN_ID, int(g_res, 16), FAKE, cd0,
                                (w3.eth.get_block(head).get("baseFeePerGas") or 1) * 2, 10 ** 6)
    l1_res, l1_err = raw_rpc(rpc_url, "eth_call",
                             [{"to": GASORACLE, "data": "0x" + (SEL_GETL1FEE + abi_encode(["bytes"], [ser0])).hex()},
                              head_hex])
    if l1_err or l1_res is None or int(l1_res, 16) <= 0:
        return abstain(run_dir, manifest, f"cout L1 inconnu : getL1Fee KO ({l1_err})")
    manifest["calibration"] = {"block": head, "out_1WETH_uni_then_slip_wei": out0,
                               "gas_units_l2_head": int(g_res, 16), "l1_fee_wei_head": int(l1_res, 16),
                               "code_override_estimategas_verified": True, "weth_price_usd_head": round(weth_price, 2)}

    # gas_units L2 par (orientation, taille) au bloc de tête (caches ; base_fee + l1 par bloc ensuite)
    gas_units = {}
    for orient in ORIENTATIONS:
        for s in SIZES_USD:
            cd = exec_calldata(orient, in_weth[s])
            gr, ge = raw_rpc(rpc_url, "eth_estimateGas",
                             [{"from": FAKE, "to": FAKE, "value": "0x0", "data": "0x" + cd.hex()}, head_hex, ov])
            gas_units[(orient, s)] = int(gr, 16) if (gr and not ge) else None

    # --- Boucle 300 blocs : sortie atomique exacte (eth_call) + gas complet par bloc ---
    blocks = list(range(head - N_BLOCKS + 1, head + 1))
    series = {(o, s): [] for o in ORIENTATIONS for s in SIZES_USD}
    fail_blocks = 0
    for b in blocks:
        bhex = hex(b)
        try:
            bf = w3.eth.get_block(b).get("baseFeePerGas") or 0
            pq_b = uq.quote(WETH, USDC, 10 ** 18, FEE, b)
            px = (pq_b[0] / 1e6) if pq_b else weth_price
            l1_by_orient = {}
            for orient in ORIENTATIONS:
                gu = gas_units[(orient, 1000)] or int(g_res, 16)
                ser = serialize_dummy_1559(CHAIN_ID, gu, FAKE, exec_calldata(orient, in_weth[1000]),
                                           max(bf, 1) * 2, 10 ** 6)
                lr, le = raw_rpc(rpc_url, "eth_call",
                                 [{"to": GASORACLE, "data": "0x" + (SEL_GETL1FEE + abi_encode(["bytes"], [ser])).hex()},
                                  bhex])
                l1_by_orient[orient] = int(lr, 16) if (lr and not le) else None
            for orient in ORIENTATIONS:
                for s in SIZES_USD:
                    cd = exec_calldata(orient, in_weth[s])
                    cr, ce = raw_rpc(rpc_url, "eth_call",
                                     [{"from": FAKE, "to": FAKE, "data": "0x" + cd.hex()}, bhex, ov])
                    gu, l1 = gas_units[(orient, s)], l1_by_orient[orient]
                    if ce or cr is None or gu is None or l1 is None or bf <= 0:
                        series[(orient, s)].append(None)
                        continue
                    ubw = upper_bound_wei(int(cr, 16), in_weth[s], gu, bf, l1)
                    series[(orient, s)].append(wei_to_usd(ubw, px))
        except Exception as e:
            fail_blocks += 1
            for k in series:
                series[k].append(None)
            if fail_blocks <= 3:
                print(f"  bloc {b} KO : {type(e).__name__}: {str(e)[:60]}")
            if fail_blocks > N_BLOCKS * 0.1:
                return abstain(run_dir, manifest, f"RPC insuffisant : {fail_blocks} blocs en echec (>10%)")

    # Reçu brut hashé hors Git
    raw = json.dumps({f"{o}|{s}": series[(o, s)] for o in ORIENTATIONS for s in SIZES_USD}, ensure_ascii=False).encode()
    raw_path = os.path.join(raw_dir, f"series_{stamp}.json")
    with open(raw_path, "wb") as f:
        f.write(raw)

    # Courbes + persistance + verdict
    curves, persistence, positive, has_valid = {}, {}, False, False
    for s in SIZES_USD:
        curves[str(s)] = {}
        for o in ORIENTATIONS:
            vals = [v for v in series[(o, s)] if v is not None]
            if vals:
                has_valid = True
                vs = sorted(vals)
                curves[str(s)][o] = {"n": len(vals), "median_usd": round(vs[len(vs) // 2], 4),
                                     "max_usd": round(max(vals), 4), "min_usd": round(min(vals), 4)}
                persistence[f"{o}|{s}"] = run_length_positive([x is not None and x > 0 for x in series[(o, s)]])
                if max(vals) > 0:
                    positive = True
    edge = edge_verdict(positive, has_valid)
    manifest.update({
        "blocks_window": {"first": blocks[0], "last": blocks[-1], "count": len(blocks), "fail_blocks": fail_blocks},
        "input_weth_wei_frozen": {str(s): in_weth[s] for s in SIZES_USD},
        "gas_units_l2_by_orient_size": {f"{o}|{s}": gas_units[(o, s)] for o in ORIENTATIONS for s in SIZES_USD},
        "curves_size_to_upper_bound_usd": curves, "persistence_descriptive": persistence,
        "gas_qc": {"l2_included": True, "l1_included": True, "priority_excluded": True,
                   "gas_source": "estimateGas (code-override executeur) ; L1 = getL1Fee octets exacts"},
        "receipts": [{"name": "series", "sha256": hashlib.sha256(raw).hexdigest(),
                      "raw_path": os.path.relpath(raw_path, HERE).replace("\\", "/")}],
        "verdict_edge": edge, "verdict": edge,
        "control_anomaly_audit_renforce": (edge == "ATOMIC_MEV_SCOPE"),
        "interpretation": ("Enveloppe atomique cross-protocole CALIBREE par executeur simule. Controle attendu "
                           "NO_ATOMIC_EDGE. Un positif -> AUDIT RENFORCE (jamais un PnL tradable). Le brut negatif "
                           "n'est PAS un rejet universel : seulement ce controle a cet instant."),
    })
    with open(os.path.join(run_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    lines = [f"# Rapport D1.6 — enveloppe atomique cross-protocole par executeur simule (Base)", "",
             f"- **Verdict edge : {edge}**" + ("  ⚠️ AUDIT RENFORCE" if edge == "ATOMIC_MEV_SCOPE" else ""),
             f"- Provenance : git `{prov['git_hash'][:10]}` ; code_versioned={prov['code_versioned']} ; "
             f"git_dirty={prov['git_dirty']} ; executeur src sha `{exec_meta['source_sha256'][:16]}…`",
             f"- Fenetre : blocs {blocks[0]}-{blocks[-1]} ({len(blocks)} ; echecs {fail_blocks})",
             f"- Enveloppe (tete) : out(1 WETH, uni->slip)={out0/1e18:.6f} ; gas_units_L2={int(g_res,16)} ; "
             f"l1Fee={int(l1_res,16)} wei ; code-override estimateGas VERIFIE",
             "", "## Courbes taille -> upper_bound_atomique (USD)", "```json",
             json.dumps(curves, ensure_ascii=False, indent=2), "```",
             "> Enveloppe atomique cross-protocole CALIBREE (executeur SIMULE, read-only ; aucun deploiement/cle/"
             "wallet/tx). Priorite MEV exclue = borne superieure. Controle ; aucun PnL tradable, aucun token cible, "
             "aucun bot. Le brut negatif n'est PAS un rejet universel."]
    with open(os.path.join(run_dir, "report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print(json.dumps({"verdict_edge": edge, "blocks": len(blocks), "fail_blocks": fail_blocks,
                      "envelope_calibrated": True, "out_1weth_uni_then_slip": round(out0 / 1e18, 6),
                      "gas_units_head": int(g_res, 16), "l1_fee_head": int(l1_res, 16),
                      "run_dir": os.path.relpath(run_dir, HERE).replace("\\", "/"),
                      "curves": curves}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
