"""
agents.py — MedSentry's multi-agent system, built with Google's Agent
Development Kit (ADK).

Five agents, each with one job and least-privilege tool access, mirroring
how a real care team divides responsibility instead of one monolithic
prompt trying to do everything:

    MedSentryOrchestrator (root, LlmAgent)
      ├─ IntakePipeline (SequentialAgent — deterministic, always runs in order)
      │    ├─ IntakeAgent        parses free-text meds -> structured list
      │    ├─ SafetyAgent        checks the list for drug interactions
      │    └─ SchedulerAgent     turns the list into a daily dosing timeline
      └─ CaregiverLiaisonAgent   (AgentTool, invoked on demand)
           builds a consent-filtered update for the family circle

Why a SequentialAgent for intake/safety/scheduling instead of pure LLM
delegation? Those three steps must always run in that exact order and must
never be skipped (you cannot schedule medications you haven't safety-
checked) — ADK's workflow agents make that a structural guarantee rather
than something we *hope* the model chooses to do. The caregiver step, by
contrast, is a genuinely separate user intent ("tell my daughter"), so the
root agent invokes it explicitly as an AgentTool and stays in the loop to
combine results — see docs/SPEC.md for the fuller rationale.

This module is only imported when live mode is active (a real
GOOGLE_API_KEY is configured). In DEMO_MODE — the default, zero-setup path —
app/demo_engine.py runs the identical pipeline with deterministic logic
instead of Gemini calls, so the whole system is inspectable and testable
without any credentials. Both paths call the exact same functions in
app/tools.py, so "demo" and "live" are two runners over one real
implementation, not two different systems.
"""

from __future__ import annotations

from app.config import settings
from app.tools import (
    build_medication_schedule,
    check_drug_interactions,
    get_audit_log,
    lookup_medication_info,
    parse_medication_text,
    share_caregiver_update,
)

MODEL = settings.gemini_model  # e.g. "gemini-flash-latest" — see app/config.py


def build_root_agent():
    """Construct MedSentry's ADK agent tree. Imports google.adk lazily so
    that DEMO_MODE (the default) never requires the package to be installed
    at all, and so a missing/incompatible ADK version fails with one clear
    error here rather than breaking module import for the whole app.
    """
    try:
        from google.adk.agents import LlmAgent, SequentialAgent
        from google.adk.tools.agent_tool import AgentTool
    except ImportError as exc:  # pragma: no cover - exercised only in live mode
        raise RuntimeError(
            "google-adk is required for live mode. Install it with "
            "`pip install google-adk` (see requirements.txt), or leave "
            "MEDSENTRY_DEMO_MODE=true to use the offline engine instead."
        ) from exc

    # --- Stage 1: Intake — free text -> structured medication list ---
    intake_agent = LlmAgent(
        name="IntakeAgent",
        model=MODEL,
        description="Parses a patient's free-text medication list into structured entries.",
        instruction=(
            "You turn a patient's free-text medication list into structured "
            "entries by calling parse_medication_text. Always call the tool; "
            "never guess the structure yourself. Pass along the user's exact "
            "wording as `raw_text`. Report any medication the tool marks as "
            "unrecognized so the patient can confirm the spelling."
        ),
        tools=[parse_medication_text],
        output_key="parsed_medications",
    )

    # --- Stage 2: Safety — structured list -> interaction flags ---
    safety_agent = LlmAgent(
        name="SafetyAgent",
        model=MODEL,
        description="Checks a medication list for known drug-drug interactions.",
        instruction=(
            "Using the medications in state['parsed_medications'], call "
            "check_drug_interactions with the medication names. Summarize "
            "any flags clearly by severity (major first) and always include "
            "the tool's disclaimer verbatim. Never soften or omit a major "
            "flag, and never provide dosing advice yourself — only report "
            "what the tool returns and recommend confirming with a "
            "pharmacist or physician."
        ),
        tools=[check_drug_interactions, lookup_medication_info],
        output_key="safety_flags",
    )

    # --- Stage 3: Scheduling — structured list -> daily timeline ---
    scheduler_agent = LlmAgent(
        name="SchedulerAgent",
        model=MODEL,
        description="Builds a same-day dosing schedule from a medication list.",
        instruction=(
            "Using the medications in state['parsed_medications'], call "
            "build_medication_schedule to produce a chronological timeline. "
            "Present it as a simple time-ordered list the patient can follow "
            "today."
        ),
        tools=[build_medication_schedule],
        output_key="daily_schedule",
    )

    # Deterministic pipeline: always intake -> safety -> schedule, in that
    # fixed order, regardless of what the model 'feels' like doing.
    intake_pipeline = SequentialAgent(
        name="IntakePipeline",
        description=(
            "Runs a new or updated medication list through parsing, safety "
            "checking, and scheduling, in that strict order."
        ),
        sub_agents=[intake_agent, safety_agent, scheduler_agent],
    )

    # --- Caregiver liaison — consent-gated, invoked on demand ---
    caregiver_agent = LlmAgent(
        name="CaregiverLiaisonAgent",
        model=MODEL,
        description=(
            "Prepares a consent-filtered update for the patient's family "
            "caregiver circle, and can show the patient their own audit log."
        ),
        instruction=(
            "When asked to share an update with a caregiver, assemble a "
            "patient_summary from state (parsed_medications, safety_flags, "
            "daily_schedule) and call share_caregiver_update with the "
            "patient's consent_flags. NEVER fabricate consent — only pass "
            "through the consent_flags you were given. Clearly tell the "
            "caregiver which scopes were withheld and why (patient has not "
            "consented), rather than silently omitting them. If the patient "
            "themself asks who has accessed their data, call get_audit_log "
            "instead — do not call it on behalf of a caregiver, who is not "
            "authorized to see it."
        ),
        tools=[share_caregiver_update, get_audit_log],
    )

    # --- Root orchestrator ---
    # The pipeline and the caregiver agent are exposed as AgentTools (not
    # permanent sub_agents) so the root stays "in the room" after each call
    # and can compose them for a request that spans both, e.g. "add this new
    # prescription and then let my daughter know" -> intake tool, then
    # caregiver tool, in one turn.
    root_agent = LlmAgent(
        name="MedSentryOrchestrator",
        model=MODEL,
        description="Secure family medication concierge — routes requests to specialist sub-agents.",
        instruction=(
            "You are MedSentry, a calm and careful medication concierge for "
            "a patient and their family caregivers. When the user provides "
            "or updates a medication list, call the process_medications "
            "tool. When they ask about a specific medication's interactions, "
            "call lookup_medication_info directly. When they ask you to "
            "update or notify a caregiver, call the notify_caregiver tool. "
            "Always be explicit about what is shared vs. withheld and why. "
            "Never invent medical advice beyond what the tools return — you "
            "are a safety-and-logistics layer, not a physician, and you say "
            "so when it matters."
        ),
        tools=[
            lookup_medication_info,
            AgentTool(agent=intake_pipeline),
            AgentTool(agent=caregiver_agent),
        ],
    )
    return root_agent


def build_runner():
    """Convenience helper: wraps build_root_agent() in an ADK Runner backed
    by an in-memory session service, ready for `await runner.run_async(...)`.
    Only called from live mode (see app/web.py and app/cli.py).
    """
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService

    root_agent = build_root_agent()
    return Runner(
        app_name="medsentry",
        agent=root_agent,
        session_service=InMemorySessionService(),
    )
