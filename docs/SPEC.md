# SPEC.md — MedSentry design spec

Written before the bulk of the implementation, in the course's Day 5
spec-driven-development style: decide the contract, then build to it.

## Problem
Patients on multiple medications (common for older adults and anyone with a
chronic condition) face two compounding risks: (1) dangerous drug-drug
interactions that no single prescriber may catch across pharmacies, and
(2) family caregivers who are either shut out of the loop entirely or given
uncontrolled access to sensitive health data. Existing pill-reminder apps
set alarms; they don't reason about safety, and they don't treat privacy as
a first-class design constraint.

## Why a multi-agent system (not one prompt)
Four distinct responsibilities, four distinct trust boundaries:
parsing free text is a data-extraction problem; interaction checking is a
safety-critical lookup that must never be skipped or reordered; scheduling
is a scheduling problem; caregiver sharing is an access-control problem. A
single agent handling all four in one prompt has no structural way to
guarantee "safety check always runs before scheduling" or "this role never
sees that field" — those become properties of prompt wording, which is not
a guarantee. Splitting them into agents with distinct tool access lets the
*system*, not the prompt, enforce the ordering and the boundary.

## Non-negotiable requirements (drove every design decision below)
1. Runs with zero configuration and no API key (DEMO_MODE default).
2. No plaintext patient data touches disk, ever.
3. A caregiver can never see a scope the patient hasn't consented to,
   even if they ask the agent nicely, even if the tool is called with a
   caregiver-supplied consent override.
4. Every access — allowed or denied — is auditable after the fact.
5. Same tool implementation whether invoked by the CLI, the dashboard, the
   ADK agents, or an external MCP client — no duplicated, divergent logic.

## Explicitly out of scope for this MVP
- Real clinical interaction API integration (data/interactions.json is a
  small curated stand-in — see its `_disclaimer` field).
- Multi-patient / multi-tenant auth (single demo patient, role simulated
  via a function argument rather than a real login system).
- Push notifications / actual SMS-to-caregiver delivery.

## Supply-chain hygiene (Day 4)
requirements.txt pins exact versions rather than ranges. AI-assisted coding
tools can hallucinate plausible-looking package names that don't exist —
attackers register those names ("slopsquatting") and ship malware to
whoever's assistant "helpfully" suggested them. Pinning to versions we
verified exist on PyPI at build time turns that risk into a visible diff on
the next intentional bump, not a silent supply-chain compromise.
