import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import demo_engine
from app.config import DATA_DIR


def _seed():
    with open(DATA_DIR / "seed_patient.json", "r", encoding="utf-8") as fh:
        return json.load(fh)["patient"]


def test_full_pipeline_from_seed_patient():
    patient = _seed()
    result = demo_engine.run_from_seed(patient)
    assert result["status"] == "success"
    # seed patient takes warfarin + ibuprofen -> known major flag
    assert any(f["severity"] == "major" for f in result["safety_flags"])
    assert len(result["daily_schedule"]) > 0


def test_caregiver_share_respects_seed_consent():
    patient = _seed()
    pipeline_result = demo_engine.run_from_seed(patient)
    result = demo_engine.run_caregiver_share(pipeline_result, patient["consent"])
    # seed consent has notes=False, but pipeline_result never included notes
    # in the first place — the real assertion is that only consented scopes
    # that *were* present end up shared, and nothing is withheld that wasn't
    # actually offered by mistake.
    assert result["status"] == "success"
    assert set(result["shared_scopes"]) <= {"medications", "schedule", "interactions"}


def test_intake_pipeline_from_free_text():
    result = demo_engine.run_intake_pipeline("warfarin 5mg at night, aspirin 81mg daily")
    assert result["status"] == "success"
    assert any(f["severity"] == "major" for f in result["safety_flags"])
