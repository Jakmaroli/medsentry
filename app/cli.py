"""
cli.py — the MedSentry Agents CLI.

Each subcommand maps 1:1 to a persistent Agent Skill defined under
skills/*/SKILL.md (see that directory's docstrings for the full behavior
contract of each). Running `medsentry skills` lists them straight from
those files, so the CLI's surface and the skills' documentation can never
drift apart silently — there is exactly one description of what each skill
does, not two.

Runs entirely in DEMO_MODE by default (no API key needed) via
app/demo_engine.py. Set MEDSENTRY_DEMO_MODE=false with a real
GOOGLE_API_KEY to route the same commands through the live ADK agents in
app/agents.py instead — the CLI surface doesn't change.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from app import demo_engine, tools
from app.config import SKILLS_DIR, DATA_DIR, settings
from app.security import Role, audit_log

app = typer.Typer(help="MedSentry — secure family medication concierge (Agents CLI).")
console = Console()


def _load_seed() -> dict:
    with open(DATA_DIR / "seed_patient.json", "r", encoding="utf-8") as fh:
        return json.load(fh)["patient"]


def _severity_style(sev: str) -> str:
    return {"major": "bold red", "moderate": "bold yellow3", "minor": "dim"}.get(sev, "white")


@app.command()
def skills() -> None:
    """List every persistent Agent Skill (reads skills/*/SKILL.md directly)."""
    table = Table(title="MedSentry Agent Skills", show_lines=False)
    table.add_column("Skill")
    table.add_column("CLI command")
    table.add_column("Description")
    for skill_dir in sorted(SKILLS_DIR.iterdir()):
        md_path = skill_dir / "SKILL.md"
        if not md_path.exists():
            continue
        text = md_path.read_text(encoding="utf-8")
        front = text.split("---")[1] if text.startswith("---") else ""
        meta = {}
        for line in front.strip().splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()
        table.add_row(meta.get("name", skill_dir.name), meta.get("cli", "-"), meta.get("description", ""))
    console.print(table)


@app.command("add-med")
def add_med(text: str = typer.Argument(..., help='Free-text medication list, e.g. "warfarin 5mg at night, aspirin 81mg daily"')) -> None:
    """Parse free-text medications into structured entries (skill: check-interactions' upstream intake step)."""
    result = tools.parse_medication_text(text, actor_role=Role.PATIENT.value)
    console.print_json(json.dumps(result, indent=2))


@app.command("check-safety")
def check_safety(use_seed: bool = typer.Option(True, help="Use the bundled fictional demo patient instead of --meds.")) -> None:
    """Run the full intake -> safety -> schedule pipeline (skills: check-interactions, build-schedule)."""
    if use_seed:
        result = demo_engine.run_from_seed(_load_seed(), actor_role=Role.PATIENT.value)
    else:
        raise typer.BadParameter("Custom medication input: use `add-med` then pipe into your own script, or see README for the API.")

    console.rule("[bold]Safety flags[/bold]")
    if not result["safety_flags"]:
        console.print("[green]No known interactions found among these medications.[/green]")
    for flag in result["safety_flags"]:
        style = _severity_style(flag["severity"])
        console.print(f"[{style}]{flag['severity'].upper()}[/{style}] {flag['a']} + {flag['b']} — {flag['risk']}")
        console.print(f"   action: {flag['action']}")
    console.print(f"\n[dim]{result['disclaimer']}[/dim]")

    console.rule("[bold]Today's schedule[/bold]")
    table = Table()
    table.add_column("Time")
    table.add_column("Medications")
    for slot in result["daily_schedule"]:
        table.add_row(slot["time"], ", ".join(slot["items"]))
    console.print(table)


@app.command()
def schedule() -> None:
    """Show today's dosing timeline for the demo patient (skill: build-schedule)."""
    result = demo_engine.run_from_seed(_load_seed(), actor_role=Role.PATIENT.value)
    table = Table(title="Today's schedule")
    table.add_column("Time")
    table.add_column("Medications")
    for slot in result["daily_schedule"]:
        table.add_row(slot["time"], ", ".join(slot["items"]))
    console.print(table)


@app.command("share-update")
def share_update(consent_medications: bool = typer.Option(True), consent_schedule: bool = typer.Option(True),
                  consent_interactions: bool = typer.Option(True), consent_notes: bool = typer.Option(False)) -> None:
    """Prepare a consent-filtered caregiver update (skill: share-caregiver-update)."""
    patient = _load_seed()
    pipeline_result = demo_engine.run_from_seed(patient, actor_role=Role.PATIENT.value)
    consent_flags = {
        "medications": consent_medications,
        "schedule": consent_schedule,
        "interactions": consent_interactions,
        "notes": consent_notes,
    }
    result = demo_engine.run_caregiver_share(pipeline_result, consent_flags, actor_role=Role.CAREGIVER.value)
    console.print(f"[bold]Shared:[/bold] {result['shared_scopes']}")
    console.print(f"[bold yellow3]Withheld (no consent):[/bold yellow3] {result['withheld_scopes']}")


@app.command("audit-log")
def show_audit_log(as_role: str = typer.Option("patient", help="Role to request the log as (try 'caregiver' to see RBAC deny in action).")) -> None:
    """Show the security audit trail (skill: audit-report). RBAC-gated: try --as-role caregiver to see it denied."""
    result = tools.get_audit_log(actor_role=as_role, n=25)
    if result["status"] != "success":
        console.print(f"[bold red]DENIED[/bold red]: {result['message']}")
        raise typer.Exit(code=1)
    table = Table(title="Audit trail (most recent)")
    for col in ("timestamp", "actor_role", "action", "scope", "outcome"):
        table.add_column(col)
    for event in result["events"]:
        style = "red" if event["outcome"] == "denied" else "white"
        table.add_row(*(f"[{style}]{event[c]}[/{style}]" for c in ("timestamp", "actor_role", "action", "scope", "outcome")))
    console.print(table)


@app.command()
def run() -> None:
    """One-shot end-to-end demo: intake -> safety -> schedule -> caregiver share -> audit log. Good for a quick video demo."""
    console.rule("[bold cyan]MedSentry — full pipeline demo[/bold cyan]")
    console.print(f"[dim]Mode: {'DEMO (offline, deterministic)' if settings.demo_mode else 'LIVE (Gemini via ADK)'}[/dim]\n")
    check_safety(use_seed=True)
    console.print()
    share_update(consent_medications=True, consent_schedule=True, consent_interactions=True, consent_notes=False)
    console.print()
    show_audit_log(as_role="patient")
    console.print()
    console.print("[bold]Now try:[/bold] medsentry audit-log --as-role caregiver   [dim](RBAC denies this — by design)[/dim]")


@app.command()
def serve(port: Optional[int] = typer.Option(None, help="Override the port (default from PORT/MEDSENTRY_PORT env var).")) -> None:
    """Launch the web dashboard (FastAPI + static UI)."""
    import uvicorn
    uvicorn.run("app.web:app", host=settings.host, port=port or settings.port, reload=False)


if __name__ == "__main__":
    app()
