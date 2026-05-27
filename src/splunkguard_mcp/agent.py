"""SplunkInvestigator — Gemini-driven agent that drives the Splunk MCP Server.

Usage:

    from splunkguard_mcp import SplunkInvestigator

    agent = SplunkInvestigator(
        gemini_api_key="...",                       # or set GEMINI_API_KEY
        splunk_token="...",                         # encrypted MCP token
        splunk_url="https://localhost:8089/services/mcp",
        verify_ssl=False,                           # local dev with self-signed cert
    )
    report = await agent.investigate(
        "What CI pipelines failed last night and why?",
        earliest="-30d",
        latest="now",
    )
    print(report.root_cause)
    for a in report.recommended_actions:
        print(f"  - {a.action}\\n    SPL: {a.spl_query}")
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from google import genai
from google.genai import types

from .client import SplunkMCPClient
from .models import RecommendedAction, SplunkInvestigationReport
from .prompts import SPLUNK_SYSTEM_PROMPT, build_investigation_prompt

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "gemini-2.5-flash"
_MAX_TOOL_ITERATIONS = 15


class SplunkInvestigator:
    """Drive Gemini through a Splunk MCP tool-call loop and return a structured report."""

    def __init__(
        self,
        gemini_api_key: str,
        splunk_token: str,
        splunk_url: str = "https://localhost:8089/services/mcp",
        verify_ssl: bool = True,
        model: str = _DEFAULT_MODEL,
        max_iterations: int = _MAX_TOOL_ITERATIONS,
    ) -> None:
        self._genai = genai.Client(api_key=gemini_api_key)
        self._splunk_token = splunk_token
        self._splunk_url = splunk_url
        self._verify_ssl = verify_ssl
        self._model = model
        self._max_iterations = max_iterations

    async def investigate(
        self,
        question: str,
        earliest: str = "-24h",
        latest: str = "now",
    ) -> SplunkInvestigationReport:
        """Run the agentic investigation loop and return a structured report."""
        async with SplunkMCPClient(
            splunk_token=self._splunk_token,
            splunk_url=self._splunk_url,
            verify_ssl=self._verify_ssl,
        ) as client:
            mcp_tools = await client.list_tools()
            gemini_tools = [
                types.Tool(
                    function_declarations=[
                        _mcp_to_gemini_declaration(t) for t in mcp_tools
                    ]
                )
            ]

            prompt = build_investigation_prompt(question, earliest, latest)
            messages: list[types.Content] = [
                types.Content(role="user", parts=[types.Part(text=prompt)])
            ]
            final_text = await self._run_tool_loop(client, gemini_tools, messages)

        return _parse_report(final_text, question)

    async def _run_tool_loop(
        self,
        client: SplunkMCPClient,
        tools: list[types.Tool],
        messages: list[types.Content],
    ) -> str:
        final_text = ""
        for iteration in range(1, self._max_iterations + 1):
            logger.debug("Iteration %d/%d", iteration, self._max_iterations)
            response = self._genai.models.generate_content(
                model=self._model,
                contents=messages,
                config=types.GenerateContentConfig(
                    system_instruction=SPLUNK_SYSTEM_PROMPT,
                    tools=tools,
                    temperature=0.1,
                ),
            )
            if not response.candidates:
                logger.warning("Gemini returned no candidates (content filtered?)")
                break

            candidate = response.candidates[0]
            messages.append(candidate.content)

            tool_calls = [
                p.function_call for p in candidate.content.parts if p.function_call
            ]
            text_parts = [p.text for p in candidate.content.parts if p.text]
            if text_parts:
                final_text = "\n".join(text_parts)
            if not tool_calls:
                break

            tool_responses: list[types.Part] = []
            for fc in tool_calls:
                logger.debug("→ %s(%s)", fc.name, dict(fc.args))
                result_text = await client.call_tool(fc.name, dict(fc.args))
                tool_responses.append(
                    types.Part(
                        function_response=types.FunctionResponse(
                            name=fc.name, response={"output": result_text}
                        )
                    )
                )
            messages.append(types.Content(role="tool", parts=tool_responses))
        return final_text


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mcp_to_gemini_declaration(tool: Any) -> types.FunctionDeclaration:
    schema = getattr(tool, "inputSchema", None) or {}
    properties: dict[str, types.Schema] = {}
    for name, definition in schema.get("properties", {}).items():
        properties[name] = types.Schema(
            type=_json_type_to_gemini(definition.get("type", "string")),
            description=definition.get("description", ""),
        )
    return types.FunctionDeclaration(
        name=tool.name,
        description=tool.description or "",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties=properties,
            required=schema.get("required", []),
        ),
    )


def _json_type_to_gemini(json_type: str) -> types.Type:
    return {
        "string": types.Type.STRING,
        "integer": types.Type.INTEGER,
        "number": types.Type.NUMBER,
        "boolean": types.Type.BOOLEAN,
        "array": types.Type.ARRAY,
        "object": types.Type.OBJECT,
    }.get(json_type, types.Type.STRING)


def _parse_report(text: str, question: str) -> SplunkInvestigationReport:
    """Pull the structured JSON block out of Gemini's free-form output."""
    json_match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
    if json_match:
        try:
            data = json.loads(json_match.group(1))
            return SplunkInvestigationReport(
                question=question,
                root_cause=data.get("root_cause", "see full analysis"),
                investigation_category=data.get("investigation_category", "unknown"),
                affected_components=data.get("affected_components", []),
                time_range=data.get("time_range", ""),
                is_ongoing=bool(data.get("is_ongoing", False)),
                recommended_actions=[
                    RecommendedAction(
                        action=a.get("action", ""),
                        spl_query=a.get("spl_query", ""),
                        confidence=a.get("confidence", "medium"),
                    )
                    for a in data.get("recommended_actions", [])
                ],
                full_analysis=text,
            )
        except (json.JSONDecodeError, ValueError, KeyError) as exc:
            logger.debug("Could not parse structured report: %s", exc)

    return SplunkInvestigationReport(
        question=question,
        root_cause="See full analysis below",
        full_analysis=text,
    )
