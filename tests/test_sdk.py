import pytest
from sdk.aevum_agent import AevumAgentCommerce, CommerceTask


def test_aevum_sdk_lifecycle():
    client = AevumAgentCommerce(escrow_address="0x1234567890123456789012345678901234567890")
    task = client.create_task_order(
        task_id="TASK-2026-TEST",
        client="0xClient000000000000000000000000000000001",
        worker="0xWorker000000000000000000000000000000002",
        amount_usd8=250.0,
        min_quality_bps=8500,
    )
    assert task.status == "ACTIVE"
    assert task.amount_usd8 == 250.0

    # Test settlement with high quality
    res = client.verify_and_settle_task(
        task=task,
        deliverable_content="High precision agent output verified.",
        qag_score_bps=9150,
    )
    assert res["passed"] is True
    assert task.status == "COMPLETED"
    assert res["a2ui_card"]["component"] == "Card"
    assert res["a2ui_card"]["props"]["status"] == "COMPLETED"


def test_aevum_sdk_subpar_quality_rejection():
    client = AevumAgentCommerce(escrow_address="0x1234567890123456789012345678901234567890")
    task = client.create_task_order(
        task_id="TASK-2026-SUBPAR",
        client="0xClient000000000000000000000000000000001",
        worker="0xWorker000000000000000000000000000000002",
        amount_usd8=100.0,
        min_quality_bps=8500,
    )
    assert task.status == "ACTIVE"

    try:
        res = client.verify_and_settle_task(
            task=task,
            deliverable_content="Subpar agent output.",
            qag_score_bps=7500,
        )
    except Exception:
        # Rejection may be signaled by an exception; task must not be completed.
        assert task.status != "COMPLETED"
    else:
        assert "passed" in res
        assert res["passed"] is False
        assert task.status != "COMPLETED"


def test_aevum_sdk_expired_task_handling():
    client = AevumAgentCommerce(escrow_address="0x1234567890123456789012345678901234567890")
    task = client.create_task_order(
        task_id="TASK-2026-EXPIRED",
        client="0xClient000000000000000000000000000000001",
        worker="0xWorker000000000000000000000000000000002",
        amount_usd8=100.0,
        min_quality_bps=8000,
    )
    assert task.status == "ACTIVE"

    # Simulate the task moving to a non-active state (e.g., expired).
    task.status = "EXPIRED"

    try:
        res = client.verify_and_settle_task(
            task=task,
            deliverable_content="Attempted settlement after expiry.",
            qag_score_bps=9000,
        )
    except Exception:
        # Settlement on a non-active task may raise; status must stay non-active.
        assert task.status == "EXPIRED"
    else:
        assert "passed" in res
        assert res["passed"] is False
        assert task.status == "EXPIRED"
