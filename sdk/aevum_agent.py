"""Aevum Agent Commerce SDK.

Provides high-level interfaces for AI agents to run ERC-8004 Confirmation of Payee
lookups, deposit tUSD8 escrow, sign Solidity-matching EIP-191 completion proofs,
and render A2UI 1.0 transaction cards.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, TypeVar
from urllib.parse import urlparse

from eth_account import Account
from eth_account.messages import encode_defunct
from web3 import Web3


AEVUM_RPC_URL = "https://rpc-test.qday.info"
AEVUM_CHAIN_ID = 44005
AEVUM_EXPLORER_URL = "https://explorer-test.qday.info"
AEVUM_TUSD8_ADDRESS = "0x456569838f1d43009A91ebA4263147Afd7233483"
AEVUM_DEFAULT_ESCROW_ADDRESS = "0xFF26781D65a8D7589699B6bcd4Cb137Bf67A7d64"
AEVUM_DEFAULT_REGISTRY_ADDRESS = "0x4595b33f41723c6f70F60adf05A69c8D2AB978e2"
AEVUM_DEFAULT_VERIFIED_PAYEE = "0x030e513B96A0B419942f4D6ECB250f172344585e"
AEVUM_MAX_LOG_RANGE = 1000
DEFAULT_RPC_TIMEOUT_SECONDS = 15

_T = TypeVar("_T")


def _rpc_call_with_retry(fn: Callable[[], _T], attempts: int = 3) -> _T:
    """Execute a read-only RPC call with bounded retries on transient failures."""
    last_exc: Exception | None = None
    total = max(1, int(attempts))
    for attempt in range(total):
        try:
            return fn()
        except Exception as exc:
            last_exc = exc
            if attempt + 1 < total:
                time.sleep(0.5 * (attempt + 1))
    assert last_exc is not None
    raise last_exc


ESCROW_CONFIRM_PAYEE_ABI = [
    {
        "type": "function",
        "name": "confirmPayee",
        "stateMutability": "view",
        "inputs": [{"name": "payee", "type": "address"}],
        "outputs": [
            {"name": "verified", "type": "bool"},
            {"name": "agentId", "type": "bytes32"},
            {"name": "endpoint", "type": "string"},
            {"name": "reputationEmaBps", "type": "uint256"},
        ],
    }
]

ERC8004_VERIFY_PAYEE_ABI = [
    {
        "type": "function",
        "name": "verifyPayee",
        "stateMutability": "view",
        "inputs": [{"name": "payee", "type": "address"}],
        "outputs": [
            {"name": "verified", "type": "bool"},
            {"name": "agentId", "type": "bytes32"},
            {"name": "endpoint", "type": "string"},
            {"name": "metadataUri", "type": "string"},
            {"name": "reputationEmaBps", "type": "uint256"},
            {"name": "totalEvaluations", "type": "uint256"},
        ],
    }
]

ESCROW_EVENT_ABIS = [
    {
        "type": "event",
        "name": "TaskCreated",
        "inputs": [
            {"name": "taskId", "type": "bytes32", "indexed": True},
            {"name": "client", "type": "address", "indexed": True},
            {"name": "worker", "type": "address", "indexed": True},
            {"name": "amount", "type": "uint256", "indexed": False},
            {"name": "deadline", "type": "uint256", "indexed": False},
            {"name": "minQualityBps", "type": "uint256", "indexed": False},
        ],
    },
    {
        "type": "event",
        "name": "TaskDelivered",
        "inputs": [
            {"name": "taskId", "type": "bytes32", "indexed": True},
            {"name": "worker", "type": "address", "indexed": True},
            {"name": "outputHash", "type": "bytes32", "indexed": False},
        ],
    },
    {
        "type": "event",
        "name": "TaskCompleted",
        "inputs": [
            {"name": "taskId", "type": "bytes32", "indexed": True},
            {"name": "worker", "type": "address", "indexed": True},
            {"name": "amount", "type": "uint256", "indexed": False},
            {"name": "finalScore", "type": "uint256", "indexed": False},
            {"name": "outputHash", "type": "bytes32", "indexed": False},
            {"name": "nonce", "type": "uint256", "indexed": False},
        ],
    },
    {
        "type": "event",
        "name": "TaskRefunded",
        "inputs": [
            {"name": "taskId", "type": "bytes32", "indexed": True},
            {"name": "client", "type": "address", "indexed": True},
            {"name": "amount", "type": "uint256", "indexed": False},
            {"name": "reason", "type": "string", "indexed": False},
        ],
    },
    {
        "type": "event",
        "name": "PayeeRegistryUpdated",
        "inputs": [
            {"name": "registry", "type": "address", "indexed": True},
            {"name": "required", "type": "bool", "indexed": False},
        ],
    },
]

_ESCROW_EVENT_TOPICS: Dict[str, str] = {
    "0x" + Web3.keccak(text="TaskCreated(bytes32,address,address,uint256,uint256,uint256)").hex(): "TaskCreated",
    "0x" + Web3.keccak(text="TaskDelivered(bytes32,address,bytes32)").hex(): "TaskDelivered",
    "0x" + Web3.keccak(text="TaskCompleted(bytes32,address,uint256,uint256,bytes32,uint256)").hex(): "TaskCompleted",
    "0x" + Web3.keccak(text="TaskRefunded(bytes32,address,uint256,string)").hex(): "TaskRefunded",
    "0x" + Web3.keccak(text="PayeeRegistryUpdated(address,bool)").hex(): "PayeeRegistryUpdated",
}


def to_bytes32(value: str) -> bytes:
    """Normalize a 32-byte hex string or arbitrary text ID into 32 bytes."""
    if value.startswith("0x") and len(value) == 66:
        try:
            return bytes.fromhex(value[2:])
        except ValueError:
            pass
    return bytes(Web3.keccak(text=value))


@dataclass
class CommerceTask:
    task_id: str
    client_address: str
    worker_address: str
    amount_usd8: float
    deadline_ts: int
    min_quality_bps: int
    status: str = "ACTIVE"
    evaluated_score: Optional[int] = None
    proof_hash: Optional[str] = None
    nonce: int = 0


@dataclass(frozen=True, slots=True)
class PayeeConfirmation:
    payee: str
    verified: bool
    agent_id: str
    endpoint: str
    reputation_ema_bps: int


def match_expected_endpoint(conf: PayeeConfirmation, expected_endpoint: str) -> str:
    """Compare the endpoint the sender expects with the one the registry holds.

    Returns "unverified" when the payee is not registered, "match" when the host names
    are equal, and "mismatch" otherwise. A registered address that does not belong to the
    party the sender meant to pay is the typo and impersonation case this guards.
    """
    if not conf.verified:
        return "unverified"
    want = urlparse(expected_endpoint.strip()).hostname
    have = urlparse(conf.endpoint.strip()).hostname
    return "match" if want and have and want.lower() == have.lower() else "mismatch"


@dataclass(frozen=True, slots=True)
class CompletionProofSignature:
    digest_hex: str
    v: int
    r_hex: str
    s_hex: str
    signer: str


class AevumAgentCommerce:
    """Agent Commerce Client for QDay Aevum Testnet (Confirmation of Payee + quality-gated tUSD8 escrow)."""

    def __init__(
        self,
        escrow_address: str,
        rpc_url: str = AEVUM_RPC_URL,
        chain_id: int = AEVUM_CHAIN_ID,
    ) -> None:
        self.escrow_address = Web3.to_checksum_address(escrow_address)
        self.rpc_url = rpc_url
        self.chain_id = int(chain_id)

    def create_task_order(
        self,
        task_id: str,
        client: str,
        worker: str,
        amount_usd8: float,
        duration_seconds: int = 3600,
        min_quality_bps: int = 8500,
    ) -> CommerceTask:
        deadline = int(time.time()) + duration_seconds
        return CommerceTask(
            task_id=task_id,
            client_address=client,
            worker_address=worker,
            amount_usd8=amount_usd8,
            deadline_ts=deadline,
            min_quality_bps=min_quality_bps,
            status="ACTIVE",
        )

    def compute_completion_digest(
        self,
        task_id: str,
        nonce: int,
        qag_score_bps: int,
        output_hash: str,
    ) -> str:
        """Compute keccak256 digest matching AevumAgentEscrow.completeTaskWithProof()."""
        raw = Web3.solidity_keccak(
            ["bytes32", "uint256", "uint256", "bytes32", "uint256", "address"],
            [
                to_bytes32(task_id),
                int(nonce),
                int(qag_score_bps),
                to_bytes32(output_hash),
                int(self.chain_id),
                self.escrow_address,
            ],
        )
        return "0x" + raw.hex()

    def sign_completion_proof(
        self,
        *,
        task_id: str,
        nonce: int,
        qag_score_bps: int,
        output_hash: str,
        private_oracle_key: str,
    ) -> CompletionProofSignature:
        """Sign completion proof digest via EIP-191 personal sign for on-chain ecrecover."""
        digest_hex = self.compute_completion_digest(
            task_id=task_id,
            nonce=nonce,
            qag_score_bps=qag_score_bps,
            output_hash=output_hash,
        )
        msg = encode_defunct(hexstr=digest_hex)
        signed = Account.sign_message(msg, private_key=private_oracle_key)
        signer = Account.from_key(private_oracle_key).address
        return CompletionProofSignature(
            digest_hex=digest_hex,
            v=int(signed.v),
            r_hex="0x" + int(signed.r).to_bytes(32, "big").hex(),
            s_hex="0x" + int(signed.s).to_bytes(32, "big").hex(),
            signer=signer,
        )

    def recover_completion_signer(self, sig: CompletionProofSignature) -> str:
        """Recover verifier oracle address from a CompletionProofSignature."""
        msg = encode_defunct(hexstr=sig.digest_hex)
        return Account.recover_message(msg, vrs=(sig.v, int(sig.r_hex, 16), int(sig.s_hex, 16)))

    def _build_web3(self, rpc_url: str | None = None) -> Web3:
        return Web3(
            Web3.HTTPProvider(
                rpc_url or self.rpc_url,
                request_kwargs={"timeout": DEFAULT_RPC_TIMEOUT_SECONDS},
            )
        )

    def confirm_payee_rpc(self, worker_address: str, rpc_url: str | None = None) -> PayeeConfirmation:
        """Query AevumAgentEscrow.confirmPayee(address) over JSON-RPC."""
        w3 = self._build_web3(rpc_url)
        payee = Web3.to_checksum_address(worker_address)
        contract = w3.eth.contract(address=self.escrow_address, abi=ESCROW_CONFIRM_PAYEE_ABI)
        verified, aid, endpoint, ema = _rpc_call_with_retry(
            lambda: contract.functions.confirmPayee(payee).call()
        )
        return PayeeConfirmation(
            payee=payee,
            verified=bool(verified),
            agent_id="0x" + bytes(aid).hex(),
            endpoint=str(endpoint),
            reputation_ema_bps=int(ema),
        )

    def check_registry_details_rpc(
        self,
        payee_address: str,
        registry_address: str = AEVUM_DEFAULT_REGISTRY_ADDRESS,
        rpc_url: str | None = None,
    ) -> Dict[str, Any]:
        """Query ERC8004AgentRegistry.verifyPayee(address) for metadata URI and evaluation count."""
        w3 = self._build_web3(rpc_url)
        payee = Web3.to_checksum_address(payee_address)
        reg = Web3.to_checksum_address(registry_address)
        contract = w3.eth.contract(address=reg, abi=ERC8004_VERIFY_PAYEE_ABI)
        verified, aid, endpoint, metadata_uri, ema, total_evals = _rpc_call_with_retry(
            lambda: contract.functions.verifyPayee(payee).call()
        )
        return {
            "verified": bool(verified),
            "agent_id": "0x" + bytes(aid).hex(),
            "endpoint": str(endpoint),
            "metadata_uri": str(metadata_uri),
            "reputation_ema_bps": int(ema),
            "total_evaluations": int(total_evals),
            "registry_address": reg,
        }

    def fetch_recent_events_rpc(
        self,
        from_block: int,
        to_block: int | None = None,
        rpc_url: str | None = None,
        chunk_size: int = AEVUM_MAX_LOG_RANGE,
        w3: Any | None = None,
    ) -> List[Dict[str, Any]]:
        """Read AevumAgentEscrow logs in <=1000-block chunks respecting Aevum RPC limits."""
        client_w3 = w3 or self._build_web3(rpc_url)
        bounded_chunk = max(1, min(int(chunk_size), AEVUM_MAX_LOG_RANGE))
        latest = int(to_block) if to_block is not None else int(
            _rpc_call_with_retry(lambda: client_w3.eth.block_number)
        )
        start = max(0, int(from_block))
        if start > latest:
            return []

        events: List[Dict[str, Any]] = []
        while start <= latest:
            end = min(start + bounded_chunk - 1, latest)
            logs = _rpc_call_with_retry(
                lambda s=start, e=end: client_w3.eth.get_logs(
                    {
                        "address": self.escrow_address,
                        "fromBlock": s,
                        "toBlock": e,
                    }
                )
            )
            for log in logs:
                topics = log.get("topics") or []
                topic0 = ""
                if topics:
                    t0 = topics[0]
                    topic0 = t0 if isinstance(t0, str) else ("0x" + bytes(t0).hex())
                    if not topic0.startswith("0x"):
                        topic0 = "0x" + topic0
                event_name = _ESCROW_EVENT_TOPICS.get(topic0.lower(), "EscrowEvent")
                tx_raw = log.get("transactionHash", b"")
                tx_hex = tx_raw if isinstance(tx_raw, str) else ("0x" + bytes(tx_raw).hex())
                if tx_hex and not tx_hex.startswith("0x"):
                    tx_hex = "0x" + tx_hex
                events.append(
                    {
                        "event": event_name,
                        "block_number": int(log.get("blockNumber", 0)),
                        "tx_hash": tx_hex,
                        "explorer_url": f"{AEVUM_EXPLORER_URL}/tx/{tx_hex}" if tx_hex else "",
                    }
                )
            start = end + 1
        return events

    def confirm_payee_local(
        self,
        worker_address: str,
        directory: Dict[str, Dict[str, Any]],
    ) -> PayeeConfirmation:
        """Resolve recipient address against a local Confirmation of Payee snapshot."""
        normalized = worker_address.lower()
        entry = next((v for k, v in directory.items() if k.lower() == normalized), None)
        if not entry or not entry.get("is_active", False):
            return PayeeConfirmation(
                payee=worker_address,
                verified=False,
                agent_id="0x" + ("00" * 32),
                endpoint="",
                reputation_ema_bps=0,
            )
        return PayeeConfirmation(
            payee=worker_address,
            verified=True,
            agent_id=str(entry.get("agent_id", "")),
            endpoint=str(entry.get("endpoint", "")),
            reputation_ema_bps=int(entry.get("reputation_ema_bps", 0)),
        )

    def generate_a2ui_escrow_card(self, task: CommerceTask) -> Dict[str, Any]:
        """Generates Google A2UI 1.0 declarative UI card for agent commerce escrow."""
        quality_pct = f"{task.min_quality_bps / 100:.2f}%"
        return {
            "surface_version": "1.0",
            "component": "Card",
            "props": {
                "title": f"Aevum Autonomous Agent Escrow: {task.task_id}",
                "status": task.status,
                "badge_color": "emerald" if task.status == "COMPLETED" else "amber",
            },
            "children": [
                {
                    "component": "MetricGrid",
                    "props": {
                        "columns": 3,
                        "metrics": [
                            {"label": "Escrow Amount", "value": f"${task.amount_usd8:,.2f} tUSD8"},
                            {"label": "Min QAG Quality", "value": quality_pct},
                            {"label": "Worker Agent", "value": f"{task.worker_address[:6]}...{task.worker_address[-4:]}"},
                        ],
                    },
                },
                {
                    "component": "ProgressBar",
                    "props": {
                        "progress": (task.evaluated_score or 0) / 100.0,
                        "label": f"Quality Score: {((task.evaluated_score or 0) / 100):.1f}%",
                    },
                },
                {
                    "component": "ActionButtons",
                    "props": {
                        "actions": [
                            {
                                "label": "Verify & Settle",
                                "action_type": "CONTRACT_CALL",
                                "target": self.escrow_address,
                                "method": "completeTaskWithProof",
                            },
                            {
                                "label": "Refund Escrow",
                                "action_type": "CONTRACT_CALL",
                                "target": self.escrow_address,
                                "method": "refundExpiredEscrow",
                                "disabled": task.status == "COMPLETED",
                            },
                        ]
                    },
                },
            ],
            "metadata": {
                "proof_hash": task.proof_hash,
                "contract": self.escrow_address,
                "chain_id": self.chain_id,
                "nonce": task.nonce,
                "timestamp": int(time.time()),
            },
        }

    def verify_and_settle_task(
        self,
        task: CommerceTask,
        deliverable_content: str,
        qag_score_bps: int,
        private_oracle_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Verify deliverable, generate completion digest/signature, and return receipt."""
        if task.status not in ("ACTIVE", "DELIVERED"):
            raise ValueError(f"Cannot settle task with status {task.status}")

        output_hash = "0x" + Web3.keccak(text=deliverable_content).hex()
        passed = qag_score_bps >= task.min_quality_bps

        task.evaluated_score = qag_score_bps
        task.proof_hash = output_hash
        task.status = "COMPLETED" if passed else "REJECTED_QUALITY"

        sig_payload: Optional[Dict[str, Any]] = None
        if private_oracle_key:
            sig = self.sign_completion_proof(
                task_id=task.task_id,
                nonce=task.nonce,
                qag_score_bps=qag_score_bps,
                output_hash=output_hash,
                private_oracle_key=private_oracle_key,
            )
            sig_payload = {
                "digest_hex": sig.digest_hex,
                "v": sig.v,
                "r_hex": sig.r_hex,
                "s_hex": sig.s_hex,
                "signer": sig.signer,
            }
            if passed:
                task.nonce += 1

        return {
            "taskId": task.task_id,
            "passed": passed,
            "qag_score_bps": qag_score_bps,
            "output_hash": task.proof_hash,
            "signature": sig_payload,
            "a2ui_card": self.generate_a2ui_escrow_card(task),
        }
