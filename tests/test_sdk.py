from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from typing import Any

from eth_account import Account
from web3 import Web3

from app.payee_ui import HTML_PAGE, SAMPLE_DIRECTORY, PayeeHandler, ThreadingHTTPServer, lookup_payee
from sdk.aevum_agent import (
    AEVUM_CHAIN_ID,
    AEVUM_EXPLORER_URL,
    AEVUM_MAX_LOG_RANGE,
    AEVUM_RPC_URL,
    AEVUM_TUSD8_ADDRESS,
    AevumAgentCommerce,
    match_expected_endpoint,
    to_bytes32,
)


TEST_ESCROW = "0x1234567890123456789012345678901234567890"
ORACLE_KEY = "0x" + "11" * 32


def test_aevum_sdk_lifecycle() -> None:
    client = AevumAgentCommerce(escrow_address=TEST_ESCROW, chain_id=31337)
    task = client.create_task_order(
        task_id="TASK-2026-TEST",
        client="0x0000000000000000000000000000000000000100",
        worker="0x0000000000000000000000000000000000000200",
        amount_usd8=250.0,
        min_quality_bps=8500,
    )
    assert task.status == "ACTIVE"
    assert task.amount_usd8 == 250.0

    res = client.verify_and_settle_task(
        task=task,
        deliverable_content="High precision agent output verified.",
        qag_score_bps=9150,
        private_oracle_key=ORACLE_KEY,
    )
    assert res["passed"] is True
    assert task.status == "COMPLETED"
    assert res["signature"] is not None
    assert res["a2ui_card"]["component"] == "Card"
    assert res["a2ui_card"]["props"]["status"] == "COMPLETED"


def test_aevum_sdk_subpar_quality_rejection() -> None:
    client = AevumAgentCommerce(escrow_address=TEST_ESCROW)
    task = client.create_task_order(
        task_id="TASK-2026-SUBPAR",
        client="0x0000000000000000000000000000000000000100",
        worker="0x0000000000000000000000000000000000000200",
        amount_usd8=100.0,
        min_quality_bps=8500,
    )
    res = client.verify_and_settle_task(
        task=task,
        deliverable_content="Subpar agent output.",
        qag_score_bps=7500,
    )
    assert res["passed"] is False
    assert task.status != "COMPLETED"


def test_aevum_solidity_digest_parity_and_signature_recovery() -> None:
    client = AevumAgentCommerce(escrow_address=TEST_ESCROW, chain_id=31337)
    out_hash = "0x" + Web3.keccak(text="DELIVERABLE").hex()
    expected = "0x" + Web3.solidity_keccak(
        ["bytes32", "uint256", "uint256", "bytes32", "uint256", "address"],
        [to_bytes32("TASK-PARITY"), 0, 9100, bytes.fromhex(out_hash[2:]), 31337, TEST_ESCROW],
    ).hex()

    sig = client.sign_completion_proof(
        task_id="TASK-PARITY",
        nonce=0,
        qag_score_bps=9100,
        output_hash=out_hash,
        private_oracle_key=ORACLE_KEY,
    )
    assert sig.digest_hex == expected
    assert client.recover_completion_signer(sig) == Account.from_key(ORACLE_KEY).address


def test_aevum_default_testnet_constants() -> None:
    client = AevumAgentCommerce(escrow_address=TEST_ESCROW)
    assert AEVUM_CHAIN_ID == 44005
    assert AEVUM_RPC_URL == "https://rpc-test.qday.info"
    assert AEVUM_EXPLORER_URL == "https://explorer-test.qday.info"
    assert AEVUM_TUSD8_ADDRESS == "0x456569838f1d43009A91ebA4263147Afd7233483"
    assert AEVUM_MAX_LOG_RANGE == 1000
    assert client.chain_id == 44005
    assert client.rpc_url == "https://rpc-test.qday.info"


def test_confirmation_of_payee_web_ui_roundtrip(monkeypatch: Any) -> None:
    monkeypatch.setenv("AEVUM_UI_MODE", "offline")
    monkeypatch.delenv("ESCROW_ADDRESS", raising=False)
    server = ThreadingHTTPServer(("127.0.0.1", 0), PayeeHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as resp:
            assert resp.status == 200
            html_text = resp.read().decode("utf-8")
            assert "Confirmation of Payee" in html_text

        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/confirm-payee",
            data=json.dumps({"payee": "0x0000000000000000000000000000000000000200"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            assert data["verified"] is True
            assert data["endpoint"] == "https://payee.example/v1"
    finally:
        server.shutdown()
        server.server_close()


def test_web_ui_xss_guard_and_health_activity_schema(monkeypatch: Any) -> None:
    monkeypatch.setenv("AEVUM_UI_MODE", "offline")
    monkeypatch.delenv("ESCROW_ADDRESS", raising=False)
    assert "innerHTML" not in HTML_PAGE

    server = ThreadingHTTPServer(("127.0.0.1", 0), PayeeHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=5) as resp:
            assert resp.status == 200
            health = json.loads(resp.read().decode("utf-8"))
            assert health["status"] == "ok"
            assert health["mode"] == "offline"
            assert health["chain_id"] == 44005
            assert health["max_task_tusd8"] == 1000.0

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/activity", timeout=5) as resp:
            assert resp.status == 200
            activity = json.loads(resp.read().decode("utf-8"))
            assert "deployment_transactions" in activity
            assert "settlement" in activity
            assert "revocation_demo" in activity
            assert "unverified_payee_guardrail" in activity
            assert activity["settlement"]["transactions"]["recordEvaluation"]["score_bps"] == 9200
    finally:
        server.shutdown()
        server.server_close()


def test_web_ui_input_validation_and_budget_cap(monkeypatch: Any) -> None:
    monkeypatch.setenv("AEVUM_UI_MODE", "offline")
    monkeypatch.delenv("ESCROW_ADDRESS", raising=False)
    server = ThreadingHTTPServer(("127.0.0.1", 0), PayeeHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        bad_payee_req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/confirm-payee",
            data=json.dumps({"payee": "not-an-address"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            urllib.request.urlopen(bad_payee_req, timeout=5)
            raise AssertionError("Expected HTTP 400 for malformed address")
        except urllib.error.HTTPError as exc:
            assert exc.code == 400

        cap_req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/prepare-escrow",
            data=json.dumps(
                {
                    "payee": "0x0000000000000000000000000000000000000200",
                    "amount_usd8": 1500.0,
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            urllib.request.urlopen(cap_req, timeout=5)
            raise AssertionError("Expected HTTP 400 when exceeding budget cap")
        except urllib.error.HTTPError as exc:
            assert exc.code == 400
    finally:
        server.shutdown()
        server.server_close()


def test_fetch_recent_events_chunk_splitting() -> None:
    recorded_ranges: list[tuple[int, int]] = []
    topic_completed = "0x" + Web3.keccak(
        text="TaskCompleted(bytes32,address,uint256,uint256,bytes32,uint256)"
    ).hex()

    class FakeEth:
        block_number = 2500

        def get_logs(self, flt: dict[str, Any]) -> list[dict[str, Any]]:
            from_blk = int(flt["fromBlock"])
            to_blk = int(flt["toBlock"])
            assert to_blk - from_blk + 1 <= AEVUM_MAX_LOG_RANGE
            recorded_ranges.append((from_blk, to_blk))
            if from_blk == 0:
                return [
                    {
                        "topics": [topic_completed],
                        "blockNumber": 42,
                        "transactionHash": b"\xab" * 32,
                    }
                ]
            return []

    class FakeW3:
        eth = FakeEth()

    client = AevumAgentCommerce(escrow_address=TEST_ESCROW)
    events = client.fetch_recent_events_rpc(from_block=0, to_block=2500, chunk_size=2500, w3=FakeW3())
    assert recorded_ranges == [(0, 999), (1000, 1999), (2000, 2500)]
    assert len(events) == 1
    assert events[0]["event"] == "TaskCompleted"
    assert events[0]["block_number"] == 42


def test_expected_endpoint_match_mismatch_and_unverified() -> None:
    client = AevumAgentCommerce(escrow_address=TEST_ESCROW, chain_id=31337)
    registered = "0x0000000000000000000000000000000000000200"
    conf = client.confirm_payee_local(registered, SAMPLE_DIRECTORY)
    assert conf.verified
    assert match_expected_endpoint(conf, conf.endpoint) == "match"
    assert match_expected_endpoint(conf, "HTTPS://" + conf.endpoint.split("//")[1].upper()) == "match"
    assert match_expected_endpoint(conf, "https://impostor.example/v1") == "mismatch"
    assert match_expected_endpoint(conf, "") == "mismatch"
    ghost = client.confirm_payee_local("0x000000000000000000000000000000000000dEaD", SAMPLE_DIRECTORY)
    assert match_expected_endpoint(ghost, conf.endpoint) == "unverified"


def test_lookup_payee_reports_endpoint_match(monkeypatch: Any) -> None:
    monkeypatch.setenv("AEVUM_UI_MODE", "offline")
    monkeypatch.delenv("ESCROW_ADDRESS", raising=False)
    addr = "0x0000000000000000000000000000000000000200"
    assert "endpoint_match" not in lookup_payee(addr)
    assert lookup_payee(addr, expected_endpoint="https://payee.example/v1")["endpoint_match"] == "match"
    assert lookup_payee(addr, expected_endpoint="https://other.example")["endpoint_match"] == "mismatch"
