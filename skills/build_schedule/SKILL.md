---
name: build-schedule
description: Turn a structured medication list into a same-day, time-ordered dosing timeline. Use after a safety check has run, when the user asks what to take and when, or to generate today's reminder timeline.
tool: app.tools.build_medication_schedule
cli: medsentry schedule
---

# Build Schedule

## When to use this skill
- Immediately after check-interactions has cleared a medication list.
- When the user asks "what do I take today" or "what's next."
- When generating the dashboard's daily timeline view.

## Behavior contract
- Never runs on a medication list that hasn't been through check-interactions
  in the same pipeline invocation — scheduling before safety-checking is a
  process ordering bug, not a style choice (see app/agents.py IntakePipeline).
- Groups medications by time slot and returns them in chronological order.
- Does not invent dose timing the patient/prescriber did not specify.

## Example
Input: `[{"display": "Metformin 500mg", "times": ["08:00", "19:00"]}]`
Output: two timeline entries, 08:00 and 19:00, each listing Metformin.
