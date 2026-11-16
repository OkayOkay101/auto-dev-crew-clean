import subprocess

import pytest

from auto_dev_crew import runner
from auto_dev_crew.redact import redact_secrets

PLACEHOLDER = "[PROTECTED_SECRET]"
HEX = "0123456789abcdef"

SECRETS = [
    "sk-" + "A1b2C3d4E5" * 4,
    "sk-or-v1-" + (HEX * 4),
    "AIza" + "Sy" * 17 + "A",
    "gsk_" + "aB3dE5gH7j" * 5 + "xY",
    "nvapi-" + (HEX * 4),
    "ghp_" + "aB3dE5gH7j" * 3 + "xYzAbC",
    "github_pat_" + "11AbCdEfG0" * 8 + "xY",
    "Bearer " + "abcDEF0123456789" * 2,
]


@pytest.mark.parametrize("secret", SECRETS)
def test_secret_is_redacted(secret):
    out = redact_secrets(f"key={secret} end")
    assert secret not in out
    assert PLACEHOLDER in out
    assert out.endswith(" end")


@pytest.mark.parametrize("text", [
    "api_key: ${GROQ_API_KEY}",
    'prefix "sk-" only',
    "sk-short",
    "สวัสดี นี่คือข้อความภาษาไทยปกติ ไม่มีความลับ",
    "Bearer token",
])
def test_ordinary_text_unchanged(text):
    assert redact_secrets(text) == text


def test_empty():
    assert redact_secrets("") == ""


def test_pr_body_redacted_before_gh(monkeypatch):
    seen = []

    def fake_run(cmd, **kw):
        seen.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="https://x/pr/1\n", stderr="")

    monkeypatch.setattr(runner, "run", fake_run)
    key = SECRETS[0]
    runner.create_pr("o/r", "main", "b", "t", f"leak {key} here", "ai")
    cmd = seen[0]
    body = cmd[cmd.index("--body") + 1]
    assert key not in body and PLACEHOLDER in body


def test_issue_comment_redacted_before_gh(monkeypatch):
    seen = []
    monkeypatch.setattr(runner, "run", lambda cmd, **kw: (seen.append(cmd), subprocess.CompletedProcess(cmd, 0, stdout="", stderr=""))[1])
    runner.gh("issue", "comment", "1", "--body", f"x {SECRETS[3]}")
    assert SECRETS[3] not in " ".join(seen[0])


def test_log_redacts(capsys, monkeypatch):
    monkeypatch.setattr(runner, "SLOTS_DIR", runner.SLOTS_DIR)
    runner.log(f"engine said {SECRETS[5]}")
    out = capsys.readouterr().out
    assert SECRETS[5] not in out and PLACEHOLDER in out
