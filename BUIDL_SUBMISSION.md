# DoraHacks BUIDL Submission: Aevum Agent Commerce

**Hackathon**: Aevum Builder Challenge #1 (Nov 16 to Dec 11, 2026)  
**Track**: DeFi / Agentic Infrastructure / Quantum-Resistant Commerce  
**Repository**: https://github.com/manderson240/aevum-agent-commerce  

This file mirrors what I entered in the DoraHacks form.

---

## Form fields

### Name
```text
Aevum Agent Commerce
```

### Brief description (120 characters max, this one is 118)
```text
Quality-gated tUSD8 escrow for AI agent payments: the worker is paid only on an oracle-signed score above a threshold.
```

### Tags
```text
DeFi, AI Agents
```

### Team
```text
Mike Anderson (Solo builder, github.com/manderson240)
```

### Links
- GitHub: https://github.com/manderson240/aevum-agent-commerce
- Demo video: https://github.com/manderson240/aevum-agent-commerce/raw/main/docs/aevum_commerce_demo.mp4

### Contact
- Telegram: `manderson240`
- Discord: `miked238725`

---

## Description

# Aevum Agent Commerce

### Why I built this
When one AI agent pays another for work, paying up front means the client loses the money if the output is bad, and paying afterwards means the worker can be stiffed. I wanted a small escrow where the payment waits on a signed quality score, and where the client always has a way to get the money back if the work never gets certified.

### How it works
I wrote one Solidity contract, [`src/AevumAgentEscrow.sol`](src/AevumAgentEscrow.sol), and a 6-decimal test token, [`src/MockUSD8.sol`](src/MockUSD8.sol), that stands in for `tUSD8`.

1. `createTaskEscrow(taskId, worker, amount, deadline, minQualityBps)` locks `amount` tokens from the client and records the task as ACTIVE. It rejects a reused task ID, a zero worker, a zero amount, a past deadline and a threshold above 10000 basis points.
2. `completeTaskWithProof(taskId, qagScore, outputHash, v, r, s)` pays the worker only if the task is ACTIVE, `qagScore >= minQualityBps`, and `ecrecover` over an EIP-191 signed digest of `(taskId, qagScore, outputHash, address(this))` returns the oracle address fixed in the constructor.
3. `refundExpiredEscrow(taskId)` returns the tokens to the client once the deadline has passed.
4. `cancelTask(taskId)` lets the client or the worker cancel an ACTIVE task, which also refunds the client.

Every exit requires ACTIVE and changes the status before transferring, so a task pays out or refunds once. All four functions use a `nonReentrant` lock.

There is also a Python helper, [`sdk/aevum_agent.py`](sdk/aevum_agent.py). `AevumAgentCommerce` creates `CommerceTask` records, applies the same score threshold in memory, SHA-256 hashes the deliverable, and builds a JSON dict shaped like a Google A2UI card for showing a task's status. It does not talk to a chain.

### Aevum and tUSD8
- The contract takes any ERC-20 as the payment token. I tested it against `MockUSD8`, a 6-decimal token with the `tUSD8` symbol.
- `foundry.toml` has an `aevum_testnet` RPC endpoint (`https://rpc-testnet.aevum.network`), and the Python helper uses the same URL as its default `rpc_url`.
- I have not deployed the contract to the Aevum testnet, and the repo contains no deployed address.

### Limits
- There is no oracle or scoring service in the repo. The tests sign scores with a fixed test key.
- The signed digest has no nonce and no chain ID; replay on the same contract is blocked by the status change.
- A client can cancel after delivery but before the proof is submitted.
- ECDSA over secp256k1 is not post-quantum.

### Verification
On my machine:
- `forge test -vv` (Foundry 1.9.0): 6 of 6 tests pass, including a 256-run fuzz test over amount and score, in 13.47 ms.
- `uv run pytest -q`: 3 of 3 Python tests pass in 0.01 s.

```bash
git clone https://github.com/manderson240/aevum-agent-commerce.git
cd aevum-agent-commerce
forge test -vv
uv run pytest -q
```

---

## Architecture diagrams

See [README.md](README.md#how-it-works) for the sequence diagram and state diagram.
