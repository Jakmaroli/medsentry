---
name: share-caregiver-update
description: Prepare a consent-filtered update for a patient's family caregiver circle. Use only when explicitly asked to notify, update, or inform a caregiver — never proactively, and never include a data scope the patient has not consented to share.
tool: app.tools.share_caregiver_update
cli: medsentry share-update
---

# Share Caregiver Update

## When to use this skill
- The patient (or an authenticated caregiver) explicitly asks for an update
  to be prepared for the family circle.
- Never run this automatically as a side effect of another skill.

## Behavior contract
- Reads `consent_flags` from the patient's own record — never accepts a
  caller-supplied override that would grant access the patient hasn't
  actually configured (see app/security.py `assert_consent`, fail-closed).
- Every call is written to the audit trail, whether scopes are shared or
  withheld, allowed or denied.
- The response always lists which scopes were withheld and why, so
  "silently missing information" never looks like "nothing happened."

## Example
Patient consent: `{"medications": true, "schedule": true, "notes": false}`.
A request that includes `notes` in the summary returns `notes` in
`withheld_scopes`, not in `update`.
