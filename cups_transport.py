#!/usr/bin/env python
"""Transport RPC partage D2B-2 : limiteur CUPS (token-bucket CU/seconde) + concurrence BORNEE.

Remplace les gros batchs (qui saturaient le rate-limit PAR SECONDE d'Alchemy -> reponses vides + 429
"compute units per second" -> contamination). Ici : chaque appel passe par un token-bucket regle en CU/s,
avec une concurrence bornee (1 = sequentiel pour la reference ; K = async borne pour la production). AUCUN
batch burst non borne. Les erreurs CUPS/vide/429 sont detectees, retentees avec backoff, et TOUJOURS
archivees ; apres epuisement -> infra=True (le cycle deviendra NON_CONCLUANT_INFRA, jamais un faux "absent").

Contrat d'un appel -> (result, error, infra) :
  - succes            : (result, None,  False)
  - erreur RPC reelle : (None,   error, False)   # ex: revert d'execution -> error dict (classify -> revert)
  - infra/CUPS epuise : (None,   error, True)    # transport/429/vide apres retries -> NON_CONCLUANT_INFRA
"""
from __future__ import annotations

import json
import threading
import time

import requests

# Couts CU Alchemy (approx., volontairement MAJORES -> throttle conservateur ; le benchmark calibre le budget).
CU_COST = {"eth_call": 26, "eth_estimateGas": 87, "eth_getCode": 24, "eth_getBlockByNumber": 16,
           "eth_blockNumber": 10, "eth_getBalance": 19}
DEFAULT_CU = 30
# Marqueurs d'un rate-limit PAR SECONDE (CUPS) ou throttle transitoire -> a RETENTER (pas une erreur RPC reelle).
CUPS_MARKERS = ["compute units per second", "compute unit per second", "exceeded its compute",
                "exceeded its throughput", "rate limit", "429", "too many requests", "capacity"]


def is_cups(error) -> bool:
    """True si l'erreur/texte ressemble a un rate-limit par seconde (a retenter), pas a une erreur RPC reelle."""
    if error is None:
        return False
    s = (error if isinstance(error, str) else json.dumps(error, ensure_ascii=False)).lower()
    return any(m in s for m in CUPS_MARKERS)


class CupsLimiter:
    """Token-bucket CU/seconde, thread-safe. acquire(cu) bloque jusqu'a disponibilite. Horloge injectable."""

    def __init__(self, cups: float, clock=time.monotonic):
        self.cups = float(cups)
        self.tokens = float(cups)            # capacite = 1 s de budget
        self.clock = clock
        self.t = clock()
        self.lock = threading.Lock()

    def acquire(self, cu: float) -> None:
        cu = min(float(cu), self.cups)       # un seul appel ne peut exceder la capacite du seau
        while True:
            with self.lock:
                now = self.clock()
                self.tokens = min(self.cups, self.tokens + (now - self.t) * self.cups)
                self.t = now
                if self.tokens >= cu:
                    self.tokens -= cu
                    return
                wait = (cu - self.tokens) / self.cups
            time.sleep(min(max(wait, 0.0), 0.25))


def rpc1(session, url, method, params, limiter, archive, max_retry: int = 6, sleeper=time.sleep):
    """Un appel JSON-RPC sous limiteur CUPS. Retries (backoff) sur CUPS/vide/exception. -> (result, error, infra)."""
    cu = CU_COST.get(method, DEFAULT_CU)
    last = None
    for attempt in range(max_retry):
        if limiter is not None:
            limiter.acquire(cu)
        try:
            r = session.post(url, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, timeout=30)
            status = getattr(r, "status_code", 200)
            if status == 429:
                last = {"method": method, "attempt": attempt, "http": 429, "cups": True}
                archive.append(last); sleeper(min(0.5 * (2 ** attempt), 8.0)); continue
            txt = r.text
            if txt is None or txt.strip() == "":
                last = {"method": method, "attempt": attempt, "error": "empty-body (gateway/CUPS presume)"}
                archive.append(last); sleeper(min(0.5 * (2 ** attempt), 8.0)); continue
            j = json.loads(txt)
            err = j.get("error") if isinstance(j, dict) else {"message": "reponse non-objet"}
            if err is not None and is_cups(err):
                last = {"method": method, "attempt": attempt, "cups_msg": str(err)[:120]}
                archive.append(last); sleeper(min(0.5 * (2 ** attempt), 8.0)); continue
            return (j.get("result") if isinstance(j, dict) else None), err, False
        except Exception as e:
            last = {"method": method, "attempt": attempt, "error": "%s: %s" % (type(e).__name__, str(e)[:80])}
            archive.append(last); sleeper(min(0.5 * (2 ** attempt), 8.0))
    return None, {"message": "infra: transport/CUPS epuise apres %d retries (%s) ; dernier=%s"
                  % (max_retry, method, last)}, True


def run_calls(url, calls, limiter, concurrency: int, archive, session_factory=requests.Session, max_retry: int = 6):
    """calls: list[(method, params)] -> list[(result, error, infra)] dans le MEME ordre.

    concurrency<=1 : sequentiel (reference). concurrency>1 : pool de threads borne (production). Le resultat
    de chaque appel ne depend que de (method, params, blockTag) -> identique quelle que soit la concurrence.
    max_retry : passe a rpc1 (prod=6 resilient ; probe=2 fail-fast pour detecter vite le plafond CUPS).
    """
    n = len(calls)
    results = [None] * n
    tl = threading.local()

    def session():
        s = getattr(tl, "s", None)
        if s is None:
            s = session_factory(); tl.s = s
        return s

    def work(i):
        results[i] = rpc1(session(), url, calls[i][0], calls[i][1], limiter, archive, max_retry=max_retry)

    if concurrency <= 1:
        for i in range(n):
            work(i)
    else:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=concurrency) as ex:
            list(ex.map(work, range(n)))
    return results
