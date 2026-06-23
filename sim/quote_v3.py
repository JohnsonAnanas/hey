"""Quote v3 EXACTE au bloc via le QuoterV2 canonique Uniswap — Phase v3.

Le QuoterV2 SIMULE le vrai swap (traverse les ticks de liquidite concentree) -> jamais un mid ni un
calcul via slot0 seul (gel #2 du contrat). Abstention explicite si revert / pool absent / illisible.
L'adresse est VERIFIEE on-chain au demarrage (code present + quote 1 WETH dans une bande saine) ; on
ne fait JAMAIS confiance a une adresse en dur sans preuve.
"""
from __future__ import annotations

from web3 import Web3

# Quoteur v3 par famille de venue (VERIFIE on-chain avant tout usage par .verify()).
QUOTERS = {
    "univ3": Web3.to_checksum_address("0x3d4e44Eb1374240CE5F1B871ab261CD16335B76a"),   # Uniswap QuoterV2 (Base)
}

QUOTER_ABI = [{
    "inputs": [{"components": [
        {"name": "tokenIn", "type": "address"}, {"name": "tokenOut", "type": "address"},
        {"name": "amountIn", "type": "uint256"}, {"name": "fee", "type": "uint24"},
        {"name": "sqrtPriceLimitX96", "type": "uint160"}], "name": "params", "type": "tuple"}],
    "name": "quoteExactInputSingle",
    "outputs": [{"name": "amountOut", "type": "uint256"}, {"name": "sqrtPriceX96After", "type": "uint160"},
                {"name": "initializedTicksCrossed", "type": "uint32"}, {"name": "gasEstimate", "type": "uint256"}],
    "stateMutability": "nonpayable", "type": "function"}]


class V3Quoter:
    """Quote exacte au bloc via QuoterV2 (eth_call avec block_identifier). Abstention -> None."""

    def __init__(self, w3, family: str = "univ3"):
        self.w3 = w3
        self.family = family
        self.addr = QUOTERS[family]
        self.q = w3.eth.contract(address=self.addr, abi=QUOTER_ABI)

    def verify(self, weth, usdc, block="latest") -> tuple[bool, str | None]:
        """Garde anti-mauvaise-adresse : code present + quote 1 WETH->USDC dans une bande saine."""
        if len(self.w3.eth.get_code(self.addr)) <= 2:
            return False, f"aucun code a {self.addr} (mauvaise adresse quoteur)"
        try:
            out, _, _, _ = self.q.functions.quoteExactInputSingle(
                (Web3.to_checksum_address(weth), Web3.to_checksum_address(usdc), 10 ** 18, 500, 0)
            ).call(block_identifier=block)
        except Exception as e:
            return False, f"quote de controle KO: {type(e).__name__}"
        px = out / 1e6
        if not (100.0 < px < 100_000.0):
            return False, f"prix WETH absurde ({px:.2f}) -> quoteur/decodage suspect"
        return True, None

    def quote(self, token_in, token_out, amount_in: int, fee: int, block):
        """(amount_out_wei, gas_estimate, ticks_crossed) ou None (revert / pool absent / illisible)."""
        try:
            out, _, ticks, gas = self.q.functions.quoteExactInputSingle(
                (Web3.to_checksum_address(token_in), Web3.to_checksum_address(token_out),
                 int(amount_in), int(fee), 0)
            ).call(block_identifier=block)
            return (int(out), int(gas), int(ticks)) if out > 0 else None
        except Exception:
            return None
