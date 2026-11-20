# DoraHacks BUIDL Submission: Aevum Agent Commerce

## 1. Project Overview
- **Project Name**: Aevum Agent Commerce Protocol
- **Tagline**: Verifiable Autonomous Micro-Settlement & Quality Escrow for AI Agent Swarms on Aevum Testnet (`tUSD8`)
- **Hackathon**: Aevum Builder Challenge #1 (Nov 16 to Dec 11, 2026)
- **Track**: DeFi / Agentic Infrastructure / Quantum-Resistant Commerce
- **GitHub Repository**: https://github.com/manderson240/aevum-agent-commerce
- **Demo Video (2K QHD)**: [`docs/aevum_commerce_demo.mp4`](docs/aevum_commerce_demo.mp4) (6-Scene Full-Code Walkthrough)

---

## 2. Problem Statement
Autonomous AI agents need to pay each other for compute, subagent orchestration, and proprietary data in real time. Traditional payments fail because:
1. **AI Deliverables are Stochastic**: Agents frequently hallucinate or produce malformed outputs. Once payment is sent, funds are irretrievable.
2. **High Dispute Latency**: Human arbitration is impossible at 1,000 requests/second.
3. **Lack of Trustworthy Standard**: Without programmatic proof of deliverable quality, autonomous swarms cannot form trustless commerce rings.

---

## 3. The Solution: Aevum Agent Commerce
Aevum Agent Commerce provides high-throughput, non-reentrant smart escrow contracts that lock `tUSD8` stablecoin funds until an independent verifier oracle cryptographically certifies deliverable quality above a defined threshold ($\ge 85\%$).

Key Highlights:
- **Zero-Loss Guarantee**: Timeout refunds ensure unfulfilled tasks return 100% of capital to clients.
- **Cryptographic Oracle Signatures**: ECDSA signed proofs prevent counterfeit delivery claims.
- **Google A2UI 1.0 Generative UI**: Declarative JSON card schemas visualize agent escrow balances, verification scores, and settlement actions.
- **Battle-Tested**: 100% test coverage with 256-run Foundry fuzzing.

---

## 4. Technical Architecture

### End-to-End System Architecture
```mermaid
flowchart TD
    subgraph ClientLayer["Client Autonomous Agent Layer"]
        ClientAgent["Client Agent / Task Coordinator"]
        ClientWallet["Agent EOA / Smart Account"]
    end

    subgraph AevumChain["Aevum Testnet Blockchain (Execution Layer)"]
        Escrow["AevumAgentEscrow.sol<br/><i>Non-Reentrant Vault & Invariant Enforcer</i>"]
        TUSD8["MockUSD8 (tUSD8 Stablecoin)<br/><i>ERC-20 Token Balance Vault</i>"]
        StateStore["Task State Registry<br/>(status, amount, deadline, minQualityBps)"]
    end

    subgraph WorkerLayer["Decentralized Worker & Inference Layer"]
        WorkerAgent["Worker Agent / Compute Provider"]
        ExecutionRuntime["Task Execution Runtime (GPU / LLM)"]
    end

    subgraph OracleLayer["Independent Verification Oracle Network"]
        VerifierOracle["Verifier Oracle / AutoHarness"]
        QAGScorer["Discrete QAG Quality Scorer"]
        ECDSASigner["ECDSA Attestation Signer (secp256k1)"]
    end

    subgraph SurfaceLayer["User Supervision & Generative UI"]
        A2UI["Google A2UI 1.0 Declarative Engine"]
        InspectorCard["Escrow Dashboard & Action Buttons"]
    end

    ClientAgent -->|"1. createTaskEscrow(taskId, worker, amount, deadline, minQualityBps)"| Escrow
    ClientAgent -->|"Deposit tUSD8"| TUSD8
    Escrow -->|"Lock Funds"| TUSD8
    Escrow -->|"Record Task Parameters"| StateStore

    Escrow -.->|"2. Event: TaskCreated"| WorkerAgent
    WorkerAgent -->|"Execute Compute"| ExecutionRuntime
    ExecutionRuntime -->|"3. Submit Output & Deliverable Hash"| VerifierOracle

    VerifierOracle --> QAGScorer
    QAGScorer -->|"Score >= minQualityBps"| ECDSASigner
    ECDSASigner -->|"4. completeTaskWithProof(taskId, score, hash, v, r, s)"| Escrow

    Escrow -->|"5. Transfer tUSD8"| WorkerAgent
    Escrow -->|"Timeout Refund (if deadline expired)"| ClientAgent

    Escrow -.->|"State Update Event"| A2UI
    A2UI --> InspectorCard

    classDef client fill:#1e1e2e,stroke:#cba6f7,stroke-width:2px,color:#cdd6f4;
    classDef aevum fill:#181825,stroke:#89b4fa,stroke-width:2px,color:#cdd6f4;
    classDef worker fill:#313244,stroke:#f9e2af,stroke-width:2px,color:#cdd6f4;
    classDef oracle fill:#313244,stroke:#a6e3a1,stroke-width:2px,color:#cdd6f4;
    classDef surface fill:#313244,stroke:#f38ba8,stroke-width:2px,color:#cdd6f4;

    class ClientLayer,ClientAgent,ClientWallet client;
    class AevumChain,Escrow,TUSD8,StateStore aevum;
    class WorkerLayer,WorkerAgent,ExecutionRuntime worker;
    class OracleLayer,VerifierOracle,QAGScorer,ECDSASigner oracle;
    class SurfaceLayer,A2UI,InspectorCard surface;
```

### Multi-Party Settlement Sequence
```mermaid
sequenceDiagram
    autonumber
    actor Client as Client Agent
    participant Escrow as AevumAgentEscrow.sol
    participant Token as tUSD8 Token Vault
    actor Worker as Worker Agent
    participant Oracle as Verifier Oracle
    participant A2UI as Google A2UI Surface

    Client->>Token: approve(Escrow, amount)
    Client->>Escrow: createTaskEscrow(taskId, worker, amount, deadline, minQualityBps)
    activate Escrow
    Escrow->>Token: transferFrom(Client, Escrow, amount)
    Escrow-->>Client: emit TaskCreated(taskId, worker, amount)
    deactivate Escrow

    Escrow-->>Worker: Notification: Task Assigned
    activate Worker
    Worker->>Worker: Run Inference & Generate Deliverable
    Worker->>Oracle: submitDeliverable(taskId, deliverablePayload)
    deactivate Worker
    activate Oracle

    Oracle->>Oracle: Evaluate QAG Claims & Invariants (Score: 9200 bps)
    Oracle->>Oracle: Sign ECDSA Digest(taskId, score, outputHash)
    Oracle-->>Worker: Signature Proof (v, r, s, score, outputHash)
    deactivate Oracle

    activate Worker
    Worker->>Escrow: completeTaskWithProof(taskId, score, outputHash, v, r, s)
    deactivate Worker
    activate Escrow

    Escrow->>Escrow: Validate Signature, Task Status & Nonce
    Escrow->>Escrow: Assert score >= minQualityBps
    Escrow->>Token: transfer(Worker, amount)
    Escrow-->>A2UI: emit TaskCompleted(taskId, worker, amount, score)
    deactivate Escrow

    activate A2UI
    A2UI-->>Client: Render Settlement Receipt & Verifier Attestation Card
    deactivate A2UI
```

### Escrow State Machine Lifecycle
```mermaid
stateDiagram-v2
    [*] --> Uninitialized
    Uninitialized --> Active: createTaskEscrow() [tUSD8 Locked]
    
    Active --> Verifying: Worker Submits Deliverable
    Verifying --> Active: Re-run Request (Before Deadline)
    
    Verifying --> Completed: completeTaskWithProof() [Score >= minQualityBps]
    Active --> Cancelled: cancelTask() [Client cancels before worker assignment]
    Active --> Refunded: refundExpiredEscrow() [Block.timestamp > Deadline]
    Verifying --> Refunded: refundExpiredEscrow() [Deadline Reached]
    
    Completed --> [*]: Funds Transferred to Worker
    Cancelled --> [*]: 100% Funds Returned to Client
    Refunded --> [*]: 100% Funds Reclaimed by Client
```

### Implementation Specifications
- **Smart Contracts**: Solidity 0.8.24 with optimizer enabled (`AevumAgentEscrow.sol`, `MockUSD8.sol`).
- **Development Framework**: Foundry (`forge test -vvv` 6/6 tests passing in 35ms).
- **Agent Integration SDK**: Python 3.11+ async SDK (`sdk/aevum_agent.py`) with A2UI 1.0 generative UI rendering.

---

## 5. Potential Impact & Ecosystem Alignment
Aevum requires high-velocity transaction flow and real economic utility on its testnet. Aevum Agent Commerce brings:
- **Instant Volume**: Autonomous agent swarms executing dozens of micro-transactions per minute in `tUSD8`.
- **Ecosystem Standard**: The reference implementation for agent-to-agent paid APIs, subagent bounties, and decentralized task markets on Aevum.
