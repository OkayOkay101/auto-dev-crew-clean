---
name: security-audit
description: Audit code for OWASP vulnerabilities, sanitization issues, and secret leaks.
tags: [security, audit, vulnerability, hardening, secrets]
---

# Security Audit & Hardening

## Principles
1. Validate and sanitize all external user inputs before passing to filesystem, shell, or database operations.
2. Disallow path traversal sequences (`../`, `..\\`) on all file upload and read paths.
3. Prevent information disclosure: sanitize stack traces and internal file paths before presenting errors.
4. Ensure no hardcoded credentials, API keys, or private tokens exist in source code or committed examples.
