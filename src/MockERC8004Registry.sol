// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * @title MockERC8004Registry
 * @notice Minimal ERC-8004 compatible Confirmation of Payee registry for standalone deployment and testing.
 */
contract MockERC8004Registry {
    struct AgentRecord {
        bytes32 agentId;
        address owner;
        string endpoint;
        string metadataUri;
        uint256 reputationEmaBps;
        uint256 totalEvaluations;
        bool isActive;
    }

    mapping(bytes32 => AgentRecord) public agents;
    mapping(address => bytes32) public ownerToAgentId;
    address public admin;

    event AgentRegistered(bytes32 indexed agentId, address indexed owner, string endpoint);

    constructor() {
        admin = msg.sender;
    }

    function registerAgent(
        bytes32 agentId,
        string calldata endpoint,
        string calldata metadataUri,
        uint256 initialReputationBps
    ) external {
        require(agentId != bytes32(0), "Invalid agentId");
        require(agents[agentId].owner == address(0), "Already registered");
        require(initialReputationBps <= 10000, "Invalid reputation");

        agents[agentId] = AgentRecord({
            agentId: agentId,
            owner: msg.sender,
            endpoint: endpoint,
            metadataUri: metadataUri,
            reputationEmaBps: initialReputationBps,
            totalEvaluations: initialReputationBps > 0 ? 1 : 0,
            isActive: true
        });
        ownerToAgentId[msg.sender] = agentId;
        emit AgentRegistered(agentId, msg.sender, endpoint);
    }

    function setAgentActive(bytes32 agentId, bool isActive) external {
        require(agents[agentId].owner == msg.sender || msg.sender == admin, "Unauthorized");
        agents[agentId].isActive = isActive;
    }

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
        )
    {
        bytes32 id = ownerToAgentId[payee];
        if (id == bytes32(0)) {
            return (false, bytes32(0), "", "", 0, 0);
        }
        AgentRecord storage rec = agents[id];
        if (!rec.isActive || rec.owner != payee) {
            return (false, id, rec.endpoint, rec.metadataUri, rec.reputationEmaBps, rec.totalEvaluations);
        }
        return (true, id, rec.endpoint, rec.metadataUri, rec.reputationEmaBps, rec.totalEvaluations);
    }
}
