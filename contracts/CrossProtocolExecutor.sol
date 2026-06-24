// SPDX-License-Identifier: MIT
// CrossProtocolExecutor — SIMULATION ONLY (D1.6). JAMAIS DÉPLOYÉ, JAMAIS SIGNÉ.
//
// Exécuteur atomique cross-protocole pour MESURER l'enveloppe de gas d'un round-trip
// Uniswap v3 (SwapRouter02, indexé par `fee`) <-> Aerodrome SlipStream (Router, indexé par `tickSpacing`)
// sur le contrôle WETH/USDC. Il appelle les DEUX routers dans la MÊME exécution et REVERT si la sortie
// finale est insuffisante (modèle d'un searcher MEV — que nous SIMULONS, sans déployer ni détenir de
// capital ni signer de transaction).
//
// Usage exclusif : injecté comme `code` via state-override sur une adresse FACTICE, puis interrogé par
// eth_call (sortie exacte) et eth_estimateGas (gas L2 exact). Aucun déploiement. ABI des deux routers
// confirmées on-chain (read-only) avant écriture : Uni 0x04e45aaf, SlipStream 0xa026383e.
pragma solidity 0.8.26;

interface IERC20 {
    function approve(address spender, uint256 value) external returns (bool);
}

interface IUniV3Router {
    struct ExactInputSingleParams {
        address tokenIn;
        address tokenOut;
        uint24 fee;
        address recipient;
        uint256 amountIn;
        uint256 amountOutMinimum;
        uint160 sqrtPriceLimitX96;
    }
    function exactInputSingle(ExactInputSingleParams calldata params) external payable returns (uint256 amountOut);
}

interface ISlipRouter {
    struct ExactInputSingleParams {
        address tokenIn;
        address tokenOut;
        int24 tickSpacing;
        address recipient;
        uint256 deadline;
        uint256 amountIn;
        uint256 amountOutMinimum;
        uint160 sqrtPriceLimitX96;
    }
    function exactInputSingle(ExactInputSingleParams calldata params) external payable returns (uint256 amountOut);
}

contract CrossProtocolExecutor {
    // WETH -> USDC (Uniswap v3, `fee`) puis USDC -> WETH (SlipStream, `tickSpacing`).
    function uniThenSlip(
        address uni, address slip, address weth, address usdc,
        uint24 fee, int24 tickSpacing, uint256 amountIn, uint256 minOut
    ) external returns (uint256 out) {
        IERC20(weth).approve(uni, type(uint256).max);
        uint256 mid = IUniV3Router(uni).exactInputSingle(
            IUniV3Router.ExactInputSingleParams(weth, usdc, fee, address(this), amountIn, 0, 0));
        IERC20(usdc).approve(slip, type(uint256).max);
        out = ISlipRouter(slip).exactInputSingle(
            ISlipRouter.ExactInputSingleParams(usdc, weth, tickSpacing, address(this),
                                               type(uint256).max, mid, 0, 0));
        require(out >= minOut, "INSUFFICIENT_FINAL_OUTPUT");
    }

    // WETH -> USDC (SlipStream, `tickSpacing`) puis USDC -> WETH (Uniswap v3, `fee`).
    function slipThenUni(
        address slip, address uni, address weth, address usdc,
        int24 tickSpacing, uint24 fee, uint256 amountIn, uint256 minOut
    ) external returns (uint256 out) {
        IERC20(weth).approve(slip, type(uint256).max);
        uint256 mid = ISlipRouter(slip).exactInputSingle(
            ISlipRouter.ExactInputSingleParams(weth, usdc, tickSpacing, address(this),
                                               type(uint256).max, amountIn, 0, 0));
        IERC20(usdc).approve(uni, type(uint256).max);
        out = IUniV3Router(uni).exactInputSingle(
            IUniV3Router.ExactInputSingleParams(usdc, weth, fee, address(this), mid, 0, 0));
        require(out >= minOut, "INSUFFICIENT_FINAL_OUTPUT");
    }
}
