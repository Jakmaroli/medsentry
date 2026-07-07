---
name: check-interactions
description: Screen a medication list for known drug-drug interactions and report severity-ranked safety flags. Use whenever a medication list is created, changed, or a new prescription is added, or when the user asks whether two medications are safe to combine.
tool: app.tools.check_drug_interactions
cli: medsentry check-safety
---

# Check Interactions

## When to use this skill
- A patient's medication list changes (add, remove, dose change).
- Before answering any "is it safe to take X with Y" question.
- Before building or updating a dosing schedule (safety must run first).

## Behavior contract
- Always calls the underlying tool rather than answering from memory —
  interaction data changes and must come from the vetted dataset.
- Always surfaces the tool's disclaimer verbatim: this is decision support,
  not a substitute for a pharmacist or physician.
- Never downgrades or omits a "major" severity flag.
- Sorts flags major -> moderate -> minor so the most urgent risk is first.

## Example
Input: `["warfarin", "aspirin", "metformin"]`
Output: one `major` flag (warfarin + aspirin, bleeding risk), zero flags
involving metformin, plus the disclaimer.
