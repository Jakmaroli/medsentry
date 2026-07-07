"""
security.py — MedSentry's security & trust layer.

Concierge Agents track is explicit that this is the bar: "safe and secure
agents... keeps personal information safe and secure." This module is where
that promise is implemented, not just claimed. It maps to the course's Day 4
"quality & security" pillars (guardrails, sandboxing, human-in-the-loop,
supply-chain hygiene) with seven concrete, testable mechanisms:

  1. Encryption at rest      -> encrypt_field / decrypt_field
  2. Least-privilege RBAC    -> require_scope / Role
  3. Consent-gated sharing   -> assert_consent
  4. PII redaction           -> redact
  5. Full audit trail        -> AuditLog
  6. Input sanitization      -> sanitize_free_text (guards against prompt
                                 injection hidden in a pasted medication list)
  7. Supply-chain hygiene    -> see requirements.txt (pinned, hash-checkable
                                 versions) + docs/SPEC.md, defends against
                                 "slopsquatting" of hallucinated package names.

None of this is theatre: every function below is exercised by tests/test_security.py.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Iterable

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

# --------------------------------------------------------------------------
# 1. Encryption at rest
# --------------------------------------------------------------------------
# Every patient record is encrypted before it touches disk (app/storage.py
# never writes a plaintext field). Key comes from the environment; MedSentry
# refuses to silently invent a "convenient" key for real data — it only
# auto-generates an ephemeral one while running in DEMO_MODE with seeded,
# fictional data, and prints a loud warning so nobody mistakes it for
# production behavior.

_ephemeral_key: bytes | None = None


def _get_key() -> bytes:
    global _ephemeral_key
    if settings.secret_key:
        key = settings.secret_key.encode()
        # Validate it's a real Fernet key early, so misconfiguration fails
        # loudly at startup instead of silently corrupting data later.
        Fernet(key)
        return key
    if not settings.demo_mode:
        raise RuntimeError(
            "MEDSENTRY_SECRET_KEY is not set. Refusing to run in live mode "
            "without a real encryption key — set it via your secret manager, "
            "never hardcode it. See .env.example."
        )
    if _ephemeral_key is None:
        _ephemeral_key = Fernet.generate_key()
    return _ephemeral_key


def encrypt_field(value: str) -> str:
    """Encrypt a single string field for storage. Returns a urlsafe token."""
    f = Fernet(_get_key())
    return f.encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_field(token: str) -> str:
    """Decrypt a field previously produced by encrypt_field."""
    f = Fernet(_get_key())
    try:
        return f.decrypt(token.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("Could not decrypt field — wrong key or corrupted data.") from exc


def encrypt_record(record: dict[str, Any], fields: Iterable[str]) -> dict[str, Any]:
    """Return a copy of `record` with the given field names encrypted in place."""
    out = dict(record)
    for name in fields:
        if name in out and out[name] is not None:
            out[name] = encrypt_field(json.dumps(out[name]) if not isinstance(out[name], str) else out[name])
    return out


def decrypt_record(record: dict[str, Any], fields: Iterable[str]) -> dict[str, Any]:
    out = dict(record)
    for name in fields:
        if name in out and out[name] is not None:
            decrypted = decrypt_field(out[name])
            try:
                out[name] = json.loads(decrypted)
            except (json.JSONDecodeError, TypeError):
                out[name] = decrypted
    return out


# --------------------------------------------------------------------------
# 2. Least-privilege role-based access control
# --------------------------------------------------------------------------

class Role(str, Enum):
    PATIENT = "patient"       # full access to their own record
    CAREGIVER = "caregiver"   # only what the patient has explicitly shared
    PHARMACIST = "pharmacist" # medication + interaction data only, no notes
    ADMIN = "admin"           # operational access, still audited


class AccessDenied(PermissionError):
    pass


# Explicit allow-list per role, per data scope. Anything not listed is denied
# by default (fail-closed), not just "not shown in the UI."
_SCOPE_MATRIX: dict[Role, set[str]] = {
    Role.PATIENT: {"medications", "schedule", "interactions", "notes", "audit_log", "consent"},
    Role.CAREGIVER: {"medications", "schedule", "interactions"},  # notes/audit withheld unless consented
    Role.PHARMACIST: {"medications", "interactions"},
    Role.ADMIN: {"audit_log"},
}


def require_scope(role: Role, scope: str) -> None:
    """Raise AccessDenied unless `role` is allow-listed for `scope`."""
    if scope not in _SCOPE_MATRIX.get(role, set()):
        raise AccessDenied(f"Role '{role.value}' is not permitted to access scope '{scope}'.")


# --------------------------------------------------------------------------
# 3. Consent-gated sharing
# --------------------------------------------------------------------------

def assert_consent(consent_flags: dict[str, bool], scope: str) -> None:
    """Raise AccessDenied if the patient has not explicitly opted in to
    sharing `scope` with their caregiver circle. Default is DENY — a missing
    key is treated as "not consented," never as "not yet asked = ok."
    """
    if not consent_flags.get(scope, False):
        raise AccessDenied(
            f"Sharing '{scope}' with the caregiver circle requires explicit "
            f"patient consent, which has not been granted."
        )


# --------------------------------------------------------------------------
# 4. PII redaction (for logs, telemetry, and caregiver summaries)
# --------------------------------------------------------------------------

_NAME_PATTERN = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z]\.?)?\s+[A-Z][a-z]+)\b")
_DOB_PATTERN = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_PHONE_PATTERN = re.compile(r"\b(?:\+?\d{1,3}[-.\s]?)?\(?\d{3,4}\)?[-.\s]?\d{3,4}[-.\s]?\d{3,4}\b")


def redact(text: str, extra_terms: Iterable[str] = ()) -> str:
    """Best-effort redaction of names, DOBs, and phone-like numbers before
    anything is written to a log file or shipped to observability/tracing.
    `extra_terms` lets a caller redact known-sensitive values (e.g. the
    specific patient's real name) even where the pattern rules would miss it.
    """
    redacted = _DOB_PATTERN.sub("[DOB REDACTED]", text)
    redacted = _PHONE_PATTERN.sub("[PHONE REDACTED]", redacted)
    redacted = _NAME_PATTERN.sub("[NAME REDACTED]", redacted)
    for term in extra_terms:
        if term:
            redacted = redacted.replace(term, "[REDACTED]")
    return redacted


# --------------------------------------------------------------------------
# 5. Full audit trail
# --------------------------------------------------------------------------

@dataclass
class AuditEvent:
    event_id: str
    timestamp: str
    actor_role: str
    action: str
    scope: str
    outcome: str  # "allowed" | "denied" | "error"
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "timestamp": self.timestamp,
            "actor_role": self.actor_role,
            "action": self.action,
            "scope": self.scope,
            "outcome": self.outcome,
            "detail": self.detail,
        }


class AuditLog:
    """Append-only, in-memory + on-disk audit trail. Every tool call in
    app/tools.py records one of these, regardless of allow/deny outcome, so
    "who accessed what, when, and whether it was permitted" is always
    reconstructable — this is what makes consent-gating and RBAC verifiable
    rather than just asserted.
    """

    def __init__(self, path: str | None = None) -> None:
        self._events: list[AuditEvent] = []
        self._path = path

    def record(self, actor_role: str, action: str, scope: str, outcome: str, detail: str = "") -> AuditEvent:
        event = AuditEvent(
            event_id=uuid.uuid4().hex[:12],
            timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            actor_role=actor_role,
            action=action,
            scope=scope,
            outcome=outcome,
            # Audit details are redacted before they're ever persisted.
            detail=redact(detail),
        )
        self._events.append(event)
        if self._path:
            with open(self._path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(event.to_dict()) + "\n")
        return event

    def tail(self, n: int = 20) -> list[dict[str, Any]]:
        return [e.to_dict() for e in self._events[-n:]]

    def all(self) -> list[dict[str, Any]]:
        return [e.to_dict() for e in self._events]


audit_log = AuditLog()  # process-wide singleton used by app/tools.py


# --------------------------------------------------------------------------
# 6. Input sanitization / prompt-injection guardrail
# --------------------------------------------------------------------------

_INJECTION_MARKERS = (
    "ignore previous instructions",
    "ignore the above",
    "disregard prior",
    "system prompt",
    "you are now",
    "act as",
    "reveal your instructions",
    "print your prompt",
)


def sanitize_free_text(text: str, max_len: int = 2000) -> str:
    """Free-text medication lists are the one place a user (or a malicious
    pasted document) gets to inject arbitrary text into an LLM prompt. This:
      - hard-truncates length (denial-of-service / cost guard),
      - strips characters used for delimiter/role-confusion attacks,
      - flags (does not silently rewrite) common injection phrasing so the
        calling agent can refuse or ask for confirmation instead of
        quietly complying with embedded instructions.
    This is a defense-in-depth guardrail, not a substitute for treating all
    tool output as untrusted data — see docs/SPEC.md.
    """
    text = text[:max_len]
    # Strip characters commonly used to fake a new turn/role boundary.
    stripped = re.sub(r"[<>{}]|```", " ", text)
    lowered = stripped.lower()
    for marker in _INJECTION_MARKERS:
        if marker in lowered:
            raise ValueError(
                "Input rejected: contains phrasing consistent with a prompt-"
                "injection attempt. Please rephrase using only medication "
                "names, doses, and schedule information."
            )
    return stripped.strip()


# --------------------------------------------------------------------------
# Helper: stable pseudonymous hash, useful for joining records across a
# demo without ever storing/logging the real identifier in the clear.
# --------------------------------------------------------------------------

def pseudonymize(identifier: str) -> str:
    return hashlib.sha256(identifier.encode("utf-8")).hexdigest()[:16]
