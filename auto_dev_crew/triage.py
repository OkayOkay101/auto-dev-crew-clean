"""Dual-Path Triage Engine: Classify tasks into Fast-Path or Heavy-Path."""
from __future__ import annotations

import json
import logging
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

_logger = logging.getLogger(__name__)


@dataclass
class TriageResult:
    path: str  # "fast" | "heavy"
    reason: str
    confidence: float
    method: str  # "heuristic" | "llm" | "heuristic_default"


DEFAULT_FAST_LABELS = ["quick-fix", "typo", "docs", "documentation", "minor", "small", "lint"]
DEFAULT_HEAVY_LABELS = ["feature", "architecture", "refactor", "breaking", "complex", "security"]


def _call_llm_classifier(job: Any, cfg: dict, call_agent: Callable[..., Any] | None = None) -> str:
    """Invokes LLM classifier to categorize task when heuristics are ambiguous."""
    if call_agent is None:
        from .runner import call_agent  # lazy: runner imports this module at load time
    # Lightweight prompt asking for strict JSON
    prompt = (
        "Classify the following software development task into either 'fast' (small, <20 lines, 1 file) "
        "or 'heavy' (feature, multi-file, architecture, refactoring).\n\n"
        f"Title: {job.title}\n"
        f"Description: {job.body[:1500]}\n\n"
        'Return strict JSON in format: {"path": "fast"|"heavy", "reason": "...", "confidence": 0.0-1.0}'
    )
    # The classifier agent may run --auto, so it gets an empty scratch dir, never the project root.
    with tempfile.TemporaryDirectory(prefix="triage-") as scratch:
        res = call_agent(cfg, prompt, Path(scratch))
    if isinstance(res, dict):
        return res.get("response") or ""
    return str(res)


def _parse_llm_triage_response(raw_text: str) -> TriageResult | None:
    match = re.search(r"```json\s*(\{.*?\})\s*```", raw_text, re.DOTALL)
    if not match:
        match = re.search(r"(\{.*\})", raw_text, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(1))
        path = str(data.get("path", "heavy")).strip().lower()
        if path not in ("fast", "heavy"):
            path = "heavy"
        reason = str(data.get("reason", "LLM triage decision"))
        confidence = float(data.get("confidence", 0.8))
        return TriageResult(path=path, reason=reason, confidence=confidence, method="llm")
    except Exception:
        return None


def classify_task(job: Any, cfg: dict, cwd: Path | None = None,
                  call_agent: Callable[..., Any] | None = None) -> TriageResult:
    """Classify task into Fast-Path or Heavy-Path using hybrid heuristic + LLM approach."""
    tcfg = cfg.get("triage", {})
    if not tcfg.get("enabled", True):
        return TriageResult(path="heavy", reason="Triage disabled", confidence=1.0, method="heuristic_default")

    fast_labels = [l.lower() for l in tcfg.get("fast_labels", DEFAULT_FAST_LABELS)]
    heavy_labels = [l.lower() for l in tcfg.get("heavy_labels", DEFAULT_HEAVY_LABELS)]

    # 1. Persona checks
    if getattr(job, "kind", "") == "persona":
        key = getattr(job, "key", "").lower()
        if key == "palette":
            return TriageResult(path="fast", reason="Persona palette handles style and polish", confidence=0.95, method="heuristic")
        if key == "sentinel" or any(h in key for h in heavy_labels):
            return TriageResult(path="heavy", reason=f"Persona {key} requires deep analysis/refactor", confidence=0.95, method="heuristic")
        # Default other personas to heavy-path to avoid classifying empty body as fast-path
        return TriageResult(path="heavy", reason=f"Persona {key} autonomous exploration", confidence=0.8, method="heuristic")

    # 2. Label checks (Heavy labels take precedence for safety)
    job_labels = [str(l).lower() for l in getattr(job, "labels", [])]
    for lbl in job_labels:
        if lbl in heavy_labels:
            return TriageResult(path="heavy", reason=f"Matched heavy-path label: {lbl}", confidence=0.95, method="heuristic")
    for lbl in job_labels:
        if lbl in fast_labels:
            return TriageResult(path="fast", reason=f"Matched fast-path label: {lbl}", confidence=0.9, method="heuristic")

    # 3. Content heuristics
    body = getattr(job, "body", "") or ""
    title = getattr(job, "title", "") or ""
    combined_len = len(body) + len(title)

    if combined_len <= 150:
        return TriageResult(path="fast", reason="Short description (<= 150 chars)", confidence=0.85, method="heuristic")
    if combined_len >= 1500:
        return TriageResult(path="heavy", reason="Long description (>= 1500 chars)", confidence=0.85, method="heuristic")

    # 4. LLM Fallback if ambiguous
    if tcfg.get("use_llm_fallback", False):
        try:
            raw_resp = _call_llm_classifier(job, cfg, call_agent=call_agent)
            parsed = _parse_llm_triage_response(raw_resp)
            if parsed:
                return parsed
        except Exception:
            # Fall back to default on error, but keep the failure visible
            _logger.warning("LLM triage failed; defaulting to heavy path", exc_info=True)

    # 5. Default safe fallback
    return TriageResult(path="heavy", reason="Ambiguous complexity defaulting to heavy-path", confidence=0.5, method="heuristic_default")
