// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "forge-std/Test.sol";
import "../src/MockUSD8.sol";
import "../src/MockERC8004Registry.sol";
import "../src/AevumAgentEscrow.sol";

contract AevumAgentEscrowTest is Test {
    MockUSD8 public token;
    MockERC8004Registry public registry;
    AevumAgentEscrow public escrow;

    uint256 internal oraclePrivateKey = 0xA11CE;
    address internal oracle;
    address internal client = address(0x100);
    address internal worker = address(0x200);
    address internal unverifiedWorker = address(0x300);

    bytes32 internal workerAgentId = keccak256("WORKER_AGENT_01");

    function setUp() public {
        oracle = vm.addr(oraclePrivateKey);
        token = new MockUSD8();
        registry = new MockERC8004Registry();
        escrow = new AevumAgentEscrow(address(token), oracle);
        escrow.setPayeeRegistry(address(registry), false);

        vm.prank(worker);
        registry.registerAgent(
            workerAgentId,
            "https://payee.example/v1",
            "ipfs://QmWorkerMetadata",
            9150
        );

        token.mint(client, 10_000 * 10 ** 6);
        vm.prank(client);
        token.approve(address(escrow), type(uint256).max);
    }

    function _signScore(
        bytes32 taskId,
        uint256 nonce,
        uint256 score,
        bytes32 outputHash,
        uint256 chainId
    ) internal view returns (uint8 v, bytes32 r, bytes32 s) {
        bytes32 rawHash = keccak256(
            abi.encodePacked(taskId, nonce, score, outputHash, chainId, address(escrow))
        );
        bytes32 ethSignedHash = keccak256(
            abi.encodePacked("\x19Ethereum Signed Message:\n32", rawHash)
        );
        (v, r, s) = vm.sign(oraclePrivateKey, ethSignedHash);
    }

    function test_CreateTaskEscrow() public {
        bytes32 taskId = keccak256("TASK-001");
        uint256 amount = 100 * 10 ** 6;
        uint256 deadline = block.timestamp + 3600;

        vm.prank(client);
        escrow.createTaskEscrow(taskId, worker, amount, deadline, 8500);

        (
            address tClient,
            address tWorker,
            uint256 tAmount,
            uint256 tDeadline,
            uint256 minQualityBps,
            AevumAgentEscrow.TaskStatus status,
            ,
        ) = escrow.tasks(taskId);

        assertEq(tClient, client);
        assertEq(tWorker, worker);
        assertEq(tAmount, amount);
        assertEq(tDeadline, deadline);
        assertEq(minQualityBps, 8500);
        assertEq(uint8(status), uint8(AevumAgentEscrow.TaskStatus.ACTIVE));
        assertEq(token.balanceOf(address(escrow)), amount);
    }

    function test_CompleteTaskWithValidProof() public {
        bytes32 taskId = keccak256("TASK-002");
        uint256 amount = 250 * 10 ** 6;
        uint256 deadline = block.timestamp + 3600;
        bytes32 outputHash = keccak256("AGENT_RESULT_JSON");
        uint256 score = 9200;

        vm.prank(client);
        escrow.createTaskEscrow(taskId, worker, amount, deadline, 8500);

        (uint8 v, bytes32 r, bytes32 s) = _signScore(taskId, 0, score, outputHash, block.chainid);

        uint256 workerBalBefore = token.balanceOf(worker);
        escrow.completeTaskWithProof(taskId, score, outputHash, v, r, s);
        uint256 workerBalAfter = token.balanceOf(worker);

        assertEq(workerBalAfter - workerBalBefore, amount);

        (, , , , , AevumAgentEscrow.TaskStatus status, bytes32 resOutputHash, uint256 finalScore) = escrow.tasks(taskId);
        assertEq(uint8(status), uint8(AevumAgentEscrow.TaskStatus.COMPLETED));
        assertEq(resOutputHash, outputHash);
        assertEq(finalScore, score);
        assertEq(escrow.taskNonces(taskId), 1);
    }

    function test_SubmitDeliveryBlocksCancelAndSettles() public {
        bytes32 taskId = keccak256("TASK-DELIVERY-LOCK");
        uint256 amount = 150 * 10 ** 6;
        uint256 deadline = block.timestamp + 3600;
        bytes32 outputHash = keccak256("DELIVERED_BUNDLE");

        vm.prank(client);
        escrow.createTaskEscrow(taskId, worker, amount, deadline, 8500);

        vm.prank(worker);
        escrow.submitDelivery(taskId, outputHash);

        // Client can no longer unilaterally cancel once worker delivered
        vm.prank(client);
        vm.expectRevert("Task cannot be cancelled after delivery or settlement");
        escrow.cancelTask(taskId);

        // Mismatched hash must revert
        (uint8 vBad, bytes32 rBad, bytes32 sBad) = _signScore(taskId, 0, 9100, keccak256("OTHER"), block.chainid);
        vm.expectRevert("Deliverable hash mismatch");
        escrow.completeTaskWithProof(taskId, 9100, keccak256("OTHER"), vBad, rBad, sBad);

        // Matching deliverable settles cleanly
        (uint8 vOk, bytes32 rOk, bytes32 sOk) = _signScore(taskId, 0, 9100, outputHash, block.chainid);
        escrow.completeTaskWithProof(taskId, 9100, outputHash, vOk, rOk, sOk);
        assertEq(token.balanceOf(worker), amount);
    }

    function test_ConfirmPayeeAndRequireVerifiedPayee() public {
        (bool ok, bytes32 aid, string memory ep, uint256 ema) = escrow.confirmPayee(worker);
        assertTrue(ok);
        assertEq(aid, workerAgentId);
        assertEq(ep, "https://payee.example/v1");
        assertEq(ema, 9150);

        (bool badOk,,,) = escrow.confirmPayee(unverifiedWorker);
        assertFalse(badOk);

        escrow.setPayeeRegistry(address(registry), true);

        bytes32 blockedTask = keccak256("TASK-UNVERIFIED");
        vm.prank(client);
        vm.expectRevert("Payee not verified in ERC-8004 registry");
        escrow.createTaskEscrow(blockedTask, unverifiedWorker, 100 * 10 ** 6, block.timestamp + 3600, 8000);

        bytes32 allowedTask = keccak256("TASK-VERIFIED");
        vm.prank(client);
        escrow.createTaskEscrow(allowedTask, worker, 100 * 10 ** 6, block.timestamp + 3600, 8000);
    }

    function test_RevertOnSubparQuality() public {
        bytes32 taskId = keccak256("TASK-003");
        uint256 amount = 50 * 10 ** 6;
        uint256 deadline = block.timestamp + 3600;
        bytes32 outputHash = keccak256("LOW_QUALITY_OUTPUT");
        uint256 score = 7400;

        vm.prank(client);
        escrow.createTaskEscrow(taskId, worker, amount, deadline, 8500);

        (uint8 v, bytes32 r, bytes32 s) = _signScore(taskId, 0, score, outputHash, block.chainid);

        vm.expectRevert("Quality score below requirement");
        escrow.completeTaskWithProof(taskId, score, outputHash, v, r, s);
    }

    function test_RevertOnInvalidSignatureAndWrongChainId() public {
        bytes32 taskId = keccak256("TASK-004");
        uint256 amount = 50 * 10 ** 6;
        uint256 deadline = block.timestamp + 3600;
        bytes32 outputHash = keccak256("OUTPUT");

        vm.prank(client);
        escrow.createTaskEscrow(taskId, worker, amount, deadline, 8500);

        // Wrong chain ID signature fails domain separation
        (uint8 vChain, bytes32 rChain, bytes32 sChain) = _signScore(taskId, 0, 9000, outputHash, 999999);
        vm.expectRevert("Invalid verifier signature");
        escrow.completeTaskWithProof(taskId, 9000, outputHash, vChain, rChain, sChain);

        // Sign with wrong key
        bytes32 ethSignedHash = keccak256(
            abi.encodePacked(
                "\x19Ethereum Signed Message:\n32",
                keccak256(abi.encodePacked(taskId, uint256(0), uint256(9000), outputHash, block.chainid, address(escrow)))
            )
        );
        (uint8 vBad, bytes32 rBad, bytes32 sBad) = vm.sign(0xBAD, ethSignedHash);

        vm.expectRevert("Invalid verifier signature");
        escrow.completeTaskWithProof(taskId, 9000, outputHash, vBad, rBad, sBad);
    }

    function test_RefundExpiredEscrow() public {
        bytes32 taskId = keccak256("TASK-005");
        uint256 amount = 100 * 10 ** 6;
        uint256 deadline = block.timestamp + 100;

        vm.prank(client);
        escrow.createTaskEscrow(taskId, worker, amount, deadline, 8000);

        vm.expectRevert("Deadline not yet reached");
        escrow.refundExpiredEscrow(taskId);

        vm.warp(deadline + 1);
        uint256 clientBalBefore = token.balanceOf(client);
        escrow.refundExpiredEscrow(taskId);
        uint256 clientBalAfter = token.balanceOf(client);

        assertEq(clientBalAfter - clientBalBefore, amount);
    }

    function testFuzz_CreateAndCompleteEscrow(uint256 amount, uint256 quality) public {
        amount = bound(amount, 1, 5_000 * 10 ** 6);
        quality = bound(quality, 8500, 10000);

        bytes32 taskId = keccak256(abi.encodePacked("FUZZ", amount, quality));
        uint256 deadline = block.timestamp + 1000;
        bytes32 outputHash = keccak256("FUZZ_OUTPUT");

        vm.prank(client);
        escrow.createTaskEscrow(taskId, worker, amount, deadline, 8500);

        (uint8 v, bytes32 r, bytes32 s) = _signScore(taskId, 0, quality, outputHash, block.chainid);
        escrow.completeTaskWithProof(taskId, quality, outputHash, v, r, s);

        assertEq(token.balanceOf(worker), amount);
    }
}
