"""Couche chaine partagee (Base, LECTURE SEULE) : RPC GARDE + Multicall3 + selecteurs.

Generaliser, pas dupliquer : utilisee par run_mav_sim.py, run_mav_multi.py, diag_pair.py, verify_data.py.

Garde d'integrite de la SOURCE (Phase 1 — cf docs/data_integrity.md) :
- health-gate au demarrage : on ne garde que les RPC qui repondent en JSON, bon chainId, et <= FRESH_TOL
  blocs du max observe. Quorum >= 2 souhaite (sinon mode degrade signale bruyamment).
- fraicheur par lecture : on recoupe la hauteur de tete sur les fournisseurs sains, on bascule sur le
  plus frais, et on detecte une regression de bloc (reorg / RPC qui recule).
- le NUMERO DE BLOC est la reference temporelle (jamais l'horloge locale).
La decision de fraicheur est isolee en fonctions PURES (`choose_primary`, `is_block_regression`) testees.
"""
from __future__ import annotations

import os
import time

import requests
from web3 import Web3

CHAIN_ID = 8453
RPC_CANDIDATES = [
    # NB: une URL en retard (ex. drpc a ~45h) ou qui renvoie du non-JSON (llamarpc) est ecartee
    # automatiquement par le health-gate ; la liste reste large, le gate fait le tri.
    "https://base.publicnode.com",
    "https://mainnet.base.org",
    "https://1rpc.io/base",
    "https://base.llamarpc.com",
    "https://base.drpc.org",
]
MULTICALL3 = Web3.to_checksum_address("0xcA11bde05977b3631167028862bE2a173976CA11")

FRESH_TOL = 4      # blocs : au-dela, un fournisseur est juge "en retard" (Base ~2s/bloc => ~8s)
REORG_TOL = 3      # blocs : recul au-dela => suspicion de reorg / RPC incoherent
PROBE_TTL = 1.5    # s : on ne re-sonde pas la fraicheur plus souvent que ca (multicalls rapproches)
PROBE_TIMEOUT = 4  # s : timeout des sondes eth_blockNumber

ABI_MC3 = [{"inputs": [{"components": [{"type": "address"}, {"type": "bool"}, {"type": "bytes"}],
                        "type": "tuple[]", "name": "calls"}],
            "name": "aggregate3",
            "outputs": [{"components": [{"type": "bool"}, {"type": "bytes"}],
                         "type": "tuple[]", "name": "ret"}],
            "stateMutability": "payable", "type": "function"}]


def sel(sig: str) -> bytes:
    return Web3.keccak(text=sig)[:4]


SEL_GETPAIR = sel("getPair(address,address)")
SEL_GETPOOL_BOOL = sel("getPool(address,address,bool)")
SEL_GETPOOL_V3 = sel("getPool(address,address,uint24)")
SEL_SLOT0 = sel("slot0()")
SEL_GETFEE = sel("getFee(address,bool)")
SEL_TOKEN0 = sel("token0()")
SEL_TOKEN1 = sel("token1()")
SEL_RESERVES = sel("getReserves()")
SEL_DECIMALS = sel("decimals()")
SEL_STABLE = sel("stable()")
SEL_BLOCKNUM = sel("getBlockNumber()")
SEL_BLOCKTS = sel("getCurrentBlockTimestamp()")
ZERO = "0x0000000000000000000000000000000000000000"


def addr_from(data) -> str | None:
    if data and len(data) >= 32 and int.from_bytes(data, "big") != 0:
        return Web3.to_checksum_address("0x" + data[-20:].hex())
    return None


def uint_from(data) -> int | None:
    return int.from_bytes(data, "big") if data and len(data) >= 32 else None


# --- Decision de fraicheur : PURE et testable (pas de reseau ici) ---

def choose_primary(heights: dict, fresh_tol: int) -> tuple[str | None, dict]:
    """Choisit le fournisseur primaire = le plus FRAIS, et resume la fraicheur.

    heights : {url: hauteur|None}. Retourne (url_primaire|None, info) ou
    info = {n_healthy, n_agree (au tip a fresh_tol pres), max_height, primary_height, ok (quorum>=2)}.
    """
    valid = {u: h for u, h in heights.items() if h is not None}
    info = {"n_healthy": len(valid), "n_agree": 0, "max_height": None, "primary_height": None, "ok": False}
    if not valid:
        return None, info
    mx = max(valid.values())
    fresh = {u: h for u, h in valid.items() if mx - h <= fresh_tol}
    primary = max(fresh, key=lambda u: fresh[u])     # fresh non vide (le max lui-meme y est)
    info.update(n_agree=len(fresh), max_height=mx, primary_height=valid[primary], ok=len(fresh) >= 2)
    return primary, info


def is_block_regression(prev: int, cur: int | None, tol: int) -> bool:
    """Vrai si le bloc courant RECULE de plus de tol vs le precedent (reorg / RPC incoherent)."""
    if not prev or cur is None:
        return False
    return cur < prev - tol


def _probe(url: str, method: str):
    try:
        r = requests.post(url, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": []}, timeout=PROBE_TIMEOUT)
        return int(r.json()["result"], 16)
    except Exception:
        return None


class RPC:
    """Connexion Base GARDEE : health-gate + fraicheur/quorum/monotonie + Multicall3."""

    def __init__(self, candidates: list[str] | None = None):
        env = os.environ.get("RPC_URL_BASE", "").strip()   # RPC dedie optionnel (Alchemy/Infura...)
        urls = [u for u in ([env] + (candidates or RPC_CANDIDATES)) if u]
        # health-gate : chainId correct + repond + fraicheur de demarrage
        heights, dropped = {}, []
        for u in urls:
            if _probe(u, "eth_chainId") != CHAIN_ID:
                dropped.append((u, "chainId/non-repondant")); continue
            h = _probe(u, "eth_blockNumber")
            if h is None:
                dropped.append((u, "blockNumber illisible")); continue
            heights[u] = h
        primary, info = choose_primary(heights, FRESH_TOL)
        if primary is None:
            raise SystemExit("Aucun RPC Base sain (health-gate).")
        mx = info["max_height"]
        self.healthy = [u for u, h in heights.items() if mx - h <= FRESH_TOL]
        for u, h in heights.items():
            if mx - h > FRESH_TOL:
                dropped.append((u, f"en retard de {mx - h} blocs"))
        self._w3 = {u: Web3(Web3.HTTPProvider(u, request_kwargs={"timeout": 12})) for u in self.healthy}
        self.primary = primary
        self.last_block = 0
        self._last_probe_t = 0.0
        self._freshness = info
        print(f"RPC health-gate : {len(self.healthy)} sain(s) au bloc ~{mx} ; primaire {self.primary}")
        for u, why in dropped:
            print(f"  [ecarte] {u} : {why}")
        if len(self.healthy) < 2:
            print("  !! QUORUM < 2 : impossible de recouper la fraicheur -> mode DEGRADE (freshness non garantie).")

    @property
    def w3(self) -> Web3:
        return self._w3[self.primary]

    @property
    def url(self) -> str:
        return self.primary

    def freshness(self) -> dict:
        return dict(self._freshness)

    def _ensure_fresh(self):
        now = time.time()
        if now - self._last_probe_t < PROBE_TTL and self.primary in self._w3:
            return
        heights = {u: _probe(u, "eth_blockNumber") for u in self.healthy}
        primary, info = choose_primary(heights, FRESH_TOL)
        self._last_probe_t = now
        self._freshness = info
        if primary is None:
            raise RuntimeError("Plus aucun RPC frais (tous en panne).")
        self.primary = primary

    def multicall(self, calls: list[tuple[str, bytes]]) -> list[tuple[bool, bytes]]:
        payload = [(t, True, d) for (t, d) in calls]
        last = None
        for _ in range(3):
            try:
                self._ensure_fresh()
                mc = self._w3[self.primary].eth.contract(address=MULTICALL3, abi=ABI_MC3)
                return mc.functions.aggregate3(payload).call()
            except Exception as e:
                last = e
                print(f"  multicall KO ({self.primary}) : {e!r} -> rotation")
                others = [u for u in self.healthy if u != self.primary]
                if others:
                    self.primary = others[0]
                self._last_probe_t = 0.0
                time.sleep(0.6)
        raise RuntimeError(f"multicall : echec apres rotation ({last!r})")

    def read_block(self, calls: list[tuple[str, bytes]]):
        """Lecture horodatee par le BLOC : renvoie (block, block_ts, results, freshness).

        results est aligne sur `calls`. freshness inclut reorg_suspect et le bloc lu.
        """
        full = [(MULTICALL3, SEL_BLOCKNUM), (MULTICALL3, SEL_BLOCKTS)] + calls
        res = self.multicall(full)
        block = uint_from(res[0][1]) if res[0][0] else None
        ts = uint_from(res[1][1]) if res[1][0] else None
        fresh = dict(self._freshness)
        fresh["block"] = block
        fresh["reorg_suspect"] = is_block_regression(self.last_block, block, REORG_TOL)
        if block:
            if fresh["reorg_suspect"]:
                print(f"  !! regression de bloc : {block} < {self.last_block} (reorg/RPC incoherent)")
            self.last_block = max(self.last_block, block)
        return block, ts, res[2:], fresh
