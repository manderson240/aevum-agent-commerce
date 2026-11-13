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
