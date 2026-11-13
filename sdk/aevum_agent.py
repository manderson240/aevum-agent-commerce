"""Aevum Agent Commerce SDK.

Provides high-level interfaces for AI agents to negotiate tasks, deposit escrow in tUSD8,
and generate Google A2UI 1.0 transaction receipts.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional


@dataclass
class CommerceTask:
    task_id: str
    client_address: str
    worker_address: str
    amount_usd8: float
    deadline_ts: int
    min_quality_bps: int
    status: str = "PENDING"
    tx_hash: Optional[str] = None
    evaluated_score: Optional[int] = None
    proof_hash: Optional[str] = None


class AevumAgentCommerce:
    """Agent Commerce Client for Aevum testnet."""

    def __init__(self, escrow_address: str, rpc_url: str = "https://rpc-testnet.aevum.network") -> None:
        self.escrow_address = escrow_address
        self.rpc_url = rpc_url

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
        """Verifies deliverable and creates completion proof."""
        output_hash = hashlib.sha256(deliverable_content.encode("utf-8")).hexdigest()
        passed = qag_score_bps >= task.min_quality_bps

        task.evaluated_score = qag_score_bps
        task.proof_hash = "0x" + output_hash
        task.status = "COMPLETED" if passed else "REJECTED_QUALITY"

        return {
            "taskId": task.task_id,
            "passed": passed,
            "qag_score_bps": qag_score_bps,
            "output_hash": task.proof_hash,
            "a2ui_card": self.generate_a2ui_escrow_card(task),
        }
