#!/usr/bin/env python3
"""End-to-End Local Anvil Verification: Python SDK <-> Solidity Escrow + Confirmation of Payee.

Starts an ephemeral Anvil node, deploys MockUSD8, MockERC8004Registry, and
AevumAgentEscrow via compiled Foundry artifacts, registers the worker in
ERC-8004, confirms the payee from Python, creates escrow, submits delivery,
signs the completion digest with `AevumAgentCommerce.sign_completion_proof()`,
and executes `completeTaskWithProof()` on-chain to transfer MockUSD8 tokens.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

from web3 import Web3

from sdk.aevum_agent import AevumAgentCommerce, to_bytes32


REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_artifact(name: str) -> tuple[list[dict[str, object]], str]:
    artifact = json.loads((REPO_ROOT / "out" / f"{name}.sol" / f"{name}.json").read_text())
    return artifact["abi"], artifact["bytecode"]["object"]


def _deploy(w3: Web3, account_key: str, abi: list[dict[str, object]], bytecode: str, *args: object):
    acct = w3.eth.account.from_key(account_key)
    contract = w3.eth.contract(abi=abi, bytecode=bytecode)
    tx = contract.constructor(*args).build_transaction(
        {
            "from": acct.address,
            "nonce": w3.eth.get_transaction_count(acct.address),
            "chainId": w3.eth.chain_id,
            "gas": 3_000_000,
            "gasPrice": w3.eth.gas_price,
        }
    )
    signed = acct.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    assert receipt["status"] == 1
    return w3.eth.contract(address=receipt["contractAddress"], abi=abi)


def _send_fn(w3: Web3, account_key: str, fn) -> dict[str, object]:
    acct = w3.eth.account.from_key(account_key)
    tx = fn.build_transaction(
        {
            "from": acct.address,
            "nonce": w3.eth.get_transaction_count(acct.address),
            "chainId": w3.eth.chain_id,
            "gas": 1_000_000,
            "gasPrice": w3.eth.gas_price,
        }
    )
    signed = acct.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    assert receipt["status"] == 1
    return dict(receipt)


def main() -> int:
    anvil_bin = shutil.which("anvil") or str(Path.home() / ".foundry" / "bin" / "anvil")
    forge_bin = shutil.which("forge") or str(Path.home() / ".foundry" / "bin" / "forge")

    subprocess.run([forge_bin, "build"], cwd=str(REPO_ROOT), check=True, capture_output=True)

    port = 18545
    proc = subprocess.Popen(
        [anvil_bin, "--hardfork", "shanghai", "--port", str(port), "--silent"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        rpc_url = f"http://127.0.0.1:{port}"
        w3 = Web3(Web3.HTTPProvider(rpc_url))
        for _ in range(30):
            if w3.is_connected():
                break
            time.sleep(0.1)
        assert w3.is_connected(), "Anvil failed to start"

        # Default deterministic Anvil dev keys
        client_key = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
        worker_key = "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d"
        oracle_key = "0x5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a"

        client_addr = w3.eth.account.from_key(client_key).address
        worker_addr = w3.eth.account.from_key(worker_key).address
        oracle_addr = w3.eth.account.from_key(oracle_key).address

        token_abi, token_bin = _load_artifact("MockUSD8")
        reg_abi, reg_bin = _load_artifact("MockERC8004Registry")
        escrow_abi, escrow_bin = _load_artifact("AevumAgentEscrow")

        token = _deploy(w3, client_key, token_abi, token_bin)
        registry = _deploy(w3, client_key, reg_abi, reg_bin)
        escrow = _deploy(w3, client_key, escrow_abi, escrow_bin, token.address, oracle_addr)

        _send_fn(w3, client_key, escrow.functions.setPayeeRegistry(registry.address, True))
        _send_fn(
            w3,
            worker_key,
            registry.functions.registerAgent(
                to_bytes32("AEVUM_WORKER_01"),
                "https://payee.example/v1",
                "ipfs://QmWorkerMetadata",
                9200,
            ),
        )
        amount = 250 * 10**6
        _send_fn(w3, client_key, token.functions.mint(client_addr, 1000 * 10**6))
        _send_fn(w3, client_key, token.functions.approve(escrow.address, amount))

        sdk = AevumAgentCommerce(escrow_address=escrow.address, rpc_url=rpc_url, chain_id=w3.eth.chain_id)
        payee = sdk.confirm_payee_rpc(worker_addr)
        assert payee.verified is True
        assert payee.endpoint == "https://payee.example/v1"

        task_id_str = "TASK-ANVIL-PARITY-01"
        task_id = to_bytes32(task_id_str)
        deadline = int(time.time()) + 3600
        _send_fn(
            w3,
            client_key,
            escrow.functions.createTaskEscrow(task_id, worker_addr, amount, deadline, 8500),
        )

        deliverable = "Verified ERC-8004 settlement payload"
        output_hash = bytes(Web3.keccak(text=deliverable))
        _send_fn(w3, worker_key, escrow.functions.submitDelivery(task_id, output_hash))

        sig = sdk.sign_completion_proof(
            task_id=task_id_str,
            nonce=0,
            qag_score_bps=9200,
            output_hash="0x" + output_hash.hex(),
            private_oracle_key=oracle_key,
        )
        _send_fn(
            w3,
            client_key,
            escrow.functions.completeTaskWithProof(
                task_id,
                9200,
                output_hash,
                sig.v,
                bytes.fromhex(sig.r_hex[2:]),
                bytes.fromhex(sig.s_hex[2:]),
            ),
        )

        worker_bal = token.functions.balanceOf(worker_addr).call()
        assert worker_bal == amount, f"Expected {amount}, got {worker_bal}"
        print(f"E2E ANVIL PARITY PASSED: worker tUSD8 balance={worker_bal / 1e6:.2f}, payee={payee.endpoint}")
        return 0
    finally:
        proc.terminate()
        proc.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
