"""splunkguard-mcp — Gemini agent for Splunk via the official MCP Server.

Public API:
    SplunkMCPClient            — async context manager for the raw MCP transport
    SplunkInvestigator         — Gemini-driven agent that returns structured reports
    SplunkInvestigationReport  — typed result dataclass
    RecommendedAction          — typed action dataclass

Example:
    import asyncio
    from splunkguard_mcp import SplunkInvestigator

    agent = SplunkInvestigator(
        gemini_api_key="...",
        splunk_token="...",
        splunk_url="https://localhost:8089/services/mcp",
        verify_ssl=False,
    )
    report = asyncio.run(agent.investigate("Find failed CI pipelines in last 24h"))
    print(report.root_cause)
"""
from __future__ import annotations

from .agent import SplunkInvestigator
from .client import SplunkMCPClient
from .models import RecommendedAction, SplunkInvestigationReport

__all__ = [
    "SplunkInvestigator",
    "SplunkMCPClient",
    "SplunkInvestigationReport",
    "RecommendedAction",
]

__version__ = "0.1.0"
