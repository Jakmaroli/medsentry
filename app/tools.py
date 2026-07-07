"""
tools.py — MedSentry's tool layer.

These plain Python functions are the single source of truth for what
MedSentry can *do*. They are reused in three places without modification:
  1. As ADK function tools        -> app/agents.py
  2. As an MCP server's tools      -> app/mcp_server.py
  3. As the deterministic engine   -> app/demo_engine.py / app/cli.py

Every function follows the same shape ADK expects: a clear docstring (the
LLM's only view into "when should I call this"), type hints, and a
dict return with a "status" key. Every function also runs its access
checks and writes to the audit trail *before* touching patient data, so a
denial never leaks the data it was supposed to protect.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from app.config import DATA_DIR
from app.security import (
    AccessDenied,
    Role,
    assert_consent,
    audit_log,
    redact,
    require_scope,
    sanitize_free_text,
)

with open(DATA_DIR / "interactions.json", "r", encoding="utf-8") as _fh:
    _INTERACTIONS = json.load(_fh)

_PAIR_INDEX: dict[frozenset[str], dict[str, Any]] = {
    frozenset({p["a"], p["b"]}): p for p in _INTERACTIONS["pairs"]
}

_SEVERITY_RANK = {"minor": 0, "moderate": 1, "major": 2}


def _normalize(name: str) -> str:
    return name.strip().lower().replace(" ", "_")


# --------------------------------------------------------------------------
# Tool 1 — Safety check (drug-drug interaction screening)
# --------------------------------------------------------------------------

def check_drug_interactions(medications: list[str], actor_role: str = "patient") -> dict[str, Any]:
    """Screen a medication list for known drug-drug interactions.

    Use this any time a medication list changes (a new prescription is added,
    or before answering any question about whether it's safe to combine two
    medications). Always surfaces the built-in safety disclaimer.

    Args:
        medications: List of medication names, e.g. ["warfarin", "aspirin"].
        actor_role: The role of whoever triggered this check (patient,
            caregiver, pharmacist, admin) — used only for audit logging.

    Returns:
        dict: {"status": "success", "flags": [...], "disclaimer": str}
        where each flag has severity/mechanism/risk/action, sorted by
        descending severity (major first).
    """
    try:
        require_scope(Role(actor_role), "interactions")
    except (AccessDenied, ValueError) as exc:
        audit_log.record(actor_role, "check_drug_interactions", "interactions", "denied", str(exc))
        return {"status": "error", "message": str(exc)}

    normalized = [_normalize(m) for m in medications]
    flags = []
    for i in range(len(normalized)):
        for j in range(i + 1, len(normalized)):
            pair = frozenset({normalized[i], normalized[j]})
            hit = _PAIR_INDEX.get(pair)
            if hit:
                flags.append(hit)
    flags.sort(key=lambda f: _SEVERITY_RANK.get(f["severity"], 0), reverse=True)

    audit_log.record(
        actor_role, "check_drug_interactions", "interactions", "allowed",
        f"checked {len(normalized)} medications, {len(flags)} flag(s)",
    )
    return {
        "status": "success",
        "checked": normalized,
        "flags": flags,
        "flag_count": len(flags),
        "disclaimer": _INTERACTIONS["_disclaimer"],
    }


# --------------------------------------------------------------------------
# Tool 2 — Schedule builder
# --------------------------------------------------------------------------

def build_medication_schedule(medications: list[dict[str, Any]], actor_role: str = "patient") -> dict[str, Any]:
    """Build a same-day dosing schedule from a structured medication list.

    Use this to answer "what do I take and when" or to generate today's
    reminder timeline. Input medications should already be parsed into
    {"display": str, "times": [\"HH:MM\", ...]} form (see IntakeAgent).

    Args:
        medications: List of {"display": str, "times": [str, ...]} entries.
        actor_role: Role triggering the request, for audit logging.

    Returns:
        dict: {"status": "success", "timeline": [{"time": "08:00",
        "items": [...]}]} sorted chronologically.
    """
    try:
        require_scope(Role(actor_role), "schedule")
    except (AccessDenied, ValueError) as exc:
        audit_log.record(actor_role, "build_medication_schedule", "schedule", "denied", str(exc))
        return {"status": "error", "message": str(exc)}

    slots: dict[str, list[str]] = {}
    for med in medications:
        for t in med.get("times", []):
            slots.setdefault(t, []).append(med.get("display", med.get("name", "medication")))

    timeline = [{"time": t, "items": items} for t, items in sorted(slots.items())]
    audit_log.record(actor_role, "build_medication_schedule", "schedule", "allowed", f"{len(timeline)} slot(s)")
    return {"status": "success", "timeline": timeline}


# --------------------------------------------------------------------------
# Tool 3 — Medication lookup
# --------------------------------------------------------------------------

def lookup_medication_info(name: str, actor_role: str = "patient") -> dict[str, Any]:
    """Look up which known interactions exist for a single medication name.

    Use this when the user asks "what does X interact with" about one
    medication, without necessarily comparing it to their full list.

    Args:
        name: Medication name, e.g. "warfarin".
        actor_role: Role triggering the request, for audit logging.

    Returns:
        dict: {"status": "success", "medication": str, "known_interactions": [...]}
    """
    try:
        require_scope(Role(actor_role), "medications")
    except (AccessDenied, ValueError) as exc:
        audit_log.record(actor_role, "lookup_medication_info", "medications", "denied", str(exc))
        return {"status": "error", "message": str(exc)}

    norm = _normalize(name)
    hits = [p for key, p in _PAIR_INDEX.items() if norm in key]
    audit_log.record(actor_role, "lookup_medication_info", "medications", "allowed", norm)
    return {"status": "success", "medication": norm, "known_interactions": hits}


# --------------------------------------------------------------------------
# Tool 4 — Caregiver update (consent-gated)
# --------------------------------------------------------------------------

def share_caregiver_update(
    patient_summary: dict[str, Any],
    consent_flags: dict[str, bool],
    actor_role: str = "caregiver",
) -> dict[str, Any]:
    """Generate a caregiver-facing update, honoring the patient's consent settings.

    Use this when a caregiver asks "how is [patient] doing with their
    medications" or similar. This NEVER includes a scope the patient has not
    explicitly consented to share (e.g. free-text clinical notes), and every
    call — allowed or denied — is written to the audit trail.

    Args:
        patient_summary: Dict that may include "medications", "schedule",
            "interactions", "notes" keys.
        consent_flags: The patient's per-scope consent settings.
        actor_role: Role of whoever is requesting the update.

    Returns:
        dict: {"status": "success", "shared_scopes": [...], "update": {...}}
    """
    shared: dict[str, Any] = {}
    denied_scopes: list[str] = []
    for scope in ("medications", "schedule", "interactions", "notes"):
        if scope not in patient_summary:
            continue
        try:
            assert_consent(consent_flags, scope)
            shared[scope] = patient_summary[scope]
        except AccessDenied:
            denied_scopes.append(scope)

    audit_log.record(
        actor_role, "share_caregiver_update", "caregiver_share", "allowed",
        f"shared={list(shared.keys())} withheld={denied_scopes}",
    )
    return {
        "status": "success",
        "shared_scopes": list(shared.keys()),
        "withheld_scopes": denied_scopes,
        "update": shared,
    }


# --------------------------------------------------------------------------
# Tool 5 — Audit log access (RBAC: patient/admin only)
# --------------------------------------------------------------------------

def get_audit_log(actor_role: str = "patient", n: int = 20) -> dict[str, Any]:
    """Retrieve the most recent audit trail entries.

    Use this when the user (patient or admin) asks "who has accessed my
    information" or "show me the security log." Caregivers and pharmacists
    are denied by design — the audit trail is the patient's own oversight
    tool, not something shared by default.

    Args:
        actor_role: Role requesting the log.
        n: How many recent entries to return.

    Returns:
        dict: {"status": "success", "events": [...]}
    """
    try:
        require_scope(Role(actor_role), "audit_log")
    except (AccessDenied, ValueError) as exc:
        return {"status": "error", "message": str(exc)}
    return {"status": "success", "events": audit_log.tail(n)}


# --------------------------------------------------------------------------
# Tool 6 — Intake parsing helper (pure/local — no LLM required, used as a
# deterministic fallback and as a validation step even in live mode)
# --------------------------------------------------------------------------

_KNOWN_MED_NAMES = {p["a"] for p in _INTERACTIONS["pairs"]} | {p["b"] for p in _INTERACTIONS["pairs"]}


def parse_medication_text(raw_text: str, actor_role: str = "patient") -> dict[str, Any]:
    """Parse a free-text medication list into structured entries.

    Use this first, on any raw text the user pastes in (e.g. "warfarin 5mg
    at night, metformin 500mg twice a day"), before scheduling or safety
    checks. Applies input sanitization to guard against prompt-injection
    text hidden inside a pasted note.

    Args:
        raw_text: Free-text medication list from the user.
        actor_role: Role of the submitter, for audit logging.

    Returns:
        dict: {"status": "success", "medications": [{"name": str,
        "display": str, "recognized": bool}, ...]}
    """
    try:
        clean = sanitize_free_text(raw_text)
    except ValueError as exc:
        audit_log.record(actor_role, "parse_medication_text", "medications", "denied", str(exc))
        return {"status": "error", "message": str(exc)}

    entries = []
    for chunk in clean.replace("\n", ",").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        first_word = _normalize(chunk.split(" ")[0])
        entries.append({
            "name": first_word,
            "display": chunk,
            "recognized": first_word in _KNOWN_MED_NAMES,
        })

    audit_log.record(actor_role, "parse_medication_text", "medications", "allowed", f"{len(entries)} entrie(s)")
    return {"status": "success", "medications": entries}
