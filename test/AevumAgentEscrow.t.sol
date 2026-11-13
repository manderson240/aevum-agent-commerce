// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "forge-std/Test.sol";
import "../src/MockUSD8.sol";
import "../src/AevumAgentEscrow.sol";

contract AevumAgentEscrowTest is Test {
    MockUSD8 public token;
    AevumAgentEscrow public escrow;

    uint256 internal oraclePrivateKey = 0xA11CE;
    address internal oracle;
    address internal client = address(0x100);
    address internal worker = address(0x200);

    function setUp() public {
        oracle = vm.addr(oraclePrivateKey);
        token = new MockUSD8();
        escrow = new AevumAgentEscrow(address(token), oracle);

        // Fund client
        token.mint(client, 10_000 * 10 ** 6);

        vm.startPrank(client);
        token.approve(address(escrow), type(uint256).max);
        vm.stopPrank();
    }

    function _signScore(
        bytes32 taskId,
        uint256 score,
        bytes32 outputHash
    ) internal view returns (uint8 v, bytes32 r, bytes32 s) {
        bytes32 rawHash = keccak256(abi.encodePacked(taskId, score, outputHash, address(escrow)));
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
        uint256 score = 9200; // 92.00%

        vm.prank(client);
        escrow.createTaskEscrow(taskId, worker, amount, deadline, 8500);

        (uint8 v, bytes32 r, bytes32 s) = _signScore(taskId, score, outputHash);

        uint256 workerBalBefore = token.balanceOf(worker);
        escrow.completeTaskWithProof(taskId, score, outputHash, v, r, s);
        uint256 workerBalAfter = token.balanceOf(worker);

        assertEq(workerBalAfter - workerBalBefore, amount);

        (, , , , , AevumAgentEscrow.TaskStatus status, bytes32 resOutputHash, uint256 finalScore) = escrow.tasks(taskId);
        assertEq(uint8(status), uint8(AevumAgentEscrow.TaskStatus.COMPLETED));
        assertEq(resOutputHash, outputHash);
        assertEq(finalScore, score);
    }

    function test_RevertOnSubparQuality() public {
        bytes32 taskId = keccak256("TASK-003");
        uint256 amount = 50 * 10 ** 6;
        uint256 deadline = block.timestamp + 3600;
        bytes32 outputHash = keccak256("LOW_QUALITY_OUTPUT");
        uint256 score = 7400; // 74% < 85% requirement

        vm.prank(client);
        escrow.createTaskEscrow(taskId, worker, amount, deadline, 8500);

        (uint8 v, bytes32 r, bytes32 s) = _signScore(taskId, score, outputHash);

        vm.expectRevert("Quality score below requirement");
        escrow.completeTaskWithProof(taskId, score, outputHash, v, r, s);
    }

    function test_RevertOnInvalidSignature() public {
        bytes32 taskId = keccak256("TASK-004");
        uint256 amount = 50 * 10 ** 6;
        uint256 deadline = block.timestamp + 3600;
        bytes32 outputHash = keccak256("OUTPUT");

        vm.prank(client);
        escrow.createTaskEscrow(taskId, worker, amount, deadline, 8500);

        // Sign with wrong private key
        bytes32 ethSignedHash = keccak256(
            abi.encodePacked("\x19Ethereum Signed Message:\n32", keccak256(abi.encodePacked(taskId, uint256(9000), outputHash, address(escrow))))
        );
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(0xBAD, ethSignedHash);

        vm.expectRevert("Invalid verifier signature");
        escrow.completeTaskWithProof(taskId, 9000, outputHash, v, r, s);
    }

    function test_RefundExpiredEscrow() public {
        bytes32 taskId = keccak256("TASK-005");
        uint256 amount = 150 * 10 ** 6;
        uint256 deadline = block.timestamp + 1000;

        vm.prank(client);
        escrow.createTaskEscrow(taskId, worker, amount, deadline, 8500);

        // Try refund before deadline
        vm.expectRevert("Deadline not yet reached");
        escrow.refundExpiredEscrow(taskId);

        // Warp past deadline
        vm.warp(deadline + 1);

        uint256 clientBalBefore = token.balanceOf(client);
        escrow.refundExpiredEscrow(taskId);
        uint256 clientBalAfter = token.balanceOf(client);

        assertEq(clientBalAfter - clientBalBefore, amount);

        (, , , , , AevumAgentEscrow.TaskStatus status, , ) = escrow.tasks(taskId);
        assertEq(uint8(status), uint8(AevumAgentEscrow.TaskStatus.REFUNDED));
    }

    function testFuzz_EscrowSettlement(uint256 amount, uint256 score) public {
        amount = bound(amount, 1 * 10 ** 6, 1_000 * 10 ** 6);
        score = bound(score, 0, 10000);

        token.mint(client, amount);

        bytes32 taskId = keccak256(abi.encodePacked(amount, score, block.timestamp));
        uint256 deadline = block.timestamp + 1000;
        bytes32 outputHash = keccak256(abi.encodePacked("FUZZ_OUTPUT", score));

        vm.prank(client);
        escrow.createTaskEscrow(taskId, worker, amount, deadline, 8500);

        (uint8 v, bytes32 r, bytes32 s) = _signScore(taskId, score, outputHash);

        if (score >= 8500) {
            uint256 workerBefore = token.balanceOf(worker);
            escrow.completeTaskWithProof(taskId, score, outputHash, v, r, s);
            assertEq(token.balanceOf(worker) - workerBefore, amount);
        } else {
            vm.expectRevert("Quality score below requirement");
            escrow.completeTaskWithProof(taskId, score, outputHash, v, r, s);
        }
    }
}
