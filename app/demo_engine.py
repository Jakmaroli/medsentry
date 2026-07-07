"""
demo_engine.py — deterministic stand-in for app/agents.py.

This runs the *exact same* five-stage pipeline (intake -> safety ->
schedule -> optional caregiver share) by calling the exact same functions in
app/tools.py directly, in the same order the ADK SequentialAgent enforces —
just without an LLM in the loop. It exists so that:

  - Judges, CI, and first-time users can see the *whole* multi-agent
    workflow run end-to-end with zero setup and no API key.
  - app/tools.py (the part that actually matters for correctness and
    security) is exercised by the same tests whether MEDSENTRY_DEMO_MODE is
    true or false.
  - The "live" path in app/agents.py stays honest: it is a thin
    orchestration/reasoning layer over these same tools, not a different
    implementation that only gets tested when someone has a Gemini key.

Swap MEDSENTRY_DEMO_MODE=false (with GOOGLE_API_KEY set) to route the same
requests through real Gemini reasoning in app/agents.py instead.
"""

from __future__ import annotations

from typing import Any

from app import tools


def run_intake_pipeline(raw_medication_text: str, actor_role: str = "patient") -> dict[str, Any]:
    """Stage 1 -> 2 -> 3, deterministic version of app.agents.intake_pipeline."""
    parsed = tools.parse_medication_text(raw_medication_text, actor_role=actor_role)
    if parsed["status"] != "success":
        return {"status": "error", "stage": "intake", "message": parsed.get("message")}

    med_names = [m["name"] for m in parsed["medications"]]
    safety = tools.check_drug_interactions(med_names, actor_role=actor_role)
    if safety["status"] != "success":
        return {"status": "error", "stage": "safety", "message": safety.get("message")}

    # The demo dataset doesn't have real per-medication times unless the
    # caller supplies them (see run_from_seed below); default to a single
    # "as directed" slot per medication so the pipeline is still meaningful
    # for arbitrary pasted text.
    schedule_input = [{"display": m["display"], "times": ["as directed"]} for m in parsed["medications"]]
    schedule = tools.build_medication_schedule(schedule_input, actor_role=actor_role)
    if schedule["status"] != "success":
        return {"status": "error", "stage": "schedule", "message": schedule.get("message")}

    return {
        "status": "success",
        "parsed_medications": parsed["medications"],
        "safety_flags": safety["flags"],
        "disclaimer": safety["disclaimer"],
        "daily_schedule": schedule["timeline"],
    }


def run_from_seed(seed_patient: dict[str, Any], actor_role: str = "patient") -> dict[str, Any]:
    """Same pipeline, but starting from already-structured seed data (used by
    the CLI/dashboard demo so times-of-day are realistic instead of 'as
    directed')."""
    meds = seed_patient["medications"]
    med_names = [m["name"] for m in meds]

    safety = tools.check_drug_interactions(med_names, actor_role=actor_role)
    schedule = tools.build_medication_schedule(
        [{"display": m["display"], "times": m["times"]} for m in meds],
        actor_role=actor_role,
    )
    return {
        "status": "success",
        "parsed_medications": [{"name": m["name"], "display": m["display"], "recognized": True} for m in meds],
        "safety_flags": safety["flags"],
        "disclaimer": safety["disclaimer"],
        "daily_schedule": schedule["timeline"],
    }


def run_caregiver_share(pipeline_result: dict[str, Any], consent_flags: dict[str, bool],
                         actor_role: str = "caregiver") -> dict[str, Any]:
    """Deterministic version of CaregiverLiaisonAgent."""
    patient_summary = {
        "medications": pipeline_result.get("parsed_medications"),
        "schedule": pipeline_result.get("daily_schedule"),
        "interactions": pipeline_result.get("safety_flags"),
    }
    return tools.share_caregiver_update(patient_summary, consent_flags, actor_role=actor_role)
