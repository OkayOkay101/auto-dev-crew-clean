"""Pre-PR agentic-eval Gate: Evaluator-Optimizer pattern for quality-critical code PRs."""
from __future__ import annotations
from auto_dev_crew import i18n as _i18n

import json
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable



ROOT = Path(__file__).resolve().parent.parent
PROMPTS = ROOT / "prompts"


@dataclass
class EvaluationResult:
    score: float
    passed: bool
    critique_th: str
    dimensions: dict[str, float]
    # True when the judge never produced a verdict because its engine was busy/unavailable (BUG-6).
    # The job must not treat this as a low score and spend a refinement round on it.
    engine_error: bool = False
    # Which engine produced this verdict, and whether it is the same engine the coder used
    # (only possible when no other judge-capable engine was available).
    judge_engine: str | None = None
    judge_same_as_coder: bool = False
    # True when the dedicated judge failed and the default engine produced this verdict instead.
    # A fallback verdict may open a PR, but the PR is never auto-merged (see runner.finish_pr).
    judge_fallback: bool = False
    # ตำแหน่งที่ judge ชี้ว่าต้องแก้ ("path:line") ใช้ในรอบปรับปรุง; ว่างเมื่อ judge ไม่ได้ชี้หรืออ่านไม่ได้
    fix_location: list[str] = field(default_factory=list)
    # ทางเลือกในการแก้ที่ judge เสนอ (วิธี/ข้อดี/ข้อเสีย) ใช้เป็นคำแนะนำ ไม่กระทบคะแนน
    fix_options: list[dict[str, str]] = field(default_factory=list)


MAX_FIX_LOCATIONS = 5
MAX_FIX_OPTIONS = 2
MAX_FIX_OPTION_TEXT = 300


def parse_fix_location(data: dict) -> list[str]:
    """ดึง fix_location จากผล judge อย่างปลอดภัย: เฉพาะสตริง ไม่ซ้ำ จำกัดจำนวนและความยาว."""
    raw = data.get("fix_location")
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            continue
        text = item.strip()[:200]
        if text and text not in out:
            out.append(text)
        if len(out) >= MAX_FIX_LOCATIONS:
            break
    return out


def parse_fix_options(data: dict) -> list[dict[str, str]]:
    """ดึง fix_options จากผล judge อย่างปลอดภัย: เฉพาะ object ที่มี approach, จำกัดจำนวนและความยาว."""
    raw = data.get("fix_options")
    if not isinstance(raw, list):
        return []
    out: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        approach = item.get("approach")
        if not isinstance(approach, str) or not approach.strip():
            continue
        option = {"approach": approach.strip()[:MAX_FIX_OPTION_TEXT]}
        for key in ("pros", "cons"):
            val = item.get(key)
            option[key] = val.strip()[:MAX_FIX_OPTION_TEXT] if isinstance(val, str) else ""
        out.append(option)
        if len(out) >= MAX_FIX_OPTIONS:
            break
    return out


def pick_judge_pool(candidates: list[dict], exclude_engine: str | None) -> tuple[list[dict], bool]:
    """Judge-capable engines minus the coder's engine. Returns (pool, same_as_coder).

    If excluding the coder's engine leaves nothing, the coder's engine is kept and flagged, so the
    job still gets a verdict instead of waiting forever for a second engine."""
    if not exclude_engine:
        return candidates, False
    others = [e for e in candidates if e.get("name") != exclude_engine]
    if others:
        return others, False
    return candidates, bool(candidates)


def count_diff_lines(diff: str) -> int:
    """Count added lines (+), excluding the +++ file headers."""
    return sum(1 for line in (diff or "").splitlines() if line.startswith("+") and not line.startswith("+++"))


def _to_float(val: Any, default: float = 0.0) -> float:
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def parse_eval_response(
    raw_text: str,
    min_score: float = 0.75,
    weights: dict[str, float] | None = None
) -> EvaluationResult:
    """Parse JSON evaluation from model response and compute weighted rubric score."""
    if weights is None:
        weights = {
            "alignment_weight": 0.4,
            "safety_cleanliness_weight": 0.3,
            "quality_weight": 0.3
        }

    # Extract JSON between ```json ... ``` or first { ... }
    match = re.search(r"```json\s*(\{.*?\})\s*```", raw_text, re.DOTALL)
    if not match:
        match = re.search(r"(\{.*\})", raw_text, re.DOTALL)

    if not match:
        return EvaluationResult(
            score=0.0,
            passed=False,
            critique_th=_i18n.t("ไม่สามารถแยกผลการประเมิน JSON จากการตอบกลับของโมเดล"),
            dimensions={"task_alignment": 0.0, "safety_cleanliness": 0.0, "quality": 0.0}
        )

    try:
        data = json.loads(match.group(1))
        if not isinstance(data, dict):
            raise ValueError("Root JSON is not an object")
    except (json.JSONDecodeError, ValueError):
        return EvaluationResult(
            score=0.0,
            passed=False,
            critique_th=_i18n.t("รูปแบบ JSON ของการประเมินไม่ถูกต้อง"),
            dimensions={"task_alignment": 0.0, "safety_cleanliness": 0.0, "quality": 0.0}
        )

    task_align = _to_float(data.get("task_alignment"), 0.0)
    safety = _to_float(data.get("safety_cleanliness"), 0.0)
    quality = _to_float(data.get("quality"), 0.0)

    w_align = weights.get("alignment_weight", 0.4)
    w_safety = weights.get("safety_cleanliness_weight", 0.3)
    w_quality = weights.get("quality_weight", 0.3)
    total_w = w_align + w_safety + w_quality or 1.0

    score = ((task_align * w_align) + (safety * w_safety) + (quality * w_quality)) / total_w
    critique = str(data.get("critique_th") or _i18n.t("ประเมินผลเรียบร้อย"))

    passed = score >= min_score and task_align >= 0.5 and safety >= 0.5

    return EvaluationResult(
        score=score,
        passed=passed,
        critique_th=critique,
        dimensions={
            "task_alignment": task_align,
            "safety_cleanliness": safety,
            "quality": quality
        },
        fix_location=parse_fix_location(data),
        fix_options=parse_fix_options(data),
    )


def check_convergence(scores: list[float]) -> bool:
    """Return True if recent scores have converged (not improving)."""
    if len(scores) < 2:
        return False
    return scores[-1] <= scores[-2]


def evaluate_diff(
    diff: str,
    task_desc: str,
    test_output: str,
    cfg: dict,
    cwd: Path,
    evaluator_engine: str | None = None,
    call_agent: Callable[..., dict] | None = None,
    mode: str = "auto",
    exclude_engine: str | None = None,
) -> EvaluationResult:
    """Run in-process agentic-eval rubric evaluation using the active engine.

    exclude_engine: the engine the coder used. The judge prefers any other judge-capable engine so
    the reviewer is not the author."""
    
    from .guardrails import check_deterministic_pre_eval

    eval_cfg = cfg.get("evaluation", {})
    if not eval_cfg.get("enabled", True):
        return EvaluationResult(
            score=1.0,
            passed=True,
            critique_th=_i18n.t("ข้ามการประเมิน (evaluation.enabled: false)"),
            dimensions={"task_alignment": 1.0, "safety_cleanliness": 1.0, "quality": 1.0}
        )

    # 1. Deterministic Git Diff Check: empty diff fails fast
    if not diff or not diff.strip():
        runner.log("[agentic-eval] ⛔ Git diff ว่างเปล่า — ไม่พบการเปลี่ยนแปลงของโค้ด")
        return EvaluationResult(
            score=0.0,
            passed=False,
            critique_th=_i18n.t("⛔ Git diff ว่างเปล่า — ไม่พบการเปลี่ยนแปลงของโค้ด"),
            dimensions={"task_alignment": 0.0, "safety_cleanliness": 0.0, "quality": 0.0}
        )

    # 2. Hard Gate for Fast Surgical Mode: diff line count cap (before any LLM call)
    max_fast_diff = int(eval_cfg.get("max_fast_diff_lines", 30))
    diff_lines = count_diff_lines(diff)
    if mode == "fast" and diff_lines > max_fast_diff:
        msg = (f"⛔ Hard Gate FAILED: Diff ขนาด {diff_lines} บรรทัด เกินโควตา {max_fast_diff} บรรทัดสำหรับ "
               "Fast Surgical Mode (กรุณาย่อโค้ดให้แก้เฉพาะจุดที่จำเป็น)")
        runner.log(f"[agentic-eval] {msg}")
        return EvaluationResult(
            score=0.0,
            passed=False,
            critique_th=msg,
            dimensions={"task_alignment": 0.5, "safety_cleanliness": 0.5, "quality": 0.0}
        )

    # 3. Deterministic Pre-Eval Gate: verify AST syntax only on changed files without burning LLM judge quota
    changed_files = re.findall(r"^\+\+\+ b/(.*?)$", diff, re.MULTILINE)
    ok, pre_eval_msg = check_deterministic_pre_eval(cwd, changed_files=changed_files)
    if not ok:
        runner.log(f"[agentic-eval] ⛔ Deterministic Pre-Eval ล้มเหลว: {pre_eval_msg}")
        return EvaluationResult(
            score=0.0,
            passed=False,
            critique_th=_i18n.t("⛔ Deterministic Pre-Eval ล้มเหลว: {p0}", p0=pre_eval_msg),
            dimensions={"task_alignment": 0.0, "safety_cleanliness": 0.0, "quality": 0.0}
        )

    # 4. ด่านตรวจแบบกำหนดผล (static_checks): กฎที่ blocking ทำให้ diff ไม่ผ่านทันที โดยไม่เรียก judge
    from .static_checks import blocking_findings, format_advisory, format_findings, scan_diff
    findings = scan_diff(diff)
    hard = blocking_findings(findings)
    if hard:
        msg = "⛔ ด่านตรวจแบบกำหนดผลไม่ผ่าน:\n" + format_findings(hard)
        runner.log(f"[agentic-eval] ⛔ Static checks ล้มเหลว {len(hard)} จุด")
        return EvaluationResult(
            score=0.0,
            passed=False,
            critique_th=msg,
            dimensions={"task_alignment": 0.0, "safety_cleanliness": 0.0, "quality": 0.0},
            fix_location=[f"{f.path}:{f.line}" for f in hard[:5]],
        )

    prompt_tmpl = (PROMPTS / "evaluator.md").read_text(encoding="utf-8")
    # ด่าน 2 (docs/draft-quality-gates.md): judge เห็นไฟล์ production เต็มหลังแก้ ไม่ใช่แค่ diff
    from .quality_gates import full_files_block
    prompt = runner.fill_template(prompt_tmpl, {
        "task_description": task_desc[:4000],
        "test_output": test_output[-3000:],
        "git_diff": diff[:12000],
        "full_files": full_files_block(cwd, changed_files),
        "static_findings": format_advisory(findings),
    })

    judge_engine = evaluator_engine or eval_cfg.get("engine", "auto")
    target_cfg = cfg
    matched = []
    same_as_coder = False
    if judge_engine and str(judge_engine).lower() != "auto":
        engines = runner.get_engines(cfg)
        matched = [e for e in engines if e.get("name") == judge_engine and e.get("enabled", True)]
        if matched:
            target_cfg = dict(cfg, engines=matched)
            same_as_coder = bool(exclude_engine) and judge_engine == exclude_engine
    else:
        # Dynamic judge selection: look for enabled engines with keys having role 'judge'
        engines = runner.get_engines(cfg)
        judge_matched = []
        for e in engines:
            if e.get("enabled", True):
                judge_entries = runner.get_engine_key_entries(e, role="judge", allow_fallback=False)
                if judge_entries and runner.is_engine_ready(e, role="judge"):
                    judge_matched.append(e)
        judge_matched, same_as_coder = pick_judge_pool(judge_matched, exclude_engine)
        if judge_matched:
            matched = judge_matched
            target_cfg = dict(cfg, engines=judge_matched)
    if same_as_coder:
        runner.log(f"[agentic-eval] ⚠️ ไม่มี judge engine อื่นที่พร้อม — ใช้ {exclude_engine} ซึ่งเป็น engine ของ coder")

    eval_timeout_min = float(eval_cfg.get("timeout_minutes", 3))
    # Cap timeout for evaluation engines so judge doesn't stall for 30 minutes
    judge_engines = []
    for e in runner.get_engines(target_cfg):
        e_copy = dict(e)
        e_copy["timeout_minutes"] = min(float(e.get("timeout_minutes", 30)), eval_timeout_min)
        judge_engines.append(e_copy)
    target_cfg = dict(target_cfg, engines=judge_engines)

    if matched:
        if judge_engine and str(judge_engine).lower() != "auto":
            engine_label = matched[0]["name"]
        else:
            engine_label = f"Auto ({matched[0]['name']} - บทบาท Judge)"
    else:
        if judge_engine and str(judge_engine).lower() != "auto":
            engine_label = f"Default (Fallback เนื่องจาก '{judge_engine}' ปิดอยู่หรือไม่พร้อม)"
        else:
            engine_label = "Auto (Fallback to default coder engine)"
    runner.log(f"[agentic-eval] เริ่มประเมินคุณภาพโค้ดตาม Rubric (Engine: {engine_label}, Timeout: {eval_timeout_min:.0f}m)...")
    fallback_used = False
    try:
        # The judge runs --auto (can edit files), so it gets an empty scratch dir, never the worktree.
        # The diff is already in the prompt.
        with tempfile.TemporaryDirectory(prefix="judge-") as judge_dir:
            agent = call_agent or runner.call_agent  # default: runner's (patchable) call_agent
            res = agent(target_cfg, prompt, Path(judge_dir), role="judge")
        if res.get("status") == "ERROR":
            err_msg = res.get("response") or _i18n.t("โมเดลประเมินไม่ตอบกลับหรือเกิดข้อผิดพลาด")
            if matched:
                fallback_used = True
                runner.log(f"[agentic-eval] ⚠️ Judge เฉพาะกิจล้มเหลว ({err_msg}) -> สลับประเมินด้วย Default Fallback Engine...")
                try:
                    with tempfile.TemporaryDirectory(prefix="judge-fb-") as fb_dir:
                        res = agent(cfg, prompt, Path(fb_dir))
                except Exception as fb_exc:
                    runner.log(f"[agentic-eval] Default Fallback Engine ล้มเหลวเช่นกัน: {fb_exc}")
            if res.get("status") == "ERROR":
                err_msg = res.get("response") or _i18n.t("โมเดลประเมินไม่ตอบกลับหรือเกิดข้อผิดพลาด")
                runner.log(f"[agentic-eval] ⚠️ โมเดลประเมินตอบกลับล้มเหลว ({err_msg})")
                return EvaluationResult(
                    score=0.0,
                    passed=False,
                    critique_th=_i18n.t("การประเมินล้มเหลว ({p0})", p0=err_msg),
                    dimensions={"task_alignment": 0.0, "safety_cleanliness": 0.0, "quality": 0.0}
                )

        raw_text = res.get("response") or ""
        min_score = float(eval_cfg.get("min_pass_score", 0.75))
        weights = eval_cfg.get("rubric", {})
        result = parse_eval_response(raw_text, min_score=min_score, weights=weights)
        result.judge_engine = res.get("engine_used")
        result.judge_same_as_coder = same_as_coder
        result.judge_fallback = fallback_used
        runner.log(
            f"[agentic-eval] คะแนนรวม: {result.score:.2f} ({'ผ่าน ✅' if result.passed else 'ไม่ผ่าน ❌'}) "
            f"— {result.critique_th}"
        )
        return result
    except Exception as exc:
        if matched:
            runner.log(f"[agentic-eval] ⚠️ เกิดข้อผิดพลาดจาก Judge เฉพาะกิจ ({exc}) -> สลับประเมินด้วย Default Fallback Engine...")
            try:
                with tempfile.TemporaryDirectory(prefix="judge-fb-") as fb_dir:
                    agent = call_agent or runner.call_agent
                    res = agent(cfg, prompt, Path(fb_dir))
                    if res.get("status") != "ERROR":
                        raw_text = res.get("response") or ""
                        min_score = float(eval_cfg.get("min_pass_score", 0.75))
                        weights = eval_cfg.get("rubric", {})
                        result = parse_eval_response(raw_text, min_score=min_score, weights=weights)
                        result.judge_fallback = True
                        runner.log(
                            f"[agentic-eval] (Fallback) คะแนนรวม: {result.score:.2f} ({'ผ่าน ✅' if result.passed else 'ไม่ผ่าน ❌'}) "
                            f"— {result.critique_th}"
                        )
                        return result
            except Exception as fb_exc:
                runner.log(f"[agentic-eval] Default Fallback Engine ล้มเหลวเช่นกัน: {fb_exc}")

        runner.log(f"[agentic-eval] การประเมินล้มเหลว: {exc} (ไม่อนุญาตให้ผ่านเพื่อรักษาความปลอดภัย)")
        return EvaluationResult(
            score=0.0,
            passed=False,
            critique_th=_i18n.t("การประเมินขัดข้อง ({p0}) — บล็อกการเปิด PR เพื่อความปลอดภัย", p0=exc),
            dimensions={"task_alignment": 0.0, "safety_cleanliness": 0.0, "quality": 0.0},
            engine_error=isinstance(exc, runner.EngineBusy),
        )


from . import runner  # noqa: E402
