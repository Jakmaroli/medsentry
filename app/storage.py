"""
storage.py — encrypted local persistence for MedSentry.

Patient records are stored in SQLite with the sensitive payload encrypted
at rest via app/security.encrypt_field (Fernet/AES). This is deliberately a
single-file, dependency-free store (no external database to stand up) so
the whole project stays trivial to run and deploy, while still
demonstrating a real encryption-at-rest pattern rather than an in-memory
toy. Swap this module for Cloud SQL / Firestore in a production
deployment — the encrypt/decrypt boundary stays the same either way.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from typing import Any, Iterator

from app.config import settings
from app.security import decrypt_field, encrypt_field

_SCHEMA = """
CREATE TABLE IF NOT EXISTS patient_records (
    patient_id TEXT PRIMARY KEY,
    encrypted_payload TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


@contextmanager
def _connect(db_path: str | None = None) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(db_path or settings.db_path)
    try:
        conn.execute(_SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


def save_patient_record(patient_id: str, record: dict[str, Any], db_path: str | None = None) -> None:
    """Encrypt `record` as a single JSON blob and upsert it by patient_id."""
    from datetime import datetime, timezone

    payload = encrypt_field(json.dumps(record))
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT INTO patient_records (patient_id, encrypted_payload, updated_at) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT(patient_id) DO UPDATE SET encrypted_payload=excluded.encrypted_payload, "
            "updated_at=excluded.updated_at",
            (patient_id, payload, datetime.now(timezone.utc).isoformat(timespec="seconds")),
        )


def load_patient_record(patient_id: str, db_path: str | None = None) -> dict[str, Any] | None:
    """Fetch and decrypt a patient record. Returns None if not found."""
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT encrypted_payload FROM patient_records WHERE patient_id = ?",
            (patient_id,),
        ).fetchone()
    if row is None:
        return None
    return json.loads(decrypt_field(row[0]))


def list_patient_ids(db_path: str | None = None) -> list[str]:
    with _connect(db_path) as conn:
        rows = conn.execute("SELECT patient_id FROM patient_records").fetchall()
    return [r[0] for r in rows]
