---
name: audit-report
description: Show the patient (or an admin) a tail of the security audit trail — who accessed what, when, and whether it was allowed or denied. Use when the patient asks who has viewed their information. Never invoke on behalf of a caregiver or pharmacist role.
tool: app.tools.get_audit_log
cli: medsentry audit-log
---

# Audit Report

## When to use this skill
- The patient asks "who has looked at my medication information."
- An operator needs to review recent access for troubleshooting (admin role).

## Behavior contract
- Enforces role-based access control before returning anything: only
  `patient` and `admin` roles are allow-listed for the `audit_log` scope
  (see app/security.py `_SCOPE_MATRIX`). A caregiver or pharmacist request
  is denied, not filtered — the denial itself is the correct behavior, not
  an error to work around.
- Entries are redacted (names/DOB/phone patterns stripped) before they are
  ever written to the log, so the audit trail cannot itself become a new
  place where sensitive data leaks.

## Example
`get_audit_log(actor_role="caregiver")` -> `{"status": "error", ...}`.
`get_audit_log(actor_role="patient")` -> the last N events.
