#!/usr/bin/env python
"""Runner D1 — contrôle WETH/USDC same-chain (Base), LECTURE SEULE, calibration de l'enveloppe atomique.

Objectif : CALIBRER l'enveloppe de mesure atomique du track MEV boundary map (D0 §4), PAS exécuter un
arbitrage ni rechercher du capital. Contrôle attendu : `NO_ATOMIC_EDGE` (round-trip WETH→USDC→WETH entre
deux paliers Uniswap v3 = perte garantie des frais ; un POSITIF déclenche un AUDIT RENFORCÉ, pas un faux
positif automatique).

STRICTEMENT read-only : eth_call / estimate_gas / getL1Fee uniquement. AUCUN contrat déployé, AUCUNE clé,
AUCUN wallet, AUCUNE approbation, AUCUNE transaction envoyée. Le `from` est une adresse factice ; les
balances/allowances WETH sont SIMULÉES par state-override (jamais signées). La sérialisation getL1Fee
utilise une signature factice CONSTANTE (aucune clé dérivée).

Enveloppe d'exécution FIGÉE (D0 §4) :
  - routeur : Uniswap SwapRouter02 (Base) 0x2626664c2603336E57B271c5C0b26F421741e481 ;
  - ordre : WETH→USDC (tier A) puis USDC→WETH (tier B), un seul exactInput 2-hop atomique ;
  - type de tx : EIP-1559 ; modèle de calldata : exactInput((bytes path, address recipient, uint256
    amountIn, uint256 amountOutMinimum=0)) ;
  - source gas_units : eth_estimate_gas du tx ci-dessus AVEC state-override (balance+allowance WETH),
    override AUTO-VÉRIFIÉ par eth_call (balanceOf/allowance) avant tout usage ;
  - coût L1/data : OP-stack GasPriceOracle.getL1Fee(tx sérialisé).
  gas_normal = gas_units × base_fee_L2(bloc) + l1Fee(bloc). Priorité MEV EXCLUE → borne SUPÉRIEURE.

Paramètres FIGÉS (D0) : grille $250/$1k/$2.5k/$5k/$10k ; minimum_research_notional=$1k ; N=300 blocs ;
deux orientations (tiers 500/3000 et 3000/500). Quotes EXACTES via QuoterV2 (jamais mid).

STOP → NON_CONCLUANT (sans fallback inventé) : identité/pools introuvables ; enveloppe non simulable
(override refusé / estimate_gas KO / getL1Fee KO) ; gas Base incomplet (L2 ou L1 manquant) ; quote non
exacte ; RPC/archive insuffisant.

Sorties : courbes taille→upper_bound_atomique, persistance descriptive, QC de gas, verdicts D0. AUCUNE
sélection de token cible, AUCUN scanner large, AUCUN bot MEV, AUCUN PnL présenté comme tradable.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

import requests
import rlp
from eth_abi import encode as abi_encode
from web3 import Web3

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from archive_rpc import endpoints  # noqa: E402
from sim.chain import ABI_MC3, MULTICALL3  # noqa: E402
from sim.quote_v3 import V3Quoter  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
CHAIN_ID = 8453
WETH = Web3.to_checksum_address("0x4200000000000000000000000000000000000006")
USDC = Web3.to_checksum_address("0x833589fcd6edb6e08f4c7c32d4f71b54bda02913")
ROUTER = Web3.to_checksum_address("0x2626664c2603336E57B271c5C0b26F421741e481")   # Uniswap SwapRouter02
GASORACLE = Web3.to_checksum_address("0x420000000000000000000000000000000000000F")  # OP-stack predeploy
SENDER = Web3.to_checksum_address("0x00000000000000000000000000000000DeaDBeef")     # factice (jamais signé)

TIER_A, TIER_B = 500, 3000
SIZES_USD = [250, 1000, 2500, 5000, 10000]
MIN_NOTIONAL = 1000
N_BLOCKS = 300
ORIENTATIONS = [("500_3000", TIER_A, TIER_B), ("3000_500", TIER_B, TIER_A)]
WETH_BAL_SLOT_INDEX = 3      # WETH9 : mapping balanceOf  (auto-vérifié à l'exécution)
WETH_ALLOW_SLOT_INDEX = 4    # WETH9 : mapping allowance  (auto-vérifié à l'exécution)
HUGE = 10 ** 24

SEL_EXACTINPUT = Web3.keccak(text="exactInput((bytes,address,uint256,uint256))")[:4]
SEL_QUOTE = Web3.keccak(text="quoteExactInputSingle((address,address,uint256,uint24,uint160))")[:4]
SEL_GETL1FEE = Web3.keccak(text="getL1Fee(bytes)")[:4]
SEL_BALANCEOF = Web3.keccak(text="balanceOf(address)")[:4]
SEL_ALLOWANCE = Web3.keccak(text="allowance(address,address)")[:4]
SEL_DECIMALS = Web3.keccak(text="decimals()")[:4]


# ---------------------------------------------------------------------------------------------------
# Fonctions PURES (testables hors réseau)
# ---------------------------------------------------------------------------------------------------
def encode_v3_path(tokens: list[str], fees: list[int]) -> bytes:
    """Chemin Uniswap v3 : token(20) + fee(3) + token(20) + ... ; len(tokens)==len(fees)+1."""
    assert len(tokens) == len(fees) + 1
    out = bytes.fromhex(tokens[0][2:])
    for f, t in zip(fees, tokens[1:]):
        out += int(f).to_bytes(3, "big") + bytes.fromhex(t[2:])
    return out


def exact_input_calldata(path: bytes, recipient: str, amount_in: int) -> bytes:
    """calldata SwapRouter02.exactInput((path, recipient, amountIn, amountOutMinimum=0))."""
    enc = abi_encode(["(bytes,address,uint256,uint256)"],
                     [(path, Web3.to_checksum_address(recipient), int(amount_in), 0)])
    return SEL_EXACTINPUT + enc


def quote_calldata(token_in: str, token_out: str, amount_in: int, fee: int) -> bytes:
    enc = abi_encode(["(address,address,uint256,uint24,uint160)"],
                     [(Web3.to_checksum_address(token_in), Web3.to_checksum_address(token_out),
                       int(amount_in), int(fee), 0)])
    return SEL_QUOTE + enc


def mapping_slot(key_addr: str, slot_index: int) -> str:
    """Slot d'un mapping(address=>uint) : keccak256(pad32(key) . pad32(slot))."""
    k = bytes.fromhex(key_addr[2:].rjust(40, "0")) if key_addr.startswith("0x") else key_addr
    key32 = (b"\x00" * 12) + bytes.fromhex(Web3.to_checksum_address(key_addr)[2:])
    slot32 = int(slot_index).to_bytes(32, "big")
    return "0x" + Web3.keccak(key32 + slot32).hex()


def nested_mapping_slot(owner: str, spender: str, slot_index: int) -> str:
    """Slot d'un mapping(address=>mapping(address=>uint)) : allowance[owner][spender]."""
    o32 = (b"\x00" * 12) + bytes.fromhex(Web3.to_checksum_address(owner)[2:])
    inner = Web3.keccak(o32 + int(slot_index).to_bytes(32, "big"))
    s32 = (b"\x00" * 12) + bytes.fromhex(Web3.to_checksum_address(spender)[2:])
    return "0x" + Web3.keccak(s32 + inner).hex()


def serialize_dummy_1559(chain_id: int, gas: int, to_addr: str, data: bytes,
                         max_fee: int, max_prio: int) -> bytes:
    """Sérialise un EIP-1559 tx avec signature FACTICE CONSTANTE (aucune clé) -> bytes pour getL1Fee."""
    fields = [int(chain_id), 0, int(max_prio), int(max_fee), int(gas),
              bytes.fromhex(to_addr[2:]), 0, data, [],
              0, int.from_bytes(b"\x11" * 32, "big"), int.from_bytes(b"\x22" * 32, "big")]
    return b"\x02" + rlp.encode(fields)


def gas_normal_wei(gas_units: int, base_fee_l2: int, l1_fee_wei: int) -> int:
    return int(gas_units) * int(base_fee_l2) + int(l1_fee_wei)


def upper_bound_wei(out2_wei: int, in_wei: int, gas_units: int, base_fee_l2: int, l1_fee_wei: int) -> int:
    """upper_bound atomique en WETH-wei = (amountOut − amountIn) − gas_normal (priorité EXCLUE)."""
    return int(out2_wei) - int(in_wei) - gas_normal_wei(gas_units, base_fee_l2, l1_fee_wei)


def wei_to_usd(weth_wei: int, weth_price_usd: float) -> float:
    return weth_wei / 1e18 * weth_price_usd


def run_length_positive(flags: list[bool]) -> dict:
    """Persistance descriptive : run-length max + fraction de blocs positifs."""
    best = cur = 0
    for f in flags:
        cur = cur + 1 if f else 0
        best = max(best, cur)
    n = len(flags)
    return {"blocks": n, "positive_blocks": sum(1 for f in flags if f),
            "fraction_positive": (sum(1 for f in flags if f) / n) if n else 0.0,
            "max_run_positive": best}


def edge_verdict(any_positive: bool, has_valid_quotes: bool) -> str:
    if not has_valid_quotes:
        return "NON_CONCLUANT"
    return "ATOMIC_MEV_SCOPE" if any_positive else "NO_ATOMIC_EDGE"


def capacity_classify(positive_sizes: list[int], min_notional: int, has_valid: bool) -> str:
    """Dimension capacité (D0) : seuil min_notional figé."""
    if not has_valid:
        return "NON_CONCLUANT"
    ge_min = [s for s in positive_sizes if s >= min_notional]
    sub_min = [s for s in positive_sizes if s < min_notional]
    if ge_min:
        return "CAPACITE_DOCUMENTEE"           # courbe complète $1k–$10k (cf curves)
    if sub_min:
        return "CAPACITY_INSUFFICIENT"          # positif seulement sous $1k
    return "PAS_DE_CAPACITE"                     # (edge négatif partout : NO_ATOMIC_EDGE)


# ---------------------------------------------------------------------------------------------------
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


def aggregate3(w3, calls, block):
    """[(target, calldata)] -> [(success, returnData)] at `block` (allowFailure=True)."""
    mc = w3.eth.contract(address=MULTICALL3, abi=ABI_MC3)
    payload = [(t, True, d) for (t, d) in calls]
    return mc.functions.aggregate3(payload).call(block_identifier=block)


def decode_amount_out(success: bool, ret: bytes):
    if not success or ret is None or len(ret) < 32:
        return None
    out = int.from_bytes(bytes(ret)[:32], "big")
    return out if out > 0 else None


def raw_rpc(url, method, params, timeout=30):
    """JSON-RPC brut (contrôle total du format geth pour state-override / estimateGas)."""
    try:
        r = requests.post(url, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
                          timeout=timeout)
        j = r.json()
        return j.get("result"), j.get("error")
    except Exception as e:
        return None, f"{type(e).__name__}: {str(e)[:60]}"


def main() -> int:
    prov = provenance()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    raw_dir = os.path.join(HERE, "data", "raw", "defi", "d1")  # HORS Git
    run_dir = os.path.join(HERE, "runs", f"{stamp}_d1-mev-boundary-control-weth-usdc")
    os.makedirs(raw_dir, exist_ok=True)
    os.makedirs(run_dir, exist_ok=True)
    manifest = {
        "phase": "D1", "track": "defi-samechain-mev-boundary", "chain": "base", "pair": "WETH/USDC",
        "control": "WETH/USDC entre paliers Uniswap v3 500 / 3000 (attendu NO_ATOMIC_EDGE)",
        "read_only": True, "no_key_no_wallet_no_tx": True,
        "params": {"sizes_usd": SIZES_USD, "min_research_notional": MIN_NOTIONAL, "n_blocks": N_BLOCKS,
                   "orientations": [o[0] for o in ORIENTATIONS], "tiers": [TIER_A, TIER_B]},
        "envelope": {"router": ROUTER, "calldata_model": "exactInput((bytes,address,uint256,uint256))",
                     "tx_type": "eip1559", "gas_units_source": "eth_estimate_gas + state-override (auto-vérifié)",
                     "l1_method": "OP-stack GasPriceOracle.getL1Fee(tx sérialisé, sig factice)"},
        "created_utc": now_utc(), **prov,
        "note": ("Calibration enveloppe atomique (read-only). Priorité MEV EXCLUE -> upper_bound = BORNE "
                 "SUPÉRIEURE, pas un PnL. Aucun chemin capital, aucun token cible, aucun bot MEV."),
    }

    # --- Connexion archive (Alchemy d'abord) ; health-gate chainId + bloc de tête ---
    w3, rpc_url = None, None
    for url in endpoints("base"):
        try:
            cand = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 30}))
            if cand.eth.chain_id == CHAIN_ID and cand.eth.block_number > 0:
                w3, rpc_url = cand, url
                break
        except Exception:
            continue
    if w3 is None:
        return abstain(run_dir, manifest, "RPC/archive insuffisant : aucun endpoint Base sain")
    head = w3.eth.block_number
    manifest["head_block"] = head

    # --- Identité (plancher) : decimals on-chain + quoteur vérifié + 2 pools quotables ---
    try:
        dec_weth = int.from_bytes(w3.eth.call({"to": WETH, "data": "0x" + SEL_DECIMALS.hex()})[-32:], "big")
        dec_usdc = int.from_bytes(w3.eth.call({"to": USDC, "data": "0x" + SEL_DECIMALS.hex()})[-32:], "big")
    except Exception as e:
        return abstain(run_dir, manifest, f"identité : decimals illisibles ({type(e).__name__})")
    if (dec_weth, dec_usdc) != (18, 6):
        return abstain(run_dir, manifest, f"identité : decimals inattendus WETH={dec_weth} USDC={dec_usdc}")
    quoter = V3Quoter(w3, "univ3")
    ok, why = quoter.verify(WETH, USDC, block=head)
    if not ok:
        return abstain(run_dir, manifest, f"quoteur non vérifié : {why}")
    price_q = quoter.quote(WETH, USDC, 10 ** 18, TIER_A, head)
    price_q2 = quoter.quote(WETH, USDC, 10 ** 18, TIER_B, head)
    if price_q is None or price_q2 is None:
        return abstain(run_dir, manifest, "pools introuvables : 1 WETH→USDC ne quote pas sur 500 et/ou 3000")
    weth_price = price_q[0] / 1e6
    manifest["identity"] = {"weth": WETH, "usdc": USDC, "dec_weth": 18, "dec_usdc": 6,
                            "weth_price_usd_head": round(weth_price, 2), "quoter_verified": True}
    in_weth = {s: int(s / weth_price * 1e18) for s in SIZES_USD}   # input WETH figé au prix de tête

    # --- Calibration de l'enveloppe au bloc de tête (override AUTO-VÉRIFIÉ, estimate_gas, getL1Fee) ---
    bal_slot = mapping_slot(SENDER, WETH_BAL_SLOT_INDEX)
    allow_slot = nested_mapping_slot(SENDER, ROUTER, WETH_ALLOW_SLOT_INDEX)
    HUGE_HEX = "0x" + HUGE.to_bytes(32, "big").hex()
    override = {SENDER: {"balance": hex(HUGE)},
                WETH: {"stateDiff": {bal_slot: HUGE_HEX, allow_slot: HUGE_HEX}}}
    head_hex = hex(head)
    # auto-vérification de l'override (JSON-RPC brut) : balanceOf/allowance DOIVENT refléter HUGE
    bo_cd = "0x" + (SEL_BALANCEOF + abi_encode(["address"], [SENDER])).hex()
    al_cd = "0x" + (SEL_ALLOWANCE + abi_encode(["address", "address"], [SENDER, ROUTER])).hex()
    bo, e1 = raw_rpc(rpc_url, "eth_call", [{"to": WETH, "data": bo_cd}, head_hex, override])
    al, e2 = raw_rpc(rpc_url, "eth_call", [{"to": WETH, "data": al_cd}, head_hex, override])
    if e1 or e2 or bo is None or al is None:
        return abstain(run_dir, manifest, f"state-override refusé par le RPC ({e1 or e2})")
    if int(bo, 16) != HUGE or int(al, 16) != HUGE:
        return abstain(run_dir, manifest, "state-override non reflété (slots WETH9 ou RPC) -> non fiable")

    path_head = encode_v3_path([WETH, USDC, WETH], [TIER_A, TIER_B])
    cal_data = exact_input_calldata(path_head, SENDER, in_weth[1000])
    base_fee_head = w3.eth.get_block(head).get("baseFeePerGas") or 0
    g_res, g_err = raw_rpc(rpc_url, "eth_estimateGas",
                           [{"from": SENDER, "to": ROUTER, "value": "0x0", "data": "0x" + cal_data.hex()},
                            head_hex, override])
    if g_err or g_res is None:
        return abstain(run_dir, manifest, f"enveloppe non simulable : estimate_gas KO ({g_err})")
    gas_units_cal = int(g_res, 16)
    ser = serialize_dummy_1559(CHAIN_ID, gas_units_cal, ROUTER, cal_data, base_fee_head * 2, 10 ** 6)
    try:
        l1_ret = w3.eth.call({"to": GASORACLE, "data": "0x" + (SEL_GETL1FEE + abi_encode(["bytes"], [ser])).hex()},
                             head)
        l1_fee_cal = int.from_bytes(l1_ret[-32:], "big")
    except Exception as e:
        return abstain(run_dir, manifest, f"coût L1 inconnu : getL1Fee KO ({type(e).__name__})")
    if base_fee_head <= 0 or gas_units_cal <= 0 or l1_fee_cal <= 0:
        return abstain(run_dir, manifest, "gas Base incomplet (L2 ou L1/data nul) -> abstention")
    manifest["calibration"] = {"block": head, "gas_units_l2": int(gas_units_cal),
                               "base_fee_l2_wei": int(base_fee_head), "l1_fee_wei_head": int(l1_fee_cal),
                               "override_self_check": "OK"}

    # gas_units L2 par (taille, orientation) au bloc de tête (cachés ; ~stables sur la fenêtre)
    gas_units = {}
    for oid, fa, fb in ORIENTATIONS:
        path = encode_v3_path([WETH, USDC, WETH], [fa, fb])
        for s in SIZES_USD:
            data = exact_input_calldata(path, SENDER, in_weth[s])
            gr, ge = raw_rpc(rpc_url, "eth_estimateGas",
                             [{"from": SENDER, "to": ROUTER, "value": "0x0", "data": "0x" + data.hex()},
                              head_hex, override])
            gas_units[(oid, s)] = int(gr, 16) if (gr and not ge) else None

    # --- Boucle 300 blocs : quotes EXACTES au même bloc + gas complet par bloc ---
    blocks = list(range(head - N_BLOCKS + 1, head + 1))
    series = {(oid, s): [] for oid, _, _ in ORIENTATIONS for s in SIZES_USD}   # ub_usd par bloc (None si revert)
    receipts, fail_blocks = [], 0
    for b in blocks:
        try:
            blk = w3.eth.get_block(b)
            bf = blk.get("baseFeePerGas") or 0
            px_q = quoter.quote(WETH, USDC, 10 ** 18, TIER_A, b)
            px = (px_q[0] / 1e6) if px_q else weth_price
            # leg1 (WETH->USDC) batché pour toutes (orient,size)
            leg1_keys, leg1_calls = [], []
            for oid, fa, fb in ORIENTATIONS:
                for s in SIZES_USD:
                    leg1_keys.append((oid, s, fb))
                    leg1_calls.append((quoter.addr, quote_calldata(WETH, USDC, in_weth[s], fa)))
            r1 = aggregate3(w3, leg1_calls, b)
            out1 = {leg1_keys[i][:2]: decode_amount_out(r1[i][0], r1[i][1]) for i in range(len(leg1_keys))}
            # leg2 (USDC->WETH) batché (amountIn = out1)
            leg2_keys, leg2_calls = [], []
            for (oid, fa, fb) in [(o, a, bb) for (o, a, bb) in ORIENTATIONS]:
                for s in SIZES_USD:
                    o1 = out1.get((oid, s))
                    if o1 is None:
                        continue
                    leg2_keys.append((oid, s))
                    leg2_calls.append((quoter.addr, quote_calldata(USDC, WETH, o1, fb)))
            r2 = aggregate3(w3, leg2_calls, b) if leg2_calls else []
            out2 = {leg2_keys[i]: decode_amount_out(r2[i][0], r2[i][1]) for i in range(len(leg2_keys))}
            # L1 fee par orientation à ce bloc (sur le calldata représentatif $1k)
            l1_by_orient = {}
            for oid, fa, fb in ORIENTATIONS:
                path = encode_v3_path([WETH, USDC, WETH], [fa, fb])
                data = exact_input_calldata(path, SENDER, in_weth[1000])
                gu = gas_units[(oid, 1000)] or gas_units_cal
                ser_b = serialize_dummy_1559(CHAIN_ID, gu, ROUTER, data, max(bf, 1) * 2, 10 ** 6)
                lr = w3.eth.call({"to": GASORACLE,
                                  "data": "0x" + (SEL_GETL1FEE + abi_encode(["bytes"], [ser_b])).hex()}, b)
                l1_by_orient[oid] = int.from_bytes(lr[-32:], "big")
            # upper_bound par (orient, size)
            for oid, fa, fb in ORIENTATIONS:
                for s in SIZES_USD:
                    o2, gu, l1 = out2.get((oid, s)), gas_units[(oid, s)], l1_by_orient[oid]
                    if o2 is None or gu is None or bf <= 0 or l1 <= 0:
                        series[(oid, s)].append(None)   # revert/gas incomplet = résultat (capacité)
                        continue
                    ubw = upper_bound_wei(o2, in_weth[s], gu, bf, l1)
                    series[(oid, s)].append(wei_to_usd(ubw, px))
        except Exception as e:
            fail_blocks += 1
            for k in series:
                series[k].append(None)
            if fail_blocks <= 3:
                print(f"  bloc {b} KO : {type(e).__name__}: {str(e)[:60]}")
            if fail_blocks > N_BLOCKS * 0.1:
                return abstain(run_dir, manifest, f"RPC insuffisant : {fail_blocks} blocs en échec (>10%)")

    # --- Reçu brut hashé (séries) hors Git ---
    raw = json.dumps({f"{oid}|{s}": series[(oid, s)] for oid, _, _ in ORIENTATIONS for s in SIZES_USD},
                     ensure_ascii=False).encode()
    raw_path = os.path.join(raw_dir, f"series_{stamp}.json")
    with open(raw_path, "wb") as f:
        f.write(raw)
    receipts.append({"name": "series", "sha256": hashlib.sha256(raw).hexdigest(),
                     "raw_path": os.path.relpath(raw_path, HERE).replace("\\", "/"),
                     "blocks": len(blocks), "fail_blocks": fail_blocks})

    # --- Courbes taille→upper_bound (meilleure orientation), persistance, QC, verdicts ---
    def vals(oid, s):
        return [v for v in series[(oid, s)] if v is not None]
    curves, persistence, positive_sizes, any_positive, has_valid = {}, {}, set(), False, False
    for s in SIZES_USD:
        per_orient = {}
        for oid, _, _ in ORIENTATIONS:
            v = vals(oid, s)
            if v:
                has_valid = True
                v_sorted = sorted(v)
                med = v_sorted[len(v_sorted) // 2]
                per_orient[oid] = {"n": len(v), "median_usd": round(med, 4),
                                   "max_usd": round(max(v), 4), "min_usd": round(min(v), 4)}
                flags = [x > 0 for x in series[(oid, s)] if x is not None]
                persistence[f"{oid}|{s}"] = run_length_positive([x is not None and x > 0
                                                                 for x in series[(oid, s)]])
                if max(v) > 0:
                    any_positive = True
                    positive_sizes.add(s)
        curves[str(s)] = per_orient
    edge = edge_verdict(any_positive, has_valid)
    capacity = capacity_classify(sorted(positive_sizes), MIN_NOTIONAL, has_valid)
    control_anomaly = (edge == "ATOMIC_MEV_SCOPE")   # major positif -> AUDIT RENFORCÉ (pas faux positif auto)

    gas_qc = {"gas_units_l2_by_size_orient": {f"{oid}|{s}": gas_units[(oid, s)]
                                              for oid, _, _ in ORIENTATIONS for s in SIZES_USD},
              "l1_included": True, "l2_included": True, "priority_excluded": True}

    manifest.update({
        "blocks_window": {"first": blocks[0], "last": blocks[-1], "count": len(blocks),
                          "fail_blocks": fail_blocks},
        "input_weth_wei_frozen": {str(s): in_weth[s] for s in SIZES_USD},
        "curves_size_to_upper_bound_usd": curves, "persistence_descriptive": persistence,
        "gas_qc": gas_qc, "receipts": receipts,
        "verdict_edge": edge, "verdict_capacity": capacity, "control_anomaly_audit_renforce": control_anomaly,
        "verdict": edge,
        "interpretation": ("Contrôle attendu NO_ATOMIC_EDGE (round-trip 2 paliers = perte des frais). Un "
                           "ATOMIC_MEV_SCOPE ici => AUDIT RENFORCÉ requis (artefact quote/identité/gas/timing "
                           "ou edge réel fugace), JAMAIS un PnL tradable."),
    })
    with open(os.path.join(run_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    lines = [f"# Rapport D1 — contrôle WETH/USDC same-chain (Base) — calibration enveloppe", "",
             f"- **Verdict edge : {edge}** ; capacité : {capacity}"
             + ("  ⚠️ **AUDIT RENFORCÉ requis**" if control_anomaly else ""),
             f"- Provenance : git `{prov['git_hash'][:10]}` ; code_versioned={prov['code_versioned']} ; "
             f"git_dirty={prov['git_dirty']}",
             f"- Fenêtre : blocs {blocks[0]}–{blocks[-1]} ({len(blocks)}; échecs {fail_blocks})",
             f"- Enveloppe : gas_units_L2(cal)={int(gas_units_cal)} ; base_fee_L2={int(base_fee_head)} wei ; "
             f"l1Fee(head)={int(l1_fee_cal)} wei ; override auto-vérifié OK",
             "", "## Courbes taille → upper_bound_atomique (USD, par orientation)", "```json",
             json.dumps(curves, ensure_ascii=False, indent=2), "```",
             "## QC gas (L2 + L1, priorité exclue → borne supérieure)", "```json",
             json.dumps(gas_qc, ensure_ascii=False, indent=2), "```",
             "> Borne SUPÉRIEURE (priorité MEV exclue). Contrôle ; **aucun PnL tradable**, aucun token cible, "
             "aucun bot MEV. Reçus bruts hors Git, hashés."]
    with open(os.path.join(run_dir, "report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print(json.dumps({"verdict_edge": edge, "verdict_capacity": capacity,
                      "control_anomaly_audit_renforce": control_anomaly,
                      "blocks": len(blocks), "fail_blocks": fail_blocks,
                      "run_dir": os.path.relpath(run_dir, HERE).replace("\\", "/"),
                      "curves": curves}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
