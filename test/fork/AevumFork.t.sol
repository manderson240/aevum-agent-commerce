// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "forge-std/Test.sol";
import "../../src/MockERC8004Registry.sol";
import "../../src/AevumAgentEscrow.sol";

interface ITUSD8 {
    function name() external view returns (string memory);
    function symbol() external view returns (string memory);
    function decimals() external view returns (uint8);
    function balanceOf(address account) external view returns (uint256);
    function approve(address spender, uint256 amount) external returns (bool);
    function DOMAIN_SEPARATOR() external view returns (bytes32);
}

/**
 * @title AevumForkTest
 * @notice Verifies AevumAgentEscrow Confirmation of Payee + settlement against live QDay Aevum tUSD8.
 * Run with: forge test --match-path 'test/fork/*' --fork-url aevum -vv
 */
contract AevumForkTest is Test {
    ITUSD8 constant TUSD8 = ITUSD8(0x456569838f1d43009A91ebA4263147Afd7233483);

    function setUp() public {
        if (block.chainid != 44005) {
            vm.skip(true);
        }
    }

    function test_RealTusd8MetadataAndDomain() public view {
        assertEq(block.chainid, 44005, "run with --fork-url aevum");
        assertEq(TUSD8.symbol(), "tUSD8");
        assertEq(TUSD8.decimals(), 6);

        bytes32 expectedDomain = keccak256(
            abi.encode(
                keccak256("EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)"),
                keccak256("tUSD8"),
                keccak256("2"),
                uint256(44005),
                address(TUSD8)
            )
        );
        assertEq(TUSD8.DOMAIN_SEPARATOR(), expectedDomain);
    }

    function _signSettlement(
        AevumAgentEscrow escrow,
        uint256 oracleKey,
        bytes32 taskId,
        uint256 score,
        bytes32 outputHash
    ) internal view returns (uint8 v, bytes32 r, bytes32 s) {
        bytes32 rawHash = keccak256(
            abi.encodePacked(taskId, uint256(0), score, outputHash, block.chainid, address(escrow))
        );
        bytes32 ethSigned = keccak256(abi.encodePacked("\x19Ethereum Signed Message:\n32", rawHash));
        return vm.sign(oracleKey, ethSigned);
    }

    function test_ForkConfirmPayeeAndRealTusd8Settlement() public {
        assertEq(block.chainid, 44005, "run with --fork-url aevum");

        (address worker,) = makeAddrAndKey("aevum-worker");
        address client = makeAddr("aevum-client");
        (address oracle, uint256 oracleKey) = makeAddrAndKey("aevum-oracle");

        MockERC8004Registry registry = new MockERC8004Registry();
        AevumAgentEscrow escrow = new AevumAgentEscrow(address(TUSD8), oracle);
        escrow.setPayeeRegistry(address(registry), true);

        {
            bytes32 workerAgentId = keccak256("AEVUM_FORK_WORKER_01");
            vm.prank(worker);
            registry.registerAgent(workerAgentId, "https://payee.example/v1", "ipfs://QmAevumFork", 9200);

            (bool verified, bytes32 aid, string memory ep, uint256 ema) = escrow.confirmPayee(worker);
            assertTrue(verified);
            assertEq(aid, workerAgentId);
            assertEq(ep, "https://payee.example/v1");
            assertEq(ema, 9200);
        }

        // Discord /faucet gives 5 tUSD8; simulate client holding 5 tUSD8 on the forked state
        deal(address(TUSD8), client, 5_000_000);
        vm.prank(client);
        TUSD8.approve(address(escrow), 5_000_000);

        // Confirmation of Payee guard must reject an unverified payee
        vm.prank(client);
        vm.expectRevert("Payee not verified in ERC-8004 registry");
        escrow.createTaskEscrow(
            keccak256("FORK-BLOCKED-UNVERIFIED"),
            makeAddr("aevum-unverified"),
            1_000_000,
            block.timestamp + 3600,
            8500
        );

        // Verified payee locks 2.50 tUSD8, submits deliverable hash, and settles via oracle EIP-191 proof
        bytes32 taskId = keccak256("FORK-TASK-AEVUM-01");
        vm.prank(client);
        escrow.createTaskEscrow(taskId, worker, 2_500_000, block.timestamp + 3600, 8500);

        bytes32 outputHash = keccak256("AEVUM_FORK_VERIFIED_DELIVERABLE");
        vm.prank(worker);
        escrow.submitDelivery(taskId, outputHash);

        (uint8 v, bytes32 r, bytes32 s) = _signSettlement(escrow, oracleKey, taskId, 9200, outputHash);
        escrow.completeTaskWithProof(taskId, 9200, outputHash, v, r, s);

        assertEq(TUSD8.balanceOf(worker), 2_500_000);
        assertEq(TUSD8.balanceOf(client), 2_500_000);
    }
}
