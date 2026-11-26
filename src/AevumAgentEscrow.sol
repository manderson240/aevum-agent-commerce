// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

interface IERC20 {
    function transfer(address to, uint256 amount) external returns (bool);
    function transferFrom(address from, address to, uint256 amount) external returns (bool);
    function balanceOf(address account) external view returns (uint256);
}

interface IERC8004PayeeRegistry {
    function verifyPayee(address payee)
        external
        view
        returns (
            bool verified,
            bytes32 agentId,
            string memory endpoint,
            string memory metadataUri,
            uint256 reputationEmaBps,
            uint256 totalEvaluations
        );
}

/**
 * @title AevumAgentEscrow
 * @notice Verifiable autonomous agent commerce escrow with ERC-8004 Confirmation of Payee for Aevum testnet (tUSD8).
 * Ensures agentic micro-settlement conditioned on payee identity verification, delivery state lock, and QAG proofs.
 */
contract AevumAgentEscrow {
    enum TaskStatus {
        NONE,
        ACTIVE,
        DELIVERED,
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
    address public verifierOracle;
    address public owner;
    address public payeeRegistry;
    bool public requireVerifiedPayee;

    mapping(bytes32 => TaskEscrow) public tasks;
    mapping(bytes32 => uint256) public taskNonces;
    bool private _locked;

    event TaskCreated(
        bytes32 indexed taskId,
        address indexed client,
        address indexed worker,
        uint256 amount,
        uint256 deadline,
        uint256 minQualityBps
    );

    event TaskDelivered(
        bytes32 indexed taskId,
        address indexed worker,
        bytes32 outputHash
    );

    event TaskCompleted(
        bytes32 indexed taskId,
        address indexed worker,
        uint256 amount,
        uint256 finalScore,
        bytes32 outputHash,
        uint256 nonce
    );

    event TaskRefunded(
        bytes32 indexed taskId,
        address indexed client,
        uint256 amount,
        string reason
    );

    event PayeeRegistryUpdated(address indexed registry, bool required);
    event VerifierOracleUpdated(address indexed oldOracle, address indexed newOracle);

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
     * @notice Configures the ERC-8004 payee verification registry (Track 4: Confirmation of Payee).
     */
    function setPayeeRegistry(address _registry, bool _required) external onlyOwner {
        payeeRegistry = _registry;
        requireVerifiedPayee = _required;
        emit PayeeRegistryUpdated(_registry, _required);
    }

    /**
     * @notice Rotates the verifier oracle address.
     */
    function setVerifierOracle(address _verifierOracle) external onlyOwner {
        require(_verifierOracle != address(0), "Invalid oracle address");
        emit VerifierOracleUpdated(verifierOracle, _verifierOracle);
        verifierOracle = _verifierOracle;
    }

    /**
     * @notice Pre-flight Confirmation of Payee lookup against the configured ERC-8004 registry.
     */
    function confirmPayee(address payee)
        external
        view
        returns (
            bool verified,
            bytes32 agentId,
            string memory endpoint,
            uint256 reputationEmaBps
        )
    {
        if (payeeRegistry == address(0)) {
            return (false, bytes32(0), "", 0);
        }
        (bool ok, bytes32 aid, string memory ep,, uint256 ema,) =
            IERC8004PayeeRegistry(payeeRegistry).verifyPayee(payee);
        return (ok, aid, ep, ema);
    }

    /**
     * @notice Creates an escrow for an autonomous agent task.
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

        if (requireVerifiedPayee && payeeRegistry != address(0)) {
            (bool verified,,,,,) = IERC8004PayeeRegistry(payeeRegistry).verifyPayee(worker);
            require(verified, "Payee not verified in ERC-8004 registry");
        }

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
     * @notice Worker records deliverable commitment before oracle evaluation, locking out unilateral cancellation.
     */
    function submitDelivery(bytes32 taskId, bytes32 outputHash) external nonReentrant {
        TaskEscrow storage task = tasks[taskId];
        require(task.status == TaskStatus.ACTIVE, "Task is not active");
        require(msg.sender == task.worker, "Only worker can submit delivery");
        require(outputHash != bytes32(0), "Invalid output hash");

        task.status = TaskStatus.DELIVERED;
        task.outputHash = outputHash;

        emit TaskDelivered(taskId, msg.sender, outputHash);
    }

    /**
     * @notice Releases escrow payment to the worker upon verifiable quality proof.
     * @dev Digest includes taskId, monotonic nonce, qagScore, outputHash, block.chainid, and address(this).
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
        require(
            task.status == TaskStatus.ACTIVE || task.status == TaskStatus.DELIVERED,
            "Task is not active or delivered"
        );
        if (task.status == TaskStatus.DELIVERED) {
            require(task.outputHash == outputHash, "Deliverable hash mismatch");
        }
        require(qagScore >= task.minQualityBps, "Quality score below requirement");

        uint256 nonce = taskNonces[taskId]++;

        bytes32 rawHash = keccak256(
            abi.encodePacked(taskId, nonce, qagScore, outputHash, block.chainid, address(this))
        );
        bytes32 messageHash = keccak256(
            abi.encodePacked("\x19Ethereum Signed Message:\n32", rawHash)
        );

        address recovered = ecrecover(messageHash, v, r, s);
        require(recovered != address(0) && recovered == verifierOracle, "Invalid verifier signature");

        task.status = TaskStatus.COMPLETED;
        task.outputHash = outputHash;
        task.finalScore = qagScore;

        bool success = paymentToken.transfer(task.worker, task.amount);
        require(success, "Payment transfer to worker failed");

        emit TaskCompleted(taskId, task.worker, task.amount, qagScore, outputHash, nonce);
    }

    /**
     * @notice Refunds locked escrow funds to the client if the deadline expired without settlement.
     */
    function refundExpiredEscrow(bytes32 taskId) external nonReentrant {
        TaskEscrow storage task = tasks[taskId];
        require(
            task.status == TaskStatus.ACTIVE || task.status == TaskStatus.DELIVERED,
            "Task is not refundable"
        );
        require(block.timestamp >= task.deadline, "Deadline not yet reached");

        task.status = TaskStatus.REFUNDED;

        bool success = paymentToken.transfer(task.client, task.amount);
        require(success, "Refund transfer to client failed");

        emit TaskRefunded(taskId, task.client, task.amount, "Deadline expired without verification");
    }

    /**
     * @notice Allows cancellation only while task is ACTIVE before deliverable submission.
     */
    function cancelTask(bytes32 taskId) external nonReentrant {
        TaskEscrow storage task = tasks[taskId];
        require(task.status == TaskStatus.ACTIVE, "Task cannot be cancelled after delivery or settlement");
        require(msg.sender == task.client || msg.sender == task.worker, "Unauthorized cancellation");

        task.status = TaskStatus.REFUNDED;

        bool success = paymentToken.transfer(task.client, task.amount);
        require(success, "Refund transfer failed");

        emit TaskRefunded(taskId, task.client, task.amount, "Cancelled before delivery");
    }
}
