#!/usr/bin/env python3
"""Interactive Confirmation of Payee and Quality-Gated tUSD8 Escrow Web UI.

Serves a self-contained web UI on port 8784 for ERC-8004 Confirmation of Payee,
reputation verification, budget-capped escrow preparation, and live Aevum Chain
44005 receipt inspection.
"""

from __future__ import annotations

import argparse
import html
import json
import math
import os
from dataclasses import asdict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from web3 import Web3

from sdk.aevum_agent import (
    AEVUM_CHAIN_ID,
    AEVUM_DEFAULT_ESCROW_ADDRESS,
    AEVUM_DEFAULT_REGISTRY_ADDRESS,
    AEVUM_DEFAULT_VERIFIED_PAYEE,
    AEVUM_EXPLORER_URL,
    AEVUM_TUSD8_ADDRESS,
    AEVUM_RPC_URL,
    AevumAgentCommerce,
    match_expected_endpoint,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

SAMPLE_DIRECTORY: dict[str, dict[str, Any]] = {
    "0x0000000000000000000000000000000000000200": {
        "agent_id": "0x" + "1a" * 32,
        "endpoint": "https://payee.example/v1",
        "reputation_ema_bps": 9150,
        "is_active": True,
    },
    "0x70997970C51812dc3A010C7D01b50e0d17dc79C8": {
        "agent_id": "0x" + "2b" * 32,
        "endpoint": "https://auditor.example/v1",
        "reputation_ema_bps": 8840,
        "is_active": True,
    },
}


def get_max_task_tusd8() -> float:
    raw = os.getenv("MAX_TASK_TUSD8", "1000.0").strip()
    try:
        cap = float(raw or "1000.0")
    except ValueError:
        cap = 1000.0
    return cap if math.isfinite(cap) and cap > 0 else 1000.0


def _resolve_live_mode() -> bool:
    mode = os.getenv("AEVUM_UI_MODE", "").strip().lower()
    if mode == "offline":
        return False
    if mode == "live":
        return True
    return bool(os.getenv("ESCROW_ADDRESS", "").strip())


def _get_registry_address() -> str:
    raw = os.getenv("ERC8004_REGISTRY_ADDRESS", "").strip()
    if raw and Web3.is_address(raw):
        return Web3.to_checksum_address(raw)
    return AEVUM_DEFAULT_REGISTRY_ADDRESS


def build_client() -> tuple[AevumAgentCommerce, bool]:
    live_rpc = _resolve_live_mode()
    escrow_addr = os.getenv("ESCROW_ADDRESS", "").strip()
    rpc_url = os.getenv("AEVUM_RPC_URL", AEVUM_RPC_URL).strip() or AEVUM_RPC_URL
    chain_id = int(os.getenv("AEVUM_CHAIN_ID", str(AEVUM_CHAIN_ID)) or str(AEVUM_CHAIN_ID))
    if escrow_addr:
        effective_addr = escrow_addr
    elif live_rpc:
        effective_addr = AEVUM_DEFAULT_ESCROW_ADDRESS
    else:
        effective_addr = "0x1234567890123456789012345678901234567890"
    return AevumAgentCommerce(escrow_address=effective_addr, rpc_url=rpc_url, chain_id=chain_id), live_rpc


def lookup_payee(
    payee: str,
    client: AevumAgentCommerce | None = None,
    use_rpc: bool = False,
    expected_endpoint: str = "",
) -> dict[str, Any]:
    if not payee or not Web3.is_address(payee):
        raise ValueError("Invalid EVM payee address")
    sdk, rpc_configured = build_client()
    active_sdk = client or sdk
    registry_addr = _get_registry_address()
    extra: dict[str, Any] = {}
    if use_rpc or (client is None and rpc_configured):
        conf = active_sdk.confirm_payee_rpc(payee)
        source = "rpc"
        try:
            reg_info = active_sdk.check_registry_details_rpc(payee, registry_address=registry_addr)
            extra["total_evaluations"] = reg_info["total_evaluations"]
            extra["metadata_uri"] = reg_info["metadata_uri"]
        except Exception:
            pass
    else:
        conf = active_sdk.confirm_payee_local(payee, SAMPLE_DIRECTORY)
        source = "local-directory"
    out = asdict(conf)
    out.update(extra)
    out["source"] = source
    out["escrow_address"] = active_sdk.escrow_address
    out["registry_address"] = registry_addr
    out["chain_id"] = active_sdk.chain_id
    if expected_endpoint:
        out["endpoint_match"] = match_expected_endpoint(conf, expected_endpoint)
    return out


def _read_deployment_record() -> dict[str, Any]:
    path = REPO_ROOT / "docs" / "aevum_testnet_deployment.json"
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def load_activity_payload(
    sdk: AevumAgentCommerce,
    live_rpc: bool,
    fetch_live_logs: bool = False,
) -> dict[str, Any]:
    dep = _read_deployment_record()
    live_events: list[dict[str, Any]] = []
    if live_rpc and fetch_live_logs:
        try:
            w3 = sdk._build_web3()
            latest = int(w3.eth.block_number)
            from_block = max(0, latest - 1500)
            live_events = sdk.fetch_recent_events_rpc(from_block=from_block, to_block=latest, w3=w3)
        except Exception:
            live_events = []

    contracts = dep.get(
        "contracts",
        {
            "tUSD8": AEVUM_TUSD8_ADDRESS,
            "erc8004_registry": _get_registry_address(),
            "aevum_agent_escrow": sdk.escrow_address,
        },
    )
    return {
        "mode": "live" if live_rpc else "offline",
        "network": dep.get("network", "QDay Aevum Testnet"),
        "chain_id": sdk.chain_id,
        "explorer_url": dep.get("explorer_url", AEVUM_EXPLORER_URL),
        "contracts": contracts,
        "deployed_source_commits": dep.get("deployed_source_commits", {}),
        "deployment_transactions": dep.get("deployment_transactions", {}),
        "confirm_payee": dep.get("confirm_payee", {}),
        "settlement": {
            "task_id": dep.get("task_id"),
            "amount_tusd8": dep.get("amount_tusd8"),
            "transactions": dep.get("transactions", {}),
        },
        "revocation_demo": dep.get("revocation_demo", {}),
        "unverified_payee_guardrail": dep.get("unverified_payee_guardrail", {}),
        "live_events": live_events,
    }


def _safe_explorer_href(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme == "https" and parsed.netloc == "explorer-test.qday.info":
        return html.escape(url, quote=True)
    return html.escape(AEVUM_EXPLORER_URL, quote=True)


def build_html_page(
    *,
    live_mode: bool | None = None,
    escrow_addr: str | None = None,
    registry_addr: str | None = None,
) -> str:
    is_live = _resolve_live_mode() if live_mode is None else live_mode
    escrow_val = html.escape(
        escrow_addr or (AEVUM_DEFAULT_ESCROW_ADDRESS if is_live else "0x1234567890123456789012345678901234567890")
    )
    registry_val = html.escape(registry_addr or _get_registry_address())
    default_payee = AEVUM_DEFAULT_VERIFIED_PAYEE if is_live else "0x0000000000000000000000000000000000000200"
    mode_label = "LIVE: QDay Aevum Chain 44005" if is_live else "OFFLINE: Local Sample Directory"
    mode_class = "pill-live" if is_live else "pill-off"
    cap_val = f"{get_max_task_tusd8():.0f}"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Aevum Confirmation of Payee &amp; Escrow Console</title>
<style>
  body {{ font-family: Arial, sans-serif; background: #0b1020; color: #e2e8f0; margin: 0; padding: 28px 16px; }}
  .wrap {{ max-width: 900px; margin: 0 auto; background: #131a2f; border: 1px solid #26314f; border-radius: 12px; padding: 26px; }}
  .header {{ display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 10px; }}
  h1 {{ margin: 0; color: #f8fafc; font-size: 22px; }}
  .pill {{ padding: 5px 11px; border-radius: 999px; font-size: 12px; font-weight: 700; font-family: monospace; }}
  .pill-live {{ background: #064e3b; color: #6ee7b7; border: 1px solid #10b981; }}
  .pill-off {{ background: #334155; color: #cbd5e1; border: 1px solid #64748b; }}
  p {{ color: #94a3b8; line-height: 1.5; margin: 10px 0 14px; }}
  .meta-bar {{ display: flex; flex-wrap: wrap; gap: 14px; font-size: 12px; color: #94a3b8; background: #0b1020; border: 1px solid #1e293b; border-radius: 8px; padding: 10px 12px; margin-bottom: 14px; }}
  .meta-bar a {{ color: #38bdf8; text-decoration: none; font-family: monospace; }}
  .meta-bar a:hover {{ text-decoration: underline; }}
  label {{ display: block; margin-top: 14px; font-weight: 600; font-size: 13px; color: #cbd5e1; }}
  input {{ width: 100%; padding: 10px 12px; border-radius: 8px; border: 1px solid #334155; background: #0b1020; color: #f8fafc; font-family: monospace; box-sizing: border-box; margin-top: 6px; }}
  .row {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 14px; }}
  .presets {{ display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; }}
  button {{ margin-top: 16px; padding: 10px 16px; border: 0; border-radius: 8px; background: #0ea5e9; color: #061224; font-weight: 700; cursor: pointer; margin-right: 8px; font-size: 13px; }}
  button.secondary {{ background: #22c55e; }}
  button.ghost {{ background: #1e293b; color: #cbd5e1; margin-top: 0; padding: 6px 10px; font-size: 12px; border: 1px solid #334155; }}
  button.ghost-warn {{ background: #2a161b; color: #fca5a5; margin-top: 0; padding: 6px 10px; font-size: 12px; border: 1px solid #7f1d1d; }}
  pre {{ margin-top: 14px; background: #070b16; border: 1px solid #1e293b; border-radius: 8px; padding: 14px; overflow-x: auto; font-size: 12px; color: #cbd5e1; }}
  .badge-ok {{ color: #22c55e; font-weight: 700; }}
  .badge-bad {{ color: #f87171; font-weight: 700; }}
  h2 {{ margin: 24px 0 10px; font-size: 16px; color: #f8fafc; border-top: 1px solid #26314f; padding-top: 18px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 12px; background: #0b1020; border: 1px solid #1e293b; border-radius: 8px; overflow: hidden; }}
  th, td {{ text-align: left; padding: 8px 10px; border-bottom: 1px solid #1e293b; }}
  th {{ color: #94a3b8; font-weight: 600; }}
  td a {{ color: #38bdf8; font-family: monospace; text-decoration: none; }}
  td a:hover {{ text-decoration: underline; }}
</style>
</head>
<body>
  <div class="wrap">
    <div class="header">
      <h1>Aevum Confirmation of Payee &amp; tUSD8 Escrow Console</h1>
      <span id="modeBadge" class="pill {mode_class}">{mode_label}</span>
    </div>
    <p>Pre-flight recipient identity check backed by ERC-8004 lookup before locking or settling tUSD8 escrow (per-task budget cap: {cap_val} tUSD8).</p>

    <div class="meta-bar">
      <span>Escrow: <a href="{_safe_explorer_href(f'{AEVUM_EXPLORER_URL}/address/{escrow_val}')}" target="_blank" rel="noopener noreferrer">{escrow_val}</a></span>
      <span>ERC-8004 Registry: <a href="{_safe_explorer_href(f'{AEVUM_EXPLORER_URL}/address/{registry_val}')}" target="_blank" rel="noopener noreferrer">{registry_val}</a></span>
      <span>tUSD8: <a href="{_safe_explorer_href(f'{AEVUM_EXPLORER_URL}/address/{AEVUM_TUSD8_ADDRESS}')}" target="_blank" rel="noopener noreferrer">{AEVUM_TUSD8_ADDRESS}</a></span>
    </div>

    <label for="payee">Recipient Wallet Address</label>
    <input id="payee" value="{default_payee}" />
    <div class="presets">
      <button type="button" class="ghost" onclick="setPayee('{AEVUM_DEFAULT_VERIFIED_PAYEE}')">Verified Live Payee (Chain 44005)</button>
      <button type="button" class="ghost" onclick="setPayee('0x0000000000000000000000000000000000000200')">Offline Sample Payee</button>
      <button type="button" class="ghost-warn" onclick="setPayee('0x000000000000000000000000000000000000dEaD')">Unverified Guardrail Test (0x...dEaD)</button>
    </div>

    <div class="row">
      <div>
        <label for="taskId">Task ID</label>
        <input id="taskId" value="TASK-AEVUM-COH-01" />
      </div>
      <div>
        <label for="amount">Amount (tUSD8, max {cap_val})</label>
        <input id="amount" value="25.0" />
      </div>
    </div>

    <div class="row">
      <div>
        <label for="score">Evaluated Quality Score (bps)</label>
        <input id="score" value="9200" />
      </div>
      <div>
        <label for="deliverable">Deliverable Payload</label>
        <input id="deliverable" value="Verified audit bundle sha256 ok" />
      </div>
    </div>

    <button onclick="confirmPayee()">1. Confirm Payee (ERC-8004)</button>
    <button class="secondary" onclick="prepareEscrow()">2. Prepare Escrow &amp; Proof</button>

    <div id="status" style="margin-top:16px;"></div>
    <pre id="output">{{}}</pre>

    <h2>Verified Chain 44005 On-Chain Receipts</h2>
    <table>
      <thead>
        <tr>
          <th>Stage / Operation</th>
          <th>Block / Status</th>
          <th>Transaction / Detail</th>
        </tr>
      </thead>
      <tbody id="activityBody">
        <tr><td colspan="3">Loading Chain 44005 activity...</td></tr>
      </tbody>
    </table>
  </div>
<script>
const EXPLORER_PREFIX = 'https://explorer-test.qday.info/';

function setPayee(addr) {{
  document.getElementById('payee').value = addr;
  confirmPayee();
}}

function renderStatus(text, ok) {{
  const statusEl = document.getElementById('status');
  const badge = document.createElement('span');
  badge.className = ok ? 'badge-ok' : 'badge-bad';
  badge.textContent = text;
  statusEl.replaceChildren(badge);
}}

async function confirmPayee() {{
  const res = await fetch('/api/confirm-payee', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{ payee: document.getElementById('payee').value }})
  }});
  const data = await res.json();
  if (!res.ok) {{
    renderStatus('ERROR: ' + (data.error || 'Request rejected'), false);
    document.getElementById('output').textContent = JSON.stringify(data, null, 2);
    return;
  }}
  const pct = (Number(data.reputation_ema_bps || 0) / 100).toFixed(2);
  const evalLabel = data.total_evaluations !== undefined ? (', evals ' + data.total_evaluations) : '';
  if (data.verified) {{
    renderStatus('VERIFIED PAYEE: ' + data.endpoint + ' (EMA ' + pct + '%' + evalLabel + ', source: ' + data.source + ')', true);
  }} else {{
    renderStatus('UNVERIFIED ADDRESS: transfer guard blocks payment (source: ' + data.source + ')', false);
  }}
  document.getElementById('output').textContent = JSON.stringify(data, null, 2);
}}

async function prepareEscrow() {{
  const res = await fetch('/api/prepare-escrow', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{
      payee: document.getElementById('payee').value,
      task_id: document.getElementById('taskId').value,
      amount_usd8: parseFloat(document.getElementById('amount').value),
      qag_score_bps: parseInt(document.getElementById('score').value, 10),
      deliverable: document.getElementById('deliverable').value
    }})
  }});
  const data = await res.json();
  if (!res.ok) {{
    renderStatus('BLOCKED: ' + (data.error || 'Escrow preparation rejected'), false);
  }} else {{
    renderStatus('READY TO SETTLE: EIP-191 completion proof signed (' + data.settlement.taskId + ')', true);
  }}
  document.getElementById('output').textContent = JSON.stringify(data, null, 2);
}}

function appendActivityRow(tbody, stage, detail, txHash, url) {{
  const tr = document.createElement('tr');
  const tdStage = document.createElement('td');
  tdStage.textContent = stage;
  const tdDetail = document.createElement('td');
  tdDetail.textContent = detail;
  const tdTx = document.createElement('td');
  if (txHash && url && url.startsWith(EXPLORER_PREFIX)) {{
    const a = document.createElement('a');
    a.href = url;
    a.target = '_blank';
    a.rel = 'noopener noreferrer';
    a.textContent = txHash.slice(0, 14) + '...' + txHash.slice(-6);
    tdTx.appendChild(a);
  }} else {{
    tdTx.textContent = txHash || '-';
  }}
  tr.appendChild(tdStage);
  tr.appendChild(tdDetail);
  tr.appendChild(tdTx);
  tbody.appendChild(tr);
}}

async function loadActivity() {{
  try {{
    const res = await fetch('/api/activity');
    const data = await res.json();
    const tbody = document.getElementById('activityBody');
    const rows = document.createDocumentFragment();
    const deps = data.deployment_transactions || {{}};
    if (deps.erc8004_registry_create) {{
      appendActivityRow(rows, 'Deploy ERC8004AgentRegistry', 'Chain 44005', deps.erc8004_registry_create.tx_hash, deps.erc8004_registry_create.explorer_url);
    }}
    if (deps.aevum_escrow_create) {{
      appendActivityRow(rows, 'Deploy AevumAgentEscrow', 'Chain 44005', deps.aevum_escrow_create.tx_hash, deps.aevum_escrow_create.explorer_url);
    }}
    const txs = (data.settlement && data.settlement.transactions) || {{}};
    Object.keys(txs).forEach((name) => {{
      const entry = txs[name];
      if (entry && entry.tx_hash) {{
        appendActivityRow(rows, name, 'Block ' + entry.block_number, entry.tx_hash, entry.explorer_url);
      }}
    }});
    const revTxs = (data.revocation_demo && data.revocation_demo.transactions) || {{}};
    if (revTxs.cancelTask) {{
      appendActivityRow(rows, 'cancelTask (0.50 tUSD8 refund)', 'Block ' + revTxs.cancelTask.block_number, revTxs.cancelTask.tx_hash, revTxs.cancelTask.explorer_url);
    }}
    const guard = data.unverified_payee_guardrail || {{}};
    if (guard.blocked) {{
      appendActivityRow(rows, 'Guardrail: ' + (guard.target_address || '0x...dEaD'), 'Blocked on-chain', guard.revert_reason || 'Reverted', '');
    }}
    tbody.replaceChildren(rows);
  }} catch (err) {{
    const tbody = document.getElementById('activityBody');
    const tr = document.createElement('tr');
    const td = document.createElement('td');
    td.colSpan = 3;
    td.textContent = 'Activity unavailable';
    tr.appendChild(td);
    tbody.replaceChildren(tr);
  }}
}}

window.addEventListener('DOMContentLoaded', () => {{
  loadActivity();
}});
</script>
</body>
</html>
"""


HTML_PAGE = build_html_page(live_mode=False)


class PayeeHandler(BaseHTTPRequestHandler):
    """HTTP handler for the Aevum Confirmation of Payee console."""

    def _send_json(self, code: int, payload: dict[str, Any]) -> None:
        raw = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        sdk, live_rpc = build_client()
        if parsed.path in ("/", "/index.html"):
            page = build_html_page(
                live_mode=live_rpc,
                escrow_addr=sdk.escrow_address,
                registry_addr=_get_registry_address(),
            )
            raw = page.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        if parsed.path == "/health":
            self._send_json(
                HTTPStatus.OK,
                {
                    "status": "ok",
                    "mode": "live" if live_rpc else "offline",
                    "chain_id": sdk.chain_id,
                    "escrow_address": sdk.escrow_address,
                    "registry_address": _get_registry_address(),
                    "max_task_tusd8": get_max_task_tusd8(),
                },
            )
            return
        if parsed.path == "/api/activity":
            fetch_logs = "live_logs=1" in parsed.query or live_rpc
            self._send_json(
                HTTPStatus.OK,
                load_activity_payload(sdk=sdk, live_rpc=live_rpc, fetch_live_logs=fetch_logs),
            )
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})

    def do_POST(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw_body = self.rfile.read(length).decode("utf-8")
            body = json.loads(raw_body or "{}")
            if not isinstance(body, dict):
                raise ValueError("JSON body must be an object")
        except (ValueError, UnicodeDecodeError) as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": f"Invalid JSON request: {exc}"})
            return

        if self.path == "/api/confirm-payee":
            payee = str(body.get("payee", "")).strip()
            if not payee or not Web3.is_address(payee):
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": "Invalid EVM payee address"})
                return
            try:
                self._send_json(HTTPStatus.OK, lookup_payee(payee, expected_endpoint=str(body.get("expected_endpoint", ""))))
            except ValueError as exc:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            except Exception as exc:
                self._send_json(HTTPStatus.BAD_GATEWAY, {"error": f"RPC lookup failed: {exc}"})
            return

        if self.path == "/api/prepare-escrow":
            payee = str(body.get("payee", "")).strip()
            client_addr = str(body.get("client", "0x0000000000000000000000000000000000000100")).strip()
            if not payee or not Web3.is_address(payee):
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": "Invalid EVM payee address"})
                return
            if not client_addr or not Web3.is_address(client_addr):
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": "Invalid EVM client address"})
                return

            max_cap = get_max_task_tusd8()
            try:
                amount_usd8 = float(body.get("amount_usd8", 25.0))
            except (TypeError, ValueError):
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": "amount_usd8 must be a finite number"})
                return
            if not math.isfinite(amount_usd8) or amount_usd8 <= 0 or amount_usd8 > max_cap:
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {"error": f"amount_usd8 must be > 0 and <= {max_cap:.2f}"},
                )
                return

            try:
                qag_score_bps = int(body.get("qag_score_bps", 9200))
                min_quality_bps = int(body.get("min_quality_bps", 8500))
            except (TypeError, ValueError):
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": "Quality scores must be integers"})
                return
            if not (0 <= qag_score_bps <= 10000) or not (0 <= min_quality_bps <= 10000):
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": "Quality scores must be between 0 and 10000"})
                return

            try:
                payee_info = lookup_payee(payee)
            except ValueError as exc:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return
            except Exception as exc:
                self._send_json(HTTPStatus.BAD_GATEWAY, {"error": f"RPC lookup failed: {exc}"})
                return

            if not payee_info["verified"]:
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {"error": "Payee failed ERC-8004 Confirmation of Payee check", "payee": payee_info},
                )
                return

            sdk, _ = build_client()
            task = sdk.create_task_order(
                task_id=str(body.get("task_id", "TASK-AEVUM-COH-01")),
                client=client_addr,
                worker=payee,
                amount_usd8=amount_usd8,
                min_quality_bps=min_quality_bps,
            )
            demo_oracle_key = os.getenv("DEMO_ORACLE_PRIVATE_KEY", "0x" + "11" * 32)
            settlement = sdk.verify_and_settle_task(
                task=task,
                deliverable_content=str(body.get("deliverable", "Verified deliverable")),
                qag_score_bps=qag_score_bps,
                private_oracle_key=demo_oracle_key,
            )
            self._send_json(
                HTTPStatus.OK,
                {
                    "payee": payee_info,
                    "settlement": settlement,
                    "budget_cap_tusd8": max_cap,
                },
            )
            return

        self._send_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})

    def log_message(self, format: str, *args: object) -> None:
        return


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Aevum Confirmation of Payee UI server.")
    parser.add_argument("--offline", action="store_true", help="Use local sample directory without live RPC")
    parser.add_argument("--host", default="", help="Bind host (defaults to HOST env or 127.0.0.1)")
    parser.add_argument("--port", type=int, default=0, help="Bind port (defaults to PORT env or 8784)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    if args.offline:
        os.environ["AEVUM_UI_MODE"] = "offline"
    else:
        os.environ.setdefault("AEVUM_UI_MODE", "live")
    host = args.host or os.getenv("HOST", "127.0.0.1")
    port = args.port or int(os.getenv("PORT", "8784"))
    server = ThreadingHTTPServer((host, port), PayeeHandler)
    print(f"Aevum Confirmation of Payee UI listening on http://{host}:{port} (mode={os.environ['AEVUM_UI_MODE']})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
