#!/usr/bin/env python3
"""Automated 2560x1440 (2K QHD) 6-Scene Code Walkthrough & Pitch Video Generator
for Aevum Agent Commerce Protocol (Aevum Builder Challenge #1).
"""

from __future__ import annotations

import html
import json
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from PIL import Image


WIDTH = 2560
HEIGHT = 1440
CHROME_CAPTURE_HEIGHT = 1527
REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_slice(rel_path: str, start_line: int, end_line: int) -> str:
    """Load exact verbatim source lines (zero ellipses) and HTML-escape safely."""
    lines = (REPO_ROOT / rel_path).read_text(encoding="utf-8").splitlines()
    return html.escape("\n".join(lines[start_line - 1 : end_line]))


ESCROW_PART1 = _load_slice("src/AevumAgentEscrow.sol", 65, 122)
ESCROW_PART2 = _load_slice("src/AevumAgentEscrow.sol", 123, 195)
SDK_CODE = _load_slice("sdk/aevum_agent.py", 15, 76)

SCENES = [
    {
        "id": "scene0_title_hero",
        "narration": (
            "Aevum Agent Commerce. I built a quality-gated escrow contract for payments between AI agents in tUSD8, "
            "for the Aevum Builder Challenge Number One. "
            "The worker is paid only when the task's score meets its threshold and the score is signed by the verifier oracle key. "
            "If that never happens, the client can take the funds back after the deadline. "
            "There are six Foundry tests, including a fuzz test, and three Python tests."
        ),
        "html_body": """
            <div class="header" style="text-align:center;margin-top:12px;margin-bottom:24px;">
                <span class="badge" style="font-size:20px;padding:8px 26px;">Aevum Builder Challenge #1</span>
                <h1 style="font-size:64px;margin-top:14px;margin-bottom:10px;letter-spacing:-2px;">Aevum Agent Commerce</h1>
                <p class="subtitle" style="font-size:26px;margin:0 auto;max-width:1950px;color:#38bdf8;font-weight:500;">
                    A quality-gated tUSD8 escrow contract and a small Python helper
                </p>
            </div>
            <div class="grid-4" style="margin-top:20px;margin-bottom:20px;">
                <div class="card" style="text-align:center;border-color:rgba(56,189,248,0.4);background:rgba(56,189,248,0.08);">
                    <h3 style="font-size:30px;color:#38bdf8;">Lock</h3>
                    <p style="font-size:18px;color:#cbd5e1;">createTaskEscrow pulls tUSD8 from the client and marks the task ACTIVE</p>
                </div>
                <div class="card" style="text-align:center;border-color:rgba(34,197,94,0.4);background:rgba(34,197,94,0.08);">
                    <h3 style="font-size:30px;color:#22c55e;">Score gate</h3>
                    <p style="font-size:18px;color:#cbd5e1;">completeTaskWithProof reverts if qagScore &lt; minQualityBps</p>
                </div>
                <div class="card" style="text-align:center;border-color:rgba(192,132,252,0.4);background:rgba(192,132,252,0.08);">
                    <h3 style="font-size:30px;color:#c084fc;">Oracle signature</h3>
                    <p style="font-size:18px;color:#cbd5e1;">ecrecover must return the oracle address set in the constructor</p>
                </div>
                <div class="card" style="text-align:center;border-color:rgba(245,158,11,0.4);background:rgba(245,158,11,0.08);">
                    <h3 style="font-size:30px;color:#f59e0b;">Refund</h3>
                    <p style="font-size:18px;color:#cbd5e1;">refundExpiredEscrow returns the funds to the client after the deadline</p>
                </div>
            </div>
            <div class="flow-container" style="margin-top:16px;">
                <div class="chip chip-green" style="font-size:17px;padding:10px 20px;">MockUSD8 (tUSD8 stand-in)</div>
                <div class="chip chip-blue" style="font-size:17px;padding:10px 20px;">Foundry 6/6 (256 fuzz runs)</div>
                <div class="chip chip-green" style="font-size:17px;padding:10px 20px;">Pytest 3/3</div>
                <div class="chip chip-blue" style="font-size:17px;padding:10px 20px;">1-Command: forge test &amp;&amp; uv run pytest</div>
            </div>
        """,
    },
    {
        "id": "scene1_problem_workflow",
        "narration": (
            "How the escrow works. "
            "If a client agent pays up front, it loses the money when the output is bad. "
            "If it pays afterwards, the worker can go unpaid. "
            "Step one: the client locks tUSD8 in AevumAgentEscrow with a minimum quality threshold in basis points and a deadline. "
            "Step two: someone submits the score and output hash with a signature from the oracle key. "
            "Step three: the contract pays the worker only if the score meets the threshold and the signature checks out. "
            "Otherwise the call reverts, and the client can refund after the deadline."
        ),
        "html_body": """
            <div class="header">
                <span class="badge">Architecture</span>
                <h1>Quality-Gated tUSD8 Settlement</h1>
                <p class="subtitle">The three steps the contract enforces.</p>
            </div>
            <div class="flow-container" style="margin-top:24px;">
                <div class="flow-step">
                    <div class="flow-num">01</div>
                    <h4>Lock tUSD8 Escrow</h4>
                    <p>Client calls createTaskEscrow with worker address, deadline, and minQualityBps (e.g. 8500).</p>
                    <div class="chip">IERC20 transferFrom</div>
                </div>
                <div class="flow-arrow">➔</div>
                <div class="flow-step highlight">
                    <div class="flow-num">02</div>
                    <h4>Signed Score</h4>
                    <p>Contract checks qagScore &gt;= minQualityBps and that ecrecover over (taskId, qagScore, outputHash, contract) is the oracle.</p>
                    <div class="chip chip-blue">e.g. 8500 bps threshold</div>
                </div>
                <div class="flow-arrow">➔</div>
                <div class="flow-step">
                    <div class="flow-num">03</div>
                    <h4>Settle or Refund</h4>
                    <p>Releases tUSD8 to the worker, or returns it to the client via refundExpiredEscrow after the deadline.</p>
                    <div class="chip chip-green">One exit per task</div>
                </div>
            </div>
            <div class="grid-2" style="margin-top:24px;">
                <div class="card">
                    <h3>What the contract does</h3>
                    <ul>
                        <li><strong>Score gate:</strong> reverts when qagScore &lt; minQualityBps</li>
                        <li><strong>Refund:</strong> anyone can trigger the client refund once the deadline has passed</li>
                        <li><strong>Lock:</strong> <code>nonReentrant</code> on all four functions; status changes before each transfer</li>
                        <li><strong>Digest:</strong> the signed hash includes <code>taskId</code> and <code>address(this)</code></li>
                    </ul>
                </div>
                <div class="card danger">
                    <h3>What it does not do</h3>
                    <ul>
                        <li><strong>No oracle service:</strong> the tests sign scores with a fixed test key</li>
                        <li><strong>No nonce or chain ID</strong> in the signed digest</li>
                        <li><strong>Cancel:</strong> client or worker can cancel an ACTIVE task alone</li>
                        <li><strong>Not deployed:</strong> no testnet address in the repo</li>
                    </ul>
                </div>
            </div>
        """,
    },
    {
        "id": "scene2_core_source_code",
        "narration": (
            "Here is the contract in src/AevumAgentEscrow.sol, lines sixty-five through one hundred ninety-five. "
            "On the left, createTaskEscrow checks for a new task ID, a non-zero worker, a positive amount, a future deadline, and a threshold of at most ten thousand basis points. "
            "On the right, completeTaskWithProof checks the score against the threshold and recovers the signer of the digest over taskId, qagScore, outputHash, and the contract address. "
            "Below it are refundExpiredEscrow and cancelTask."
        ),
        "html_body": f"""
            <div class="header">
                <span class="badge">Code Walkthrough: Solidity</span>
                <h1>AevumAgentEscrow.sol</h1>
                <p class="subtitle">Source from <code>src/AevumAgentEscrow.sol</code>, lines 65 to 195.</p>
            </div>
            <div class="code-grid-2">
                <div class="code-box">
                    <div class="linux-bar">
                        <span class="linux-tab">src/AevumAgentEscrow.sol (Lines 65 to 122)</span>
                        <div class="linux-controls"><span>_</span><span>□</span><span>✕</span></div>
                    </div>
                    <pre style="font-size:13.2px;line-height:1.25;">{ESCROW_PART1}</pre>
                    <div class="eval-flow">
                        <span class="flow-pill pass">[OK] nonReentrant lock</span>
                        <span class="flow-pill pass">[OK] Deadline and bps bounds</span>
                    </div>
                </div>
                <div class="code-box">
                    <div class="linux-bar">
                        <span class="linux-tab">src/AevumAgentEscrow.sol (Lines 123 to 195)</span>
                        <div class="linux-controls"><span>_</span><span>□</span><span>✕</span></div>
                    </div>
                    <pre style="font-size:12.6px;line-height:1.22;">{ESCROW_PART2}</pre>
                    <div class="eval-flow">
                        <span class="flow-pill pass">[OK] ecrecover == verifierOracle</span>
                        <span class="flow-pill pass">[OK] Refund after deadline</span>
                    </div>
                </div>
            </div>
        """,
    },
    {
        "id": "scene3_verifier_source_code",
        "narration": (
            "Next to the contract is a small Python helper in sdk/aevum_agent.py. "
            "CommerceTask holds the amount, deadline, quality threshold, status, and deliverable hash. "
            "AevumAgentCommerce creates task records, applies the same score threshold in memory, "
            "and builds a JSON dict shaped like a Google A2UI card that shows the worker address, the score, and the two contract calls. "
            "The helper does not talk to a chain."
        ),
        "html_body": f"""
            <div class="header">
                <span class="badge">Code Walkthrough: Python helper</span>
                <h1>Off-Chain Helper: aevum_agent.py</h1>
                <p class="subtitle">The task dataclass and card builder from <code>sdk/aevum_agent.py</code>, lines 15 to 76.</p>
            </div>
            <div class="grid-2" style="gap:28px;height:980px;">
                <div class="code-box">
                    <div class="linux-bar">
                        <span class="linux-tab">sdk/aevum_agent.py (Lines 15 to 76)</span>
                        <div class="linux-controls"><span>_</span><span>□</span><span>✕</span></div>
                    </div>
                    <pre style="font-size:13.5px;line-height:1.27;">{SDK_CODE}</pre>
                    <div class="eval-flow">
                        <span class="flow-pill pass">[OK] CommerceTask record</span>
                        <span class="flow-pill pass">[OK] A2UI-shaped JSON dict</span>
                    </div>
                </div>
                <div class="card" style="display:flex;flex-direction:column;justify-content:space-between;">
                    <div>
                        <h3>What the contract checks</h3>
                        <ul>
                            <li><strong>State moves only from ACTIVE:</strong> <code>NONE → ACTIVE → COMPLETED | REFUNDED</code>, status set before each transfer.</li>
                            <li><strong>Payout needs the oracle:</strong> reverts unless <code>ecrecover(msgHash, v, r, s) == verifierOracle</code>.</li>
                            <li><strong>Payout needs the score:</strong> reverts when <code>qagScore &lt; minQualityBps</code>.</li>
                            <li><strong>Refund after deadline:</strong> <code>refundExpiredEscrow</code> reverts before <code>deadline</code>.</li>
                        </ul>
                    </div>
                    <div class="card success" style="padding:20px;">
                        <h4 style="color:#22c55e;font-size:20px;margin-bottom:6px;">Fuzz test</h4>
                        <p style="font-size:17px;">256 runs over amount and score against an 8500 threshold: the worker gets exactly the amount, or the call reverts.</p>
                    </div>
                </div>
            </div>
        """,
    },
    {
        "id": "scene4_honest_vs_adversarial_exec",
        "narration": (
            "The Foundry tests for the pass and fail paths. "
            "On the left, test_CompleteTaskWithValidProof signs a score of ninety-two hundred basis points with the test oracle key "
            "and checks that the worker receives two hundred fifty tUSD8. "
            "On the right, test_RevertOnSubparQuality expects a revert for a score of seventy-four hundred, "
            "and test_RevertOnInvalidSignature expects a revert for a signature from the wrong key."
        ),
        "html_body": """
            <div class="header">
                <span class="badge">Foundry tests</span>
                <h1>Valid Proof vs. Low Score and Wrong Signer</h1>
                <p class="subtitle">forge test -vv output from my machine, plus what each test checks.</p>
            </div>
            <div class="code-grid-2">
                <div class="terminal-mini">
                    <div class="linux-bar">
                        <span class="linux-tab">test_CompleteTaskWithValidProof</span>
                        <div class="linux-controls"><span>_</span><span>□</span><span>✕</span></div>
                    </div>
                    <div class="term-lines" style="font-size:17px;">
                        <p class="t-line"><span class="t-prompt">$</span> forge test --match-test test_CompleteTaskWithValidProof -vv</p>
                        <p class="t-line">Ran 1 test for test/AevumAgentEscrow.t.sol:AevumAgentEscrowTest</p>
                        <p class="t-line"><span class="t-green">[PASS]</span> test_CompleteTaskWithValidProof() (gas: 377072)</p>
                        <p class="t-line">Suite result: ok. 1 passed; 0 failed; 0 skipped</p>
                        <p class="t-line t-cyan">What it checks:</p>
                        <p class="t-line t-indent">score 9200, threshold 8500, signed with the test oracle key</p>
                        <p class="t-line t-indent">worker balance rises by 250 tUSD8; status COMPLETED</p>
                        <div class="t-banner-pass">1 passed</div>
                    </div>
                </div>
                <div class="terminal-mini danger-border">
                    <div class="linux-bar danger-header">
                        <span class="linux-tab-danger">test_RevertOn*</span>
                        <div class="linux-controls"><span>_</span><span>□</span><span>✕</span></div>
                    </div>
                    <div class="term-lines" style="font-size:17px;">
                        <p class="t-line"><span class="t-prompt">$</span> forge test --match-test test_RevertOn -vv</p>
                        <p class="t-line">Ran 2 tests for test/AevumAgentEscrow.t.sol:AevumAgentEscrowTest</p>
                        <p class="t-line"><span class="t-green">[PASS]</span> test_RevertOnInvalidSignature() (gas: 270180)</p>
                        <p class="t-line"><span class="t-green">[PASS]</span> test_RevertOnSubparQuality() (gas: 268598)</p>
                        <p class="t-line t-cyan">What they check:</p>
                        <p class="t-line t-indent">score 7400: expects revert "Quality score below requirement"</p>
                        <p class="t-line t-indent">wrong signing key: expects revert "Invalid verifier signature"</p>
                        <div class="t-banner-fail">2 passed (both calls revert)</div>
                    </div>
                </div>
            </div>
        """,
    },
    {
        "id": "scene5_verification_and_impact",
        "narration": (
            "Running the tests. "
            "Foundry runs six tests, including a fuzz test with two hundred fifty-six runs, and all six pass. "
            "Pytest runs three tests for the Python helper, and all three pass. "
            "You can run both with forge test and uv run pytest."
        ),
        "html_body": """
            <div class="header">
                <span class="badge">Tests</span>
                <h1>Foundry (6/6) and Pytest (3/3)</h1>
                <p class="subtitle">Output from my machine.</p>
            </div>
            <div class="grid-2" style="margin-top:18px;gap:26px;">
                <div class="terminal-window" style="height:640px;">
                    <div class="linux-bar">
                        <span class="linux-tab">forge test &amp;&amp; uv run pytest</span>
                        <div class="linux-controls"><span>_</span><span>□</span><span>✕</span></div>
                    </div>
                    <div class="terminal-content" style="font-size:14.8px;line-height:1.45;">
                        <p class="cmd">$ forge test -vv</p>
                        <p><span class="pass">[PASS]</span> test_CreateTaskEscrow() (gas: 246689)</p>
                        <p><span class="pass">[PASS]</span> test_CompleteTaskWithValidProof() (gas: 377072)</p>
                        <p><span class="pass">[PASS]</span> test_RevertOnSubparQuality() (gas: 268598)</p>
                        <p><span class="pass">[PASS]</span> test_RevertOnInvalidSignature() (gas: 270180)</p>
                        <p><span class="pass">[PASS]</span> test_RefundExpiredEscrow() (gas: 366605)</p>
                        <p><span class="pass">[PASS]</span> testFuzz_EscrowSettlement(uint256,uint256) (runs: 256)</p>
                        <p class="cmd" style="margin-top:8px;">$ uv run pytest -q</p>
                        <p><span class="pass">3 passed</span> in 0.01s</p>
                        <p class="success-banner">Foundry 6 passed (13.47ms) • Pytest 3 passed (0.01s)</p>
                    </div>
                </div>
                <div class="card" style="display:flex;flex-direction:column;justify-content:space-between;height:640px;">
                    <div>
                        <h3 style="color:#38bdf8;">Limits</h3>
                        <ul>
                            <li><strong>Not deployed:</strong> no testnet address in the repo</li>
                            <li><strong>No oracle service:</strong> tests sign with a fixed key</li>
                            <li><strong>Python helper:</strong> in memory only, no chain calls</li>
                            <li><strong>Contracts:</strong> <code>AevumAgentEscrow.sol</code> + <code>MockUSD8.sol</code></li>
                            <li><strong>GitHub Repository:</strong> <code>manderson240/aevum-agent-commerce</code></li>
                        </ul>
                    </div>
                    <div class="card success" style="padding:18px;">
                        <h4 style="color:#22c55e;font-size:20px;margin-bottom:6px;">Run it locally</h4>
                        <div class="code-pill" style="font-size:15.5px;">forge test &amp;&amp; uv run pytest -q</div>
                    </div>
                </div>
            </div>
        """,
    },
]

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en" style="background-color:#030712;width:100%;height:100%;margin:0;padding:0;">
<head><meta charset="UTF-8"><style>
* { box-sizing:border-box; margin:0; padding:0; }
html, body {
  width:2560px; height:1440px;
  background:radial-gradient(circle at 50% 12%, #182234 0%, #0b0f19 55%, #030712 100%) !important;
  font-family:-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  color:#f8fafc; padding:30px 60px;
  display:flex; flex-direction:column; justify-content:space-between; overflow:hidden;
}
.header { margin-bottom:12px; }
.badge { display:inline-block; padding:6px 18px; background:rgba(56,189,248,0.15); border:1px solid rgba(56,189,248,0.4); border-radius:9999px; color:#38bdf8; font-size:17px; font-weight:700; text-transform:uppercase; letter-spacing:2px; margin-bottom:6px; }
h1 { font-size:46px; font-weight:800; color:#ffffff; margin-bottom:6px; letter-spacing:-1px; }
.subtitle { font-size:22px; color:#94a3b8; line-height:1.35; }
.grid-2 { display:grid; grid-template-columns:1fr 1fr; gap:30px; }
.grid-4 { display:grid; grid-template-columns:repeat(4,1fr); gap:24px; }
.flow-container { display:flex; align-items:center; justify-content:space-between; background:rgba(30,41,59,0.45); border:1px solid rgba(148,163,184,0.2); border-radius:18px; padding:18px 32px; gap:16px; }
.flow-step { flex:1; background:#0d1322; border:1px solid #334155; border-radius:14px; padding:18px; text-align:center; }
.flow-step.highlight { border-color:#38bdf8; background:rgba(56,189,248,0.12); }
.flow-num { font-size:20px; font-weight:900; color:#38bdf8; margin-bottom:4px; }
.flow-step h4 { font-size:22px; color:#f8fafc; margin-bottom:4px; }
.flow-step p { font-size:16px; color:#94a3b8; margin-bottom:8px; line-height:1.35; }
.flow-arrow { font-size:30px; color:#64748b; padding:0 12px; font-weight:bold; }
.chip { display:inline-block; padding:6px 14px; background:#1e293b; border-radius:8px; font-size:14px; font-weight:600; color:#cbd5e1; }
.chip-blue { background:rgba(56,189,248,0.2); color:#38bdf8; border:1px solid rgba(56,189,248,0.4); }
.chip-green { background:rgba(34,197,94,0.2); color:#22c55e; border:1px solid rgba(34,197,94,0.4); }
.card { background:rgba(30,41,59,0.65); border:1px solid rgba(148,163,184,0.2); border-radius:18px; padding:24px; }
.card.danger { background:rgba(239,68,68,0.08); border-color:rgba(239,68,68,0.35); }
.card.success { background:rgba(34,197,94,0.08); border-color:rgba(34,197,94,0.35); }
.card-icon { font-size:36px; margin-bottom:8px; }
.card h3 { font-size:26px; color:#f1f5f9; margin-bottom:10px; font-weight:700; }
.card p { font-size:18px; color:#cbd5e1; line-height:1.4; }
.card ul { list-style:none; }
.card ul li { font-size:18px; color:#cbd5e1; line-height:1.8; }
.card ul li strong { color:#ffffff; }
.code-grid-2 { display:grid; grid-template-columns:1fr 1fr; gap:26px; height:980px; }
.code-box { background:#0a0e17; border:1px solid #1e293b; border-radius:14px; overflow:hidden; display:flex; flex-direction:column; box-shadow:0 25px 50px -12px rgba(0,0,0,0.7); }
.linux-bar { background:#181f30; padding:10px 18px; display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid #222d42; }
.linux-tab { background:#0a0e17; padding:4px 12px; border-radius:6px 6px 0 0; border:1px solid #222d42; border-bottom:none; color:#38bdf8; font-family:monospace; font-size:16px; font-weight:600; }
.linux-tab-danger { background:#0a0e17; padding:4px 12px; border-radius:6px 6px 0 0; border:1px solid rgba(239,68,68,0.4); border-bottom:none; color:#ef4444; font-family:monospace; font-size:16px; font-weight:600; }
.danger-header { background:#241319; border-bottom-color:rgba(239,68,68,0.3); }
.danger-border { border-color:rgba(239,68,68,0.45) !important; }
.linux-controls { display:flex; gap:14px; font-size:16px; color:#94a3b8; font-family:monospace; font-weight:bold; }
pre { padding:16px 22px; font-family:"JetBrains Mono","DejaVu Sans Mono",monospace; color:#e2e8f0; overflow:hidden; flex:1; }
.eval-flow { padding:12px 18px; background:#0e1526; border-top:1px solid #1e293b; display:flex; gap:10px; }
.flow-pill.pass { padding:5px 12px; border-radius:6px; font-size:14px; font-weight:700; background:rgba(34,197,94,0.18); color:#22c55e; border:1px solid rgba(34,197,94,0.35); }
.terminal-mini { background:#0a0e17; border:1px solid #1e293b; border-radius:14px; overflow:hidden; display:flex; flex-direction:column; }
.term-lines { padding:20px 24px; font-family:"JetBrains Mono",monospace; line-height:1.75; flex:1; display:flex; flex-direction:column; justify-content:space-between; }
.t-line { color:#f8fafc; } .t-prompt { color:#4ade80; font-weight:bold; } .t-cyan { color:#38bdf8; font-weight:bold; } .t-yellow { color:#fbbf24; font-weight:bold; } .t-green { color:#22c55e; font-weight:bold; } .t-red { color:#ef4444; font-weight:bold; } .t-indent { padding-left:22px; }
.t-banner-pass { margin-top:10px; padding:10px 16px; background:rgba(34,197,94,0.18); border:1px solid rgba(34,197,94,0.45); border-radius:8px; color:#22c55e; font-weight:800; font-size:18px; text-align:center; }
.t-banner-fail { margin-top:10px; padding:10px 16px; background:rgba(239,68,68,0.18); border:1px solid rgba(239,68,68,0.45); border-radius:8px; color:#ef4444; font-weight:800; font-size:18px; text-align:center; }
.terminal-window { background:#0a0e17; border:1px solid #1e293b; border-radius:14px; overflow:hidden; display:flex; flex-direction:column; }
.terminal-content { padding:20px 26px; font-family:"JetBrains Mono",monospace; flex:1; display:flex; flex-direction:column; justify-content:space-between; }
.cmd { color:#f8fafc; font-weight:bold; } .pass { color:#22c55e; font-weight:bold; } .success-banner { color:#22c55e; font-weight:bold; font-size:18px; margin-top:8px; }
.code-pill { display:inline-block; padding:8px 14px; background:#030712; border:1px solid #334155; border-radius:8px; font-family:monospace; color:#38bdf8; }
.footer { display:flex; justify-content:space-between; align-items:center; border-top:1px solid rgba(148,163,184,0.2); padding-top:14px; font-size:17px; color:#64748b; }
.footer-brand { font-weight:bold; color:#94a3b8; }
</style></head>
<body>
  __BODY__
  <div class="footer">
    <div class="footer-brand">Aevum Agent Commerce • Aevum Builder Challenge #1</div>
    <div>Quality-gated tUSD8 escrow • github.com/manderson240/aevum-agent-commerce</div>
  </div>
</body></html>"""


def _synthesize_audio(text: str, output_mp3: Path) -> None:
    pocket_bin = shutil.which("pocket-tts") or "/home/mike-anderson/.local/bin/pocket-tts"
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s.strip()]
    with tempfile.TemporaryDirectory() as td:
        wavs: list[Path] = []
        for idx, sent in enumerate(sentences):
            wav = Path(td) / f"part_{idx}.wav"
            subprocess.run(
                [pocket_bin, "generate", "--text", sent, "--device", "cpu", "--quantize", "--max-tokens", "150", "--output-path", str(wav), "-q"],
                check=True,
                capture_output=True,
            )
            if wav.exists() and wav.stat().st_size > 1000:
                wavs.append(wav)
        clist = Path(td) / "list.txt"
        clist.write_text("\n".join(f"file '{w}'" for w in wavs), encoding="utf-8")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(clist), "-af", "apad=pad_dur=1.25", "-c:a", "libmp3lame", "-b:a", "192k", str(output_mp3)],
            check=True,
            capture_output=True,
        )


def main() -> None:
    out_mp4 = REPO_ROOT / "docs" / "aevum_commerce_demo.mp4"
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        parts: list[Path] = []
        for scene in SCENES:
            sid = scene["id"]
            print(f"🎬 Rendering {sid} at {WIDTH}x{HEIGHT} QHD...")
            html_file = work / f"{sid}.html"
            raw_png = work / f"{sid}_raw.png"
            png_file = work / f"{sid}.png"
            mp3_file = work / f"{sid}.mp3"
            seg_mp4 = work / f"{sid}.mp4"
            html_file.write_text(HTML_TEMPLATE.replace("__BODY__", scene["html_body"]), encoding="utf-8")
            subprocess.run(
                ["google-chrome", "--headless", "--hide-scrollbars", "--disable-gpu", "--force-device-scale-factor=1", f"--screenshot={raw_png}", f"--window-size={WIDTH},{CHROME_CAPTURE_HEIGHT}", str(html_file)],
                check=True,
                capture_output=True,
            )
            Image.open(raw_png).crop((0, 0, WIDTH, HEIGHT)).save(png_file)
            _synthesize_audio(scene["narration"], mp3_file)
            subprocess.run(
                ["ffmpeg", "-y", "-loop", "1", "-i", str(png_file), "-i", str(mp3_file), "-c:v", "libx264", "-crf", "16", "-preset", "medium", "-tune", "stillimage", "-c:a", "aac", "-b:a", "192k", "-pix_fmt", "yuv420p", "-shortest", str(seg_mp4)],
                check=True,
                capture_output=True,
            )
            parts.append(seg_mp4)
        clist = work / "concat.txt"
        clist.write_text("\n".join(f"file '{p}'" for p in parts), encoding="utf-8")
        subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(clist), "-c", "copy", str(out_mp4)], check=True, capture_output=True)
    info = json.loads(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration,size", "-of", "json", str(out_mp4)], text=True))
    print(f"GENERATED: {out_mp4} ({float(info['format']['duration']):.2f}s, {int(info['format']['size'])/(1024*1024):.2f} MB)")


if __name__ == "__main__":
    t0 = time.time()
    main()
    print(f"Elapsed: {time.time() - t0:.1f}s")
