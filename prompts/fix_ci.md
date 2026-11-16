# CI Remediation Protocol

## Workflow
1. **Root Cause Analysis**: The required CI checks on this pull request failed. Read the log below, find the root cause, and fix the code or the test that caused it. Fix root causes, not symptoms. NEVER delete tests, skip them, or weaken assertions to make CI pass.
2. **Fix & Verify**: Make the smallest change that resolves the failure. Re-run the relevant local tests when you can.
3. **Safe Fallback**: If the failure is outside this repository (for example a missing secret, a flaky external service, or a runner problem), make no changes and output `NO_ACTION`.
4. **Result Delivery**: Overwrite `{{result_path}}` with standard output JSON format (`status`, `title_th`, `summary_th`, `commit_message`).

---

# Failed CI Log (redacted)
```
{{ci_log}}
```

Important: Ensure the JSON file is completely valid and follows the Output Schema defined in the primary instructions.
