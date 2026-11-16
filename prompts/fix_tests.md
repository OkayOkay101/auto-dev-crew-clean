# Test Remediation Protocol

## Workflow
1. **Root Cause Analysis**: Analyze the error traceback carefully. Fix root causes, not symptoms. NEVER remove or skip existing tests.
2. **Fix & Verify**: Update the code (or newly added test if flawed), re-run tests until all pass.
3. **Safe Fallback**: If unable to fix safely, revert all changes (`git checkout -- .` and remove untracked files), then output `NO_ACTION`.
4. **Result Delivery**: Overwrite `{{result_path}}` with standard output JSON format (`status`, `title_th`, `summary_th`, `commit_message`).

---

# Failure Output & Traceback
{{test_output}}

## Your changes so far
Your earlier edits in this job (`git diff HEAD`, may be truncated). Build on them. Do not redo them, and revert them only if they caused the failure.
```diff
{{previous_diff}}
```

Important: Ensure the JSON file is completely valid and follows the Output Schema defined in the primary instructions.
