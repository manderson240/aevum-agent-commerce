# Aevum Agent Commerce Protocol



> **Verifiable Micro-Settlement & Quality Escrow for Autonomous AI Swarms on Aevum Testnet (`tUSD8`)**  
> *Submitted to the Aevum Builder Challenge #1 (Nov 16 to Dec 11, 2026)*

[![Foundry](https://img.shields.io/badge/Foundry-passing-brightgreen.svg)](https://github.com/foundry-rs/foundry)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)

---

## Executive Summary

As AI agents transition from read-only assistants into autonomous economic actors, agent-to-agent transactions face severe risks:
1. **Hallucination / Quality Default Risk**: Client agents pay upfront for deliverables that fail execution checks or contain synthetic hallucinations.
2. **Double-Spend & Chargeback Fraud**: Service agents perform expensive GPU inference but get front-run or denied payment.
3. **Lack of Native Verifiable UI**: Web3 agent protocols lack visual transparency for human observers and operator oversight.

**Aevum Agent Commerce** solves this by introducing a **non-reentrant, threshold-conditioned escrow protocol** natively integrated with Aevum Testnet and `tUSD8`. Agent payments remain securely locked until cryptographic verification of quality standards (e.g., QAG score $\ge 85\%$) is attested on-chain. Deliverables and settlement state are rendered dynamically using **Google A2UI 1.0** declarative interfaces.

---

## System Architecture

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

### Interactive Settlement Sequence

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

### Escrow Lifecycle State Machine

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

---

## Key Features

1. **Deterministic Quality-Gated Settlement**:
   Payments cannot be withdrawn by worker agents unless accompanied by an ECDSA signature from the Verifier Oracle validating that the quality threshold (`minQualityBps`) was exceeded.
2. **Guaranteed Client Refund Guarantee**:
   If an agent hangs, times out, or fails to deliver before `deadline`, the client agent can reclaim 100% of the locked `tUSD8` without administrative intervention.
3. **Property-Based Fuzzing Tested**:
   Includes a 256-run Foundry fuzzing suite validating arbitrary token quantities and quality boundaries without precision loss or invariant failure.
4. **Declarative Google A2UI 1.0 Surfaces**:
   Built-in Python SDK automatically compiles transaction proofs into A2UI JSON components, providing transparent visual dashboards for agent swarms.

---

## Smart Contract Specification

- **`AevumAgentEscrow.sol`**:
  - `createTaskEscrow(bytes32 taskId, address worker, uint256 amount, uint256 deadline, uint256 minQualityBps)`
  - `completeTaskWithProof(bytes32 taskId, uint256 qagScore, bytes32 outputHash, uint8 v, bytes32 r, bytes32 s)`
  - `refundExpiredEscrow(bytes32 taskId)`
  - `cancelTask(bytes32 taskId)`
- **`MockUSD8.sol`**:
  - 6-decimal standard ERC20 mock simulating Aevum's native `tUSD8` stablecoin.

---

## Testing & Verification

### 1. Foundry Solidity Tests
```bash
# Run all unit tests and property fuzzing
forge test -vvv
```
Output:
```
Ran 6 tests for test/AevumAgentEscrow.t.sol:AevumAgentEscrowTest
[PASS] testFuzz_EscrowSettlement(uint256,uint256) (runs: 256, μ: 322480, ~: 309789)
[PASS] test_CompleteTaskWithValidProof() (gas: 377072)
[PASS] test_CreateTaskEscrow() (gas: 246689)
[PASS] test_RefundExpiredEscrow() (gas: 366605)
[PASS] test_RevertOnInvalidSignature() (gas: 270180)
[PASS] test_RevertOnSubparQuality() (gas: 268598)
Suite result: ok. 6 passed; 0 failed; 0 skipped
```

### 2. Python SDK Unit Tests
```bash
uv run pytest
```

---

## Deployment Guide (Aevum Testnet)

1. Set your private key and RPC endpoint in `.env`:
   ```bash
   AEVUM_RPC_URL="https://rpc-testnet.aevum.network"
   PRIVATE_KEY="0x..."
   TUSD8_ADDRESS="0x..."
   ORACLE_ADDRESS="0x..."
   ```
2. Deploy the Escrow Contract:
   ```bash
   forge create --rpc-url $AEVUM_RPC_URL \
     --private-key $PRIVATE_KEY \
     src/AevumAgentEscrow.sol:AevumAgentEscrow \
     --constructor-args $TUSD8_ADDRESS $ORACLE_ADDRESS
   ```

---

## License

MIT License. Designed for open deployment across the Aevum ecosystem.
