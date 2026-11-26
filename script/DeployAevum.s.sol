// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "forge-std/Script.sol";
import "../src/MockUSD8.sol";
import "../src/MockERC8004Registry.sol";
import "../src/AevumAgentEscrow.sol";

contract DeployAevum is Script {
    address constant AEVUM_TUSD8 = 0x456569838f1d43009A91ebA4263147Afd7233483;
    uint256 constant ANVIL_CHAIN = 31337;
    uint256 constant FORK_CHAIN = 440050;

    function run() external {
        uint256 deployerPrivateKey = vm.envOr("PRIVATE_KEY", uint256(0));
        if (deployerPrivateKey != 0) {
            vm.startBroadcast(deployerPrivateKey);
        } else {
            vm.startBroadcast();
        }
        (, address deployer,) = vm.readCallers();

        address tokenAddr = vm.envOr("TUSD8_ADDRESS", address(0));
        address registryAddr = vm.envOr("ERC8004_REGISTRY_ADDRESS", address(0));
        address verifierOracle = vm.envOr("VERIFIER_ORACLE", deployer);
        bool requirePayee = vm.envOr("REQUIRE_VERIFIED_PAYEE", true);

        if (tokenAddr == address(0)) {
            if (AEVUM_TUSD8.code.length > 0) {
                tokenAddr = AEVUM_TUSD8;
                console.log("Detected live Aevum tUSD8 at:", tokenAddr);
            } else {
                require(
                    block.chainid == ANVIL_CHAIN || block.chainid == FORK_CHAIN,
                    "tUSD8 not detected on this chain; set TUSD8_ADDRESS or target Anvil"
                );
                MockUSD8 mockToken = new MockUSD8();
                tokenAddr = address(mockToken);
                console.log("Deployed MockUSD8 at:", tokenAddr);
            }
        } else {
            console.log("Using configured tUSD8 token at:", tokenAddr);
        }

        if (registryAddr == address(0)) {
            MockERC8004Registry mockRegistry = new MockERC8004Registry();
            registryAddr = address(mockRegistry);
            console.log("Deployed MockERC8004Registry at:", registryAddr);
        } else {
            console.log("Using existing ERC-8004 registry at:", registryAddr);
        }

        AevumAgentEscrow escrow = new AevumAgentEscrow(tokenAddr, verifierOracle);
        escrow.setPayeeRegistry(registryAddr, requirePayee);

        vm.stopBroadcast();

        console.log("Deployer:", deployer);
        console.log("Deployed AevumAgentEscrow at:", address(escrow));
        console.log("Verifier oracle:", verifierOracle);
        console.log("Chain ID:", block.chainid);
        console.log("Explorer: https://explorer-test.qday.info/address/", address(escrow));
    }
}
