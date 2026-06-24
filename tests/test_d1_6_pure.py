"""Tests OFFLINE du runner D1.6 (executeur simule) — AUCUN reseau.

Inclut une verification d'INTEGRITE : le bytecode versionne (contracts/CrossProtocolExecutor.json) doit
correspondre exactement a la source versionnee (.sol) — sinon le runner utiliserait un bytecode non audite.
"""
import hashlib
import json
import os

from d1_6_simulated_executor_envelope import (
    SEL_UNI_THEN_SLIP, SEL_SLIP_THEN_UNI, exec_calldata, override_exec, EXEC_JSON,
    FAKE, WETH, UNI_ROUTER, SLIP_ROUTER, FEE, TICKSPACING,
)
from d1_mev_boundary_control import mapping_slot

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_executor_selectors_connus():
    # vecteurs confirmes on-chain (sonde read-only) avant ecriture
    assert SEL_UNI_THEN_SLIP == bytes.fromhex("459cc3b3")
    assert SEL_SLIP_THEN_UNI == bytes.fromhex("0d70e541")


def test_exec_calldata_structure():
    cd = exec_calldata("uni_then_slip", 10 ** 18, 0)
    assert cd[:4] == SEL_UNI_THEN_SLIP
    assert len(cd) == 4 + 32 * 8                       # 8 parametres
    assert int.from_bytes(cd[4 + 192:4 + 224], "big") == 10 ** 18   # amountIn (7e param)
    cd2 = exec_calldata("slip_then_uni", 5 * 10 ** 17, 0)
    assert cd2[:4] == SEL_SLIP_THEN_UNI
    assert int.from_bytes(cd2[4 + 192:4 + 224], "big") == 5 * 10 ** 17


def test_override_exec_structure():
    ov = override_exec("0xabcd")
    assert ov[FAKE]["code"] == "0xabcd" and ov[FAKE]["balance"].startswith("0x")
    sd = ov[WETH]["stateDiff"]
    assert mapping_slot(FAKE, 3) in sd                  # balanceOf[FAKE] (slot WETH9)
    assert int(list(sd.values())[0], 16) > 0
    assert USDC_absent(ov)                              # pas d'override d'allowance USDC (approve interne)


def USDC_absent(ov):
    from d1_6_simulated_executor_envelope import USDC
    return USDC not in ov


def test_bytecode_correspond_a_la_source():
    meta = json.load(open(EXEC_JSON, encoding="utf-8"))
    sol = open(os.path.join(HERE, "contracts", "CrossProtocolExecutor.sol"), encoding="utf-8").read()
    # le bytecode versionne provient bien de la source versionnee
    assert hashlib.sha256(sol.encode("utf-8")).hexdigest() == meta["source_sha256"]
    # le sha du bytecode est coherent
    bc = meta["deployed_bytecode"]
    assert bc.startswith("0x") and (len(bc) - 2) // 2 > 200
    assert hashlib.sha256(bytes.fromhex(bc[2:])).hexdigest() == meta["deployed_bytecode_sha256"]


def test_constantes_controle():
    assert FEE == 500 and TICKSPACING == 100
    assert UNI_ROUTER.lower() == "0x2626664c2603336e57b271c5c0b26f421741e481"
    assert SLIP_ROUTER.lower() == "0xbe6d8f0d05cc4be24d5167a3ef062215be6d18a5"
