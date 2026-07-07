"""
web.py — FastAPI backend for the MedSentry dashboard.

Serves the static single-page dashboard (static/index.html) and a small
JSON API it calls. Runs the same demo_engine / tools pipeline the CLI uses —
see app/cli.py and app/demo_engine.py for the underlying logic; this module
is purely a thin HTTP surface over it; plus /health for load-balancer /
Cloud Run readiness checks (see deploy/cloudrun.sh).
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import demo_engine, tools
from app.config import BASE_DIR, DATA_DIR, settings
from app.security import Role

app = FastAPI(title="MedSentry", version="1.0.0")

# CORS is wide open here because this is a demo dashboard with no cookies /
# session auth to protect; a production deployment behind real user auth
# should restrict allow_origins to its own domain.
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

STATIC_DIR = BASE_DIR / "static"


def _load_seed() -> dict:
    with open(DATA_DIR / "seed_patient.json", "r", encoding="utf-8") as fh:
        return json.load(fh)["patient"]


@app.get("/health")
def health() -> dict:
    """Liveness/readiness probe for Cloud Run / any orchestrator."""
    return {"status": "ok", "mode": "demo" if settings.demo_mode else "live"}


@app.get("/api/mode")
def mode() -> dict:
    return {
        "demo_mode": settings.demo_mode,
        "model": settings.gemini_model,
        "live_mode_available": (not settings.demo_mode) and bool(settings.google_api_key),
    }


@app.get("/api/summary")
def summary() -> dict:
    patient = _load_seed()
    result = demo_engine.run_from_seed(patient, actor_role=Role.PATIENT.value)
    return {
        "patient_name": patient["display_name"],
        "medications": result["parsed_medications"],
        "safety_flags": result["safety_flags"],
        "disclaimer": result["disclaimer"],
        "daily_schedule": result["daily_schedule"],
        "caregiver_circle": patient["caregiver_circle"],
        "consent": patient["consent"],
    }


@app.get("/api/caregiver-update")
def caregiver_update() -> dict:
    patient = _load_seed()
    pipeline_result = demo_engine.run_from_seed(patient, actor_role=Role.PATIENT.value)
    result = demo_engine.run_caregiver_share(pipeline_result, patient["consent"], actor_role=Role.CAREGIVER.value)
    return result


@app.get("/api/audit-log")
def audit_log_endpoint(role: str = Query("patient", description="Try 'caregiver' to see RBAC deny it.")) -> dict:
    # First generate some activity so the log isn't empty on a fresh boot.
    patient = _load_seed()
    demo_engine.run_from_seed(patient, actor_role=Role.PATIENT.value)

    result = tools.get_audit_log(actor_role=role, n=25)
    if result["status"] != "success":
        raise HTTPException(status_code=403, detail=result["message"])
    return result


# Static assets (CSS/JS) and the SPA shell itself.
app.mount("/assets", StaticFiles(directory=str(STATIC_DIR)), name="assets")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(str(STATIC_DIR / "index.html"))
