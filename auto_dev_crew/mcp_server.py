"""Auto Dev Crew — Model Context Protocol (MCP) Server & Outbound Role-Scoped Client Guard.

Zero external dependencies: Python 3.12 stdlib JSON-RPC 2.0 over stdio.
Run: python -m auto_dev_crew.mcp_server --transport stdio
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from . import gui, gui_patches, metrics, runner
from .redact import redact_secrets

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "auto-dev-crew", "version": "1.1.0"}
MAX_RPC_LINE_BYTES = 512 * 1024

MCP_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{1,48}$")
ALLOWED_MCP_BINARIES = frozenset({"python", "python3", "npx", "uvx", "node", "opencode"})
SHELL_METACHARS = frozenset(";&|`$<>\n\r\x00")

TOOLS_SCHEMA: list[dict[str, Any]] = [
    {
        "name": "adc_get_status",
        "description": "Read-only daemon state, parallel slot status, merge_mode, and F6 engine health.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "adc_list_pending_decisions",
        "description": "Read-only inbox of open bot PRs and failed/blocked issues awaiting owner decision.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "adc_inspect_pr_gate",
        "description": "Read-only redacted diff preview for an open PR in a registered repository.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo": {"type": "string"},
                "pr": {"type": "integer", "minimum": 1},
            },
            "required": ["repo", "pr"],
            "additionalProperties": False,
        },
    },
    {
        "name": "adc_get_metrics",
        "description": "Read-only terminal merge-rate summary grouped by engine, kind, or triage_path.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "by": {"type": "string", "enum": ["engine", "kind", "key", "triage_path"]},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "adc_run_dry_check",
        "description": "Run allowlisted local verification (test, syntax, security) with zero GitHub writes.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo": {"type": "string"},
                "check_type": {"type": "string", "enum": ["test", "syntax", "security"]},
            },
            "required": ["repo"],
            "additionalProperties": False,
        },
    },
    {
        "name": "adc_create_ai_task",
        "description": "Create a GitHub issue labeled ai-task. Requires explicit confirm=true flag.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo": {"type": "string"},
                "title": {"type": "string", "minLength": 3, "maxLength": 200},
                "body": {"type": "string", "maxLength": 8000},
                "confirm": {"type": "boolean"},
            },
            "required": ["repo", "title", "confirm"],
            "additionalProperties": False,
        },
    },
]

PROMPTS_SCHEMA: list[dict[str, str]] = [
    {
        "name": "adc-morning-briefing",
        "description": "Summarize overnight merged PRs, F6 quota health, and pending owner approvals.",
    },
    {
        "name": "adc-triage-failed-issues",
        "description": "Diagnose ai-failed or Gate-3-blocked issues in plain English and suggest retry tasks.",
    },
    {
        "name": "adc-review-protected-prs",
        "description": "Review open PRs against AGENTS.md protected-file rules (runner.py, config.yaml, workflows).",
    },
]


def validate_external_mcp_client(
    entry: dict[str, Any],
    role: str,
    slot_workdir: Path | None = None,
) -> dict[str, Any]:
    """Validate external MCP client config and enforce read-only isolation for judge and scan roles."""
    if role not in ("coder", "judge", "scan"):
        raise ValueError(f"Unknown agent role: {role!r}")

    name = str(entry.get("name") or "").strip()
    if not MCP_NAME_RE.fullmatch(name):
        raise ValueError(f"Invalid MCP server name: {name!r}")

    raw_cmd = str(entry.get("command") or "").strip()
    if not raw_cmd or any(ch in SHELL_METACHARS for ch in raw_cmd):
        raise ValueError("MCP command is empty or contains forbidden shell metacharacters")

    parts = raw_cmd.split()
    binary = Path(parts[0]).stem.lower()
    if binary not in ALLOWED_MCP_BINARIES:
        raise ValueError(f"MCP command binary {binary!r} is not in ALLOWED_MCP_BINARIES")

    read_only = bool(entry.get("read_only", True))
    if role in ("judge", "scan") and not read_only:
        raise PermissionError(f"Role {role!r} is strictly restricted to read_only=True MCP servers")

    scoped_cwd: str | None = None
    if not read_only:
        if slot_workdir is None:
            raise PermissionError("Write-capable MCP server for coder requires an isolated slot_workdir")
        safe_dir = gui_patches.resolve_safe_worktree_path(slot_workdir, runner.WORK)
        scoped_cwd = str(safe_dir)

    return {
        "name": name,
        "args": parts,
        "binary": binary,
        "read_only": read_only,
        "cwd": scoped_cwd,
    }


def _execute_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    cfg = gui.load_cfg()
    if name == "adc_get_status":
        st = gui.status()
        return {
            "agent": st["agent"],
            "merge_mode": st["merge_mode"],
            "slots": st["slots"],
            "activity": st["activity"],
            "engines": [
                {
                    "name": e["name"],
                    "state": e["state"],
                    "trains_on_data": e["trains_on_data"],
                    "keys_status": e.get("keys_status"),
                }
                for e in st["usage"]["engines"]
            ],
        }

    if name == "adc_list_pending_decisions":
        st = gui.status()
        items: list[dict[str, Any]] = []
        for repo in st["repos"]:
            for pr in repo.get("prs", []):
                if pr.get("state") == "OPEN":
                    items.append({
                        "kind": "open_pr",
                        "repo": repo["name"],
                        "number": pr.get("number"),
                        "title": pr.get("title"),
                        "url": pr.get("url"),
                    })
            for iss in repo.get("issues", []):
                if iss.get("status") == "failed":
                    items.append({
                        "kind": "failed_issue",
                        "repo": repo["name"],
                        "number": iss.get("number"),
                        "title": iss.get("title"),
                        "url": iss.get("url"),
                    })
        return {"count": len(items), "items": items}

    if name == "adc_inspect_pr_gate":
        repo = gui_patches.require_registered_repo(arguments.get("repo"), cfg)
        pr_val = arguments.get("pr")
        if isinstance(pr_val, bool) or not isinstance(pr_val, int) or pr_val < 1:
            raise ValueError("pr must be a positive integer")
        diff_txt = gui.diff_for({"repo": repo, "pr": str(pr_val)})
        return {"repo": repo, "pr": pr_val, "diff": redact_secrets(diff_txt[:40_000])}

    if name == "adc_get_metrics":
        group_by = str(arguments.get("by") or "engine")
        if group_by not in metrics.GROUP_FIELDS:
            raise ValueError(f"by must be one of {metrics.GROUP_FIELDS}")
        history = runner.load_history()
        return {"by": group_by, "groups": metrics.summarize(history, by=group_by)}

    if name == "adc_run_dry_check":
        repo = gui_patches.require_registered_repo(arguments.get("repo"), cfg)
        check_type = str(arguments.get("check_type") or "test")
        if check_type not in ("test", "syntax", "security"):
            raise ValueError("check_type must be test, syntax, or security")
        return gui.act("/api/repo/run-command", {"repo": repo, "check_type": check_type})

    if name == "adc_create_ai_task":
        if arguments.get("confirm") is not True:
            raise PermissionError("Safety Guard: confirm=true is required before creating GitHub issues")
        repo = gui_patches.require_registered_repo(arguments.get("repo"), cfg)
        title = str(arguments.get("title") or "").strip()
        if len(title) < 3 or len(title) > 200:
            raise ValueError("title must be 3..200 characters")
        body = str(arguments.get("body") or "").strip()[:8000]
        return gui.act("/api/task", {"repo": repo, "title": title, "body": body})

    raise LookupError(f"Unknown MCP tool: {name!r}")


def _build_prompt(name: str) -> dict[str, Any]:
    known = {p["name"] for p in PROMPTS_SCHEMA}
    if name not in known:
        raise LookupError(f"Unknown MCP prompt: {name!r}")
    snapshot = _execute_tool("adc_list_pending_decisions", {})
    safe_json = redact_secrets(json.dumps(snapshot, ensure_ascii=False))
    templates = {
        "adc-morning-briefing": (
            "Summarize overnight Auto Dev Crew activity, highlight pending human approvals, "
            f"and confirm zero-budget engine readiness using this live snapshot: {safe_json}"
        ),
        "adc-triage-failed-issues": (
            "Explain each failed_issue in plain, beginner-friendly language and draft a corrected "
            f"ai-task description specifying exact target source files: {safe_json}"
        ),
        "adc-review-protected-prs": (
            "Audit each open_pr against AGENTS.md protected paths (runner.py, config.yaml, "
            f".github/workflows/, .env, keys.py, providers.py): {safe_json}"
        ),
    }
    return {
        "description": name,
        "messages": [{"role": "user", "content": {"type": "text", "text": templates[name]}}],
    }


def handle_rpc(req: dict[str, Any]) -> dict[str, Any] | None:
    """Process one JSON-RPC 2.0 message and return a response dict (or None for notifications)."""
    if not isinstance(req, dict) or req.get("jsonrpc") != "2.0":
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid Request"}}

    method = req.get("method")
    req_id = req.get("id")
    params = req.get("params") if isinstance(req.get("params"), dict) else {}

    if isinstance(method, str) and method.startswith("notifications/"):
        return None

    try:
        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "serverInfo": SERVER_INFO,
                    "capabilities": {"tools": {}, "prompts": {}, "resources": {}},
                },
            }
        if method == "ping":
            return {"jsonrpc": "2.0", "id": req_id, "result": {}}
        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS_SCHEMA}}
        if method == "tools/call":
            tool_name = str(params.get("name") or "")
            tool_args = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
            data = _execute_tool(tool_name, tool_args)
            text = redact_secrets(json.dumps(data, ensure_ascii=False, indent=2))
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"content": [{"type": "text", "text": text}], "isError": False},
            }
        if method == "prompts/list":
            return {"jsonrpc": "2.0", "id": req_id, "result": {"prompts": PROMPTS_SCHEMA}}
        if method == "prompts/get":
            return {"jsonrpc": "2.0", "id": req_id, "result": _build_prompt(str(params.get("name") or ""))}
        if method == "resources/list":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "resources": [
                        {
                            "uri": "adc://status",
                            "name": "Auto Dev Crew Live Status",
                            "mimeType": "application/json",
                        }
                    ]
                },
            }
        if method == "resources/read" and params.get("uri") == "adc://status":
            text = redact_secrets(json.dumps(_execute_tool("adc_get_status", {}), ensure_ascii=False))
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"contents": [{"uri": "adc://status", "mimeType": "application/json", "text": text}]},
            }
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Method not found: {method}"}}
    except PermissionError as exc:
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32001, "message": redact_secrets(str(exc))}}
    except (ValueError, LookupError, KeyError) as exc:
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32602, "message": redact_secrets(str(exc))}}
    except Exception as exc:  # noqa: BLE001
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32603, "message": redact_secrets(f"Internal error: {exc}")}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m auto_dev_crew.mcp_server")
    parser.add_argument("--transport", choices=("stdio",), default="stdio")
    parser.add_argument("--config", default=None, help="Optional config.yaml path override")
    args = parser.parse_args(argv)
    if args.config:
        gui.set_config_path(args.config)

    for stream in (sys.stdin, sys.stdout):
        stream.reconfigure(encoding="utf-8", errors="replace")

    for raw_line in sys.stdin:
        if len(raw_line.encode("utf-8", errors="replace")) > MAX_RPC_LINE_BYTES:
            err = {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Payload exceeds 512 KB limit"}}
            sys.stdout.write(json.dumps(err) + "\n")
            sys.stdout.flush()
            continue
        stripped = raw_line.strip()
        if not stripped:
            continue
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            resp: dict[str, Any] | None = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
        else:
            resp = handle_rpc(payload)
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
