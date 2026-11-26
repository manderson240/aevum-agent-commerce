#!/usr/bin/env python3
"""Execute or inspect live QDay Aevum Testnet (Chain ID 44005) settlement using real tUSD8.

Uses legacy type-0 transactions matching QDay Aevum's RPC rules, verifies tQDAY gas and
tUSD8 balances, performs Confirmation of Payee lookup, settles escrow via Python EIP-191
oracle proof, and saves non-secret tx receipts to docs/aevum_testnet_deployment.json.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from eth_account import Account
from eth_account.messages import encode_defunct
from web3 import Web3

from sdk.aevum_agent import (
    AEVUM_CHAIN_ID,
    AEVUM_EXPLORER_URL,
    AEVUM_RPC_URL,
    AEVUM_TUSD8_ADDRESS,
    AevumAgentCommerce,
    to_bytes32,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

ERC20_ABI = [
    {"type": "function", "name": "balanceOf", "stateMutability": "view", "inputs": [{"name": "account", "type": "address"}], "outputs": [{"type": "uint256"}]},
    {"type": "function", "name": "approve", "stateMutability": "nonpayable", "inputs": [{"name": "spender", "type": "address"}, {"name": "amount", "type": "uint256"}], "outputs": [{"type": "bool"}]},
]

MOCK_REGISTRY_ABI = [
    {"type": "function", "name": "registerAgent", "stateMutability": "nonpayable", "inputs": [{"name": "agentId", "type": "bytes32"}, {"name": "endpoint", "type": "string"}, {"name": "metadataUri", "type": "string"}, {"name": "initialReputationBps", "type": "uint256"}], "outputs": []},
]

ERC8004_REGISTRY_ABI = [
    {"type": "function", "name": "registerAgent", "stateMutability": "nonpayable", "inputs": [{"name": "agentId", "type": "bytes32"}, {"name": "endpoint", "type": "string"}, {"name": "metadataUri", "type": "string"}], "outputs": []},
    {"type": "function", "name": "agentNonces", "stateMutability": "view", "inputs": [{"name": "", "type": "bytes32"}], "outputs": [{"type": "uint256"}]},
    {"type": "function", "name": "evalOracle", "stateMutability": "view", "inputs": [], "outputs": [{"type": "address"}]},
    {"type": "function", "name": "verifyPayee", "stateMutability": "view", "inputs": [{"name": "payee", "type": "address"}], "outputs": [{"name": "verified", "type": "bool"}, {"name": "agentId", "type": "bytes32"}, {"name": "endpoint", "type": "string"}, {"name": "metadataUri", "type": "string"}, {"name": "reputationEmaBps", "type": "uint256"}, {"name": "totalEvaluations", "type": "uint256"}]},
    {"type": "function", "name": "recordEvaluation", "stateMutability": "nonpayable", "inputs": [{"name": "agentId", "type": "bytes32"}, {"name": "qagScore", "type": "uint256"}, {"name": "rubricHash", "type": "bytes32"}, {"name": "v", "type": "uint8"}, {"name": "r", "type": "bytes32"}, {"name": "s", "type": "bytes32"}], "outputs": []},
]

ESCROW_ABI = [
    {"type": "function", "name": "payeeRegistry", "stateMutability": "view", "inputs": [], "outputs": [{"type": "address"}]},
    {"type": "function", "name": "confirmPayee", "stateMutability": "view", "inputs": [{"name": "payee", "type": "address"}], "outputs": [{"name": "verified", "type": "bool"}, {"name": "agentId", "type": "bytes32"}, {"name": "endpoint", "type": "string"}, {"name": "reputationEmaBps", "type": "uint256"}]},
    {"type": "function", "name": "createTaskEscrow", "stateMutability": "nonpayable", "inputs": [{"name": "taskId", "type": "bytes32"}, {"name": "worker", "type": "address"}, {"name": "amount", "type": "uint256"}, {"name": "deadline", "type": "uint256"}, {"name": "minQualityBps", "type": "uint256"}], "outputs": []},
    {"type": "function", "name": "submitDelivery", "stateMutability": "nonpayable", "inputs": [{"name": "taskId", "type": "bytes32"}, {"name": "outputHash", "type": "bytes32"}], "outputs": []},
    {"type": "function", "name": "completeTaskWithProof", "stateMutability": "nonpayable", "inputs": [{"name": "taskId", "type": "bytes32"}, {"name": "qagScore", "type": "uint256"}, {"name": "outputHash", "type": "bytes32"}, {"name": "v", "type": "uint8"}, {"name": "r", "type": "bytes32"}, {"name": "s", "type": "bytes32"}], "outputs": []},
]


def _load_dotenv_defaults(env_path: Path) -> None:
    """Load non-empty key=value pairs into os.environ without printing values."""
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, val = stripped.split("=", 1)
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and val and not os.environ.get(key):
            os.environ[key] = val


def _load_signer_key(keystore_path: str | None) -> str:
    if keystore_path:
        ks = Path(keystore_path).expanduser()
        if not ks.is_file():
            ks = Path.home() / ".foundry" / "keystores" / keystore_path
        password = getpass.getpass(f"Password for keystore {ks.name}: ")
        key_bytes = Account.decrypt(json.loads(ks.read_text(encoding="utf-8")), password)
        return "0x" + key_bytes.hex()
    key = os.getenv("PRIVATE_KEY", "").strip()
    if not key:
        raise SystemExit("Provide --keystore <name_or_path> or set PRIVATE_KEY in environment/.env")
    return key


def _send_legacy_tx(w3: Web3, account_key: str, fn: Any, gas_limit: int = 500_000) -> dict[str, Any]:
    acct = w3.eth.account.from_key(account_key)
    nonce = w3.eth.get_transaction_count(acct.address, "pending")
    tx = fn.build_transaction(
        {
            "from": acct.address,
            "nonce": nonce,
            "chainId": w3.eth.chain_id,
            "gas": gas_limit,
            "gasPrice": w3.eth.gas_price,
        }
    )
    signed = acct.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
    if receipt["status"] != 1:
        raise RuntimeError(f"Transaction reverted: 0x{tx_hash.hex()}")
    return {
        "tx_hash": "0x" + tx_hash.hex(),
        "block_number": int(receipt["blockNumber"]),
        "gas_used": int(receipt["gasUsed"]),
        "explorer_url": f"{AEVUM_EXPLORER_URL}/tx/0x{tx_hash.hex()}",
    }


def _register_payee_if_needed(
    w3: Web3, account_key: str, registry_addr: str, endpoint: str, metadata_uri: str
) -> dict[str, Any] | None:
    agent_id = to_bytes32(f"AEVUM_PAYEE_{int(time.time())}")
    acct_addr = w3.eth.account.from_key(account_key).address
    reg_erc8004 = w3.eth.contract(address=registry_addr, abi=ERC8004_REGISTRY_ABI)
    try:
        reg_erc8004.functions.registerAgent(agent_id, endpoint, metadata_uri).estimate_gas({"from": acct_addr})
        return _send_legacy_tx(w3, account_key, reg_erc8004.functions.registerAgent(agent_id, endpoint, metadata_uri))
    except Exception:
        reg_mock = w3.eth.contract(address=registry_addr, abi=MOCK_REGISTRY_ABI)
        return _send_legacy_tx(
            w3, account_key, reg_mock.functions.registerAgent(agent_id, endpoint, metadata_uri, 9200)
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run or check live Aevum testnet escrow settlement.")
    parser.add_argument("--keystore", help="Foundry keystore name (in ~/.foundry/keystores) or file path")
    parser.add_argument("--address", help="Public 0x address for --check-only mode without a key")
    parser.add_argument("--rpc-url", default="", help="RPC URL (defaults to AEVUM_RPC_URL or QDay testnet)")
    parser.add_argument("--escrow", default="", help="Deployed AevumAgentEscrow address (or ESCROW_ADDRESS)")
    parser.add_argument("--registry", default="", help="Deployed ERC-8004 registry (or escrow.payeeRegistry())")
    parser.add_argument("--tusd8", default="", help="tUSD8 token address (default: QDay Aevum tUSD8)")
    parser.add_argument("--amount", type=float, default=1.0, help="tUSD8 amount to settle (default: 1.0)")
    parser.add_argument("--check-only", action="store_true", help="Inspect chain ID and balances only")
    parser.add_argument("--allow-any-chain", action="store_true", help="Allow chain IDs other than 44005 (e.g. local fork)")
    parser.add_argument(
        "--record-eval",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Sign and broadcast ERC8004AgentRegistry.recordEvaluation after settlement",
    )
    parser.add_argument("--output", default=str(REPO_ROOT / "docs" / "aevum_testnet_deployment.json"))
    return parser.parse_args()


def main() -> int:
    _load_dotenv_defaults(REPO_ROOT / ".env")
    args = parse_args()

    rpc_url = args.rpc_url or os.getenv("AEVUM_RPC_URL", AEVUM_RPC_URL)
    escrow_raw = (args.escrow or os.getenv("ESCROW_ADDRESS", "")).strip()
    tusd8_addr = Web3.to_checksum_address(args.tusd8 or os.getenv("TUSD8_ADDRESS", AEVUM_TUSD8_ADDRESS))

    w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 20}))
    if not w3.is_connected():
        raise SystemExit(f"Could not connect to RPC: {rpc_url}")

    chain_id = int(w3.eth.chain_id)
    if not args.allow_any_chain and chain_id != AEVUM_CHAIN_ID:
        raise SystemExit(f"Expected Aevum Chain ID {AEVUM_CHAIN_ID}, got {chain_id}")

    tusd8 = w3.eth.contract(address=tusd8_addr, abi=ERC20_ABI)

    if args.check_only:
        addr = Web3.to_checksum_address(args.address) if args.address else Account.from_key(_load_signer_key(args.keystore)).address
        tqday = w3.eth.get_balance(addr) / 1e18
        bal_usd8 = tusd8.functions.balanceOf(addr).call() / 1e6
        print(f"Chain ID: {chain_id}, Block: {w3.eth.block_number}")
        print(f"Address:  {addr}")
        print(f"tQDAY:    {tqday:.6f}")
        print(f"tUSD8:    {bal_usd8:.6f}")
        if escrow_raw:
            escrow = w3.eth.contract(address=Web3.to_checksum_address(escrow_raw), abi=ESCROW_ABI)
            verified, _, endpoint, ema = escrow.functions.confirmPayee(addr).call()
            print(f"Payee verified={verified}, endpoint={endpoint}, ema_bps={ema}")
        return 0

    if not escrow_raw:
        raise SystemExit("ESCROW_ADDRESS (or --escrow) is required for live settlement")
    escrow_addr = Web3.to_checksum_address(escrow_raw)
    account_key = _load_signer_key(args.keystore)
    acct_addr = Account.from_key(account_key).address

    tqday_wei = w3.eth.get_balance(acct_addr)
    amount_raw = int(round(args.amount * 1_000_000))
    usd8_raw = tusd8.functions.balanceOf(acct_addr).call()
    if tqday_wei == 0:
        raise SystemExit(f"Address {acct_addr} has 0 tQDAY; claim /faucet in QDay Discord first.")
    if usd8_raw < amount_raw:
        raise SystemExit(f"Address {acct_addr} has {usd8_raw / 1e6:.6f} tUSD8, need {args.amount:.2f}.")

    escrow = w3.eth.contract(address=escrow_addr, abi=ESCROW_ABI)
    registry_addr = Web3.to_checksum_address(
        args.registry or os.getenv("ERC8004_REGISTRY_ADDRESS", "") or escrow.functions.payeeRegistry().call()
    )

    txs: dict[str, Any] = {}
    verified_before, _, _, _ = escrow.functions.confirmPayee(acct_addr).call()
    if not verified_before:
        txs["registerAgent"] = _register_payee_if_needed(
            w3,
            account_key,
            registry_addr,
            "https://payee.example/v1",
            "https://github.com/manderson240/aevum-agent-commerce",
        )

    sdk = AevumAgentCommerce(escrow_address=escrow_addr, rpc_url=rpc_url, chain_id=chain_id)
    payee = sdk.confirm_payee_rpc(acct_addr)
    if not payee.verified:
        raise RuntimeError("confirmPayee returned verified=False after registration")

    task_id_str = f"TASK-AEVUM-LIVE-{int(time.time())}"
    task_id = to_bytes32(task_id_str)
    deadline = int(time.time()) + 3600

    txs["approve_tUSD8"] = _send_legacy_tx(w3, account_key, tusd8.functions.approve(escrow_addr, amount_raw))
    txs["createTaskEscrow"] = _send_legacy_tx(
        w3, account_key, escrow.functions.createTaskEscrow(task_id, acct_addr, amount_raw, deadline, 8500)
    )

    output_hash = bytes(Web3.keccak(text=f"Aevum live verified delivery {task_id_str}"))
    txs["submitDelivery"] = _send_legacy_tx(
        w3, account_key, escrow.functions.submitDelivery(task_id, output_hash)
    )

    sig = sdk.sign_completion_proof(
        task_id=task_id_str,
        nonce=0,
        qag_score_bps=9200,
        output_hash="0x" + output_hash.hex(),
        private_oracle_key=account_key,
    )
    txs["completeTaskWithProof"] = _send_legacy_tx(
        w3,
        account_key,
        escrow.functions.completeTaskWithProof(
            task_id,
            9200,
            output_hash,
            sig.v,
            bytes.fromhex(sig.r_hex[2:]),
            bytes.fromhex(sig.s_hex[2:]),
        ),
    )

    total_evaluations = 0
    if args.record_eval and registry_addr:
        reg_erc = w3.eth.contract(address=registry_addr, abi=ERC8004_REGISTRY_ABI)
        try:
            eval_oracle = reg_erc.functions.evalOracle().call()
            if eval_oracle.lower() == acct_addr.lower():
                aid_bytes = bytes.fromhex(payee.agent_id[2:])
                eval_nonce = int(reg_erc.functions.agentNonces(aid_bytes).call())
                rubric_str = f"{task_id_str}-QAG-RUBRIC-V1"
                rubric_hash = bytes(Web3.keccak(text=rubric_str))
                raw_digest = Web3.solidity_keccak(
                    ["bytes32", "uint256", "uint256", "bytes32", "uint256", "address"],
                    [aid_bytes, eval_nonce, 9200, rubric_hash, chain_id, registry_addr],
                )
                signed_eval = Account.sign_message(
                    encode_defunct(hexstr="0x" + raw_digest.hex()),
                    private_key=account_key,
                )
                txs["recordEvaluation"] = _send_legacy_tx(
                    w3,
                    account_key,
                    reg_erc.functions.recordEvaluation(
                        aid_bytes,
                        9200,
                        rubric_hash,
                        int(signed_eval.v),
                        int(signed_eval.r).to_bytes(32, "big"),
                        int(signed_eval.s).to_bytes(32, "big"),
                    ),
                )
                txs["recordEvaluation"]["score_bps"] = 9200
                txs["recordEvaluation"]["rubric"] = rubric_str
        except Exception:
            pass

    payee = sdk.confirm_payee_rpc(acct_addr)
    try:
        reg_details = sdk.check_registry_details_rpc(acct_addr, registry_addr)
        total_evaluations = int(reg_details["total_evaluations"])
    except Exception:
        total_evaluations = 0

    commit_sha = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=REPO_ROOT, text=True).strip()
    report = {
        "network": "QDay Aevum Testnet",
        "chain_id": chain_id,
        "rpc_url": rpc_url,
        "explorer_url": AEVUM_EXPLORER_URL,
        "git_commit": commit_sha,
        "contracts": {
            "tUSD8": tusd8_addr,
            "erc8004_registry": registry_addr,
            "aevum_agent_escrow": escrow_addr,
        },
        "participant": acct_addr,
        "confirm_payee": {
            "verified": payee.verified,
            "agent_id": payee.agent_id,
            "endpoint": payee.endpoint,
            "reputation_ema_bps": payee.reputation_ema_bps,
            "total_evaluations": total_evaluations,
        },
        "task_id": task_id_str,
        "amount_tusd8": args.amount,
        "transactions": txs,
    }
    out_path = Path(args.output)
    out_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"LIVE AEVUM SETTLEMENT COMPLETE -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
