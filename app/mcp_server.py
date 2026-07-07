"""
mcp_server.py — exposes MedSentry's tools as an MCP (Model Context Protocol)
server, independent of ADK.

This is the second, separate demonstration of the "MCP Server" course
concept: rather than only letting our own ADK agents call these functions,
we wrap the exact same functions from app/tools.py with FastMCP so that
*any* MCP-compatible client — Claude Desktop, Claude Code, Gemini CLI, or a
teammate's own agent framework — can attach to MedSentry's vetted,
sandboxed medication-safety tools without re-implementing them.

Run it directly:
    python -m app.mcp_server

Then point any MCP client at it over stdio. Example Claude Desktop config
(see README.md "Use MedSentry's tools from Claude Desktop"):

    {
      "mcpServers": {
        "medsentry": {
          "command": "python",
          "args": ["-m", "app.mcp_server"]
        }
      }
    }

For a remote deployment, switch TRANSPORT to "streamable-http" (see
app/config.py MEDSENTRY_MCP_TRANSPORT) and run behind the same Cloud Run
service as the dashboard — see deploy/cloudrun.sh.
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from app import tools
from app.config import settings

mcp = FastMCP("medsentry")


@mcp.tool()
def check_drug_interactions(medications: list[str]) -> dict[str, Any]:
    """Screen a list of medication names for known drug-drug interactions.

    Always surfaces the safety disclaimer alongside any flags. Severity is
    one of minor/moderate/major, sorted with major first.
    """
    return tools.check_drug_interactions(medications, actor_role="mcp_client")


@mcp.tool()
def build_medication_schedule(medications: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a same-day dosing timeline from a structured medication list.

    Each medication should be like {"display": "Metformin 500mg",
    "times": ["08:00", "19:00"]}.
    """
    return tools.build_medication_schedule(medications, actor_role="mcp_client")


@mcp.tool()
def lookup_medication_info(name: str) -> dict[str, Any]:
    """Look up known interactions for a single medication name."""
    return tools.lookup_medication_info(name, actor_role="mcp_client")


@mcp.tool()
def parse_medication_text(raw_text: str) -> dict[str, Any]:
    """Parse a free-text medication list into structured entries.

    Applies input sanitization to reject text containing prompt-injection
    phrasing before it reaches any downstream reasoning.
    """
    return tools.parse_medication_text(raw_text, actor_role="mcp_client")


# Deliberately NOT exposed over MCP: share_caregiver_update and
# get_audit_log. Both touch a specific patient's consent state and audit
# trail, which is a same-process, authenticated concern (see app/security.py
# RBAC), not something to hand to an arbitrary external MCP client. This is
# the tool_filter / least-privilege principle from the course's Day 4
# security module applied at the boundary: expose the stateless safety
# tools broadly, keep the consent-bearing ones behind the app's own auth.


def main() -> None:
    transport = "stdio" if settings.mcp_transport == "stdio" else "streamable-http"
    mcp.run(transport=transport)


if __name__ == "__main__":
    main()
