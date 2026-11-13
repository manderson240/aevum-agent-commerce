// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

interface IERC20 {
    function transfer(address to, uint256 amount) external returns (bool);
    function transferFrom(address from, address to, uint256 amount) external returns (bool);
    function balanceOf(address account) external view returns (uint256);
}

/**
 * @title AevumAgentEscrow
 * @notice Verifiable autonomous agent commerce escrow for Aevum testnet (tUSD8).
 * Ensures agentic micro-settlement conditioned on zero-knowledge / QAG quality thresholds.
 */
contract AevumAgentEscrow {
    enum TaskStatus {
        NONE,
        ACTIVE,
        COMPLETED,
        REFUNDED
    }

    struct TaskEscrow {
        address client;
        address worker;
        uint256 amount;
        uint256 deadline;
        uint256 minQualityBps; // In basis points (e.g. 8500 = 85.00%)
        TaskStatus status;
        bytes32 outputHash;
        uint256 finalScore;
    }

    IERC20 public immutable paymentToken;
    address public immutable verifierOracle;
    address public owner;

    mapping(bytes32 => TaskEscrow) public tasks;
    bool private _locked;

    event TaskCreated(
        bytes32 indexed taskId,
        address indexed client,
        address indexed worker,
        uint256 amount,
        uint256 deadline,
        uint256 minQualityBps
    );

    event TaskCompleted(
        bytes32 indexed taskId,
        address indexed worker,
        uint256 amount,
        uint256 finalScore,
        bytes32 outputHash
    );

    event TaskRefunded(
        bytes32 indexed taskId,
        address indexed client,
        uint256 amount,
        string reason
    );

    modifier nonReentrant() {
        require(!_locked, "ReentrancyGuard: reentrant call");
        _locked = true;
        _;
        _locked = false;
    }

    modifier onlyOwner() {
        require(msg.sender == owner, "Caller is not owner");
        _;
    }

    constructor(address _paymentToken, address _verifierOracle) {
        require(_paymentToken != address(0), "Invalid token address");
        require(_verifierOracle != address(0), "Invalid oracle address");
        paymentToken = IERC20(_paymentToken);
        verifierOracle = _verifierOracle;
        owner = msg.sender;
    }

    /**
     * @notice Creates an escrow for an autonomous agent task.
     * @param taskId Unique identifier for the agent work order.
     * @param worker Address of the autonomous agent / provider.
     * @param amount Amount of tUSD8 locked.
     * @param deadline Unix timestamp after which client can refund if uncompleted.
     * @param minQualityBps Minimum verifiable QAG score (basis points, 0 - 10000).
     */
    function createTaskEscrow(
        bytes32 taskId,
        address worker,
        uint256 amount,
        uint256 deadline,
        uint256 minQualityBps
    ) external nonReentrant {
        require(tasks[taskId].status == TaskStatus.NONE, "Task ID already exists");
        require(worker != address(0), "Invalid worker address");
        require(amount > 0, "Amount must be greater than zero");
        require(deadline > block.timestamp, "Deadline must be in future");
        require(minQualityBps <= 10000, "Quality threshold > 100%");

        tasks[taskId] = TaskEscrow({
            client: msg.sender,
            worker: worker,
            amount: amount,
            deadline: deadline,
            minQualityBps: minQualityBps,
            status: TaskStatus.ACTIVE,
            outputHash: bytes32(0),
            finalScore: 0
        });

        bool success = paymentToken.transferFrom(msg.sender, address(this), amount);
        require(success, "Token transfer failed");

        emit TaskCreated(taskId, msg.sender, worker, amount, deadline, minQualityBps);
    }

    /**
     * @notice Releases escrow payment to the worker upon verifiable quality proof.
     * @param taskId Unique task identifier.
     * @param qagScore Evaluated quality score in basis points (e.g. 8950).
     * @param outputHash SHA256/keccak256 hash of agent execution deliverable.
     * @param v ECDSA recovery byte.
     * @param r ECDSA signature parameter.
     * @param s ECDSA signature parameter.
     */
    function completeTaskWithProof(
        bytes32 taskId,
        uint256 qagScore,
        bytes32 outputHash,
        uint8 v,
        bytes32 r,
        bytes32 s
    ) external nonReentrant {
        TaskEscrow storage task = tasks[taskId];
        require(task.status == TaskStatus.ACTIVE, "Task is not active");
        require(qagScore >= task.minQualityBps, "Quality score below requirement");

        // Verify oracle cryptographic signature over (taskId, qagScore, outputHash)
        bytes32 messageHash = keccak256(
            abi.encodePacked("\x19Ethereum Signed Message:\n32",
            keccak256(abi.encodePacked(taskId, qagScore, outputHash, address(this))))
        );

        address recovered = ecrecover(messageHash, v, r, s);
        require(recovered == verifierOracle, "Invalid verifier signature");

        task.status = TaskStatus.COMPLETED;
        task.outputHash = outputHash;
        task.finalScore = qagScore;

        bool success = paymentToken.transfer(task.worker, task.amount);
        require(success, "Payment transfer to worker failed");

        emit TaskCompleted(taskId, task.worker, task.amount, qagScore, outputHash);
    }

    /**
     * @notice Refunds locked escrow funds to the client if the deadline expired.
     * @param taskId Unique task identifier.
     */
    function refundExpiredEscrow(bytes32 taskId) external nonReentrant {
        TaskEscrow storage task = tasks[taskId];
        require(task.status == TaskStatus.ACTIVE, "Task is not active");
        require(block.timestamp >= task.deadline, "Deadline not yet reached");

        task.status = TaskStatus.REFUNDED;

        bool success = paymentToken.transfer(task.client, task.amount);
        require(success, "Refund transfer to client failed");

        emit TaskRefunded(taskId, task.client, task.amount, "Deadline expired without verification");
    }

    /**
     * @notice Allows client and worker to mutually cancel before completion.
     */
    function cancelTask(bytes32 taskId) external nonReentrant {
        TaskEscrow storage task = tasks[taskId];
        require(task.status == TaskStatus.ACTIVE, "Task is not active");
        require(msg.sender == task.client || msg.sender == task.worker, "Unauthorized cancellation");

        task.status = TaskStatus.REFUNDED;

        bool success = paymentToken.transfer(task.client, task.amount);
        require(success, "Refund transfer failed");

        emit TaskRefunded(taskId, task.client, task.amount, "Mutually cancelled");
    }
}
