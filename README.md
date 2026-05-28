# splunkguard-mcp

[![PyPI version](https://img.shields.io/pypi/v/splunkguard-mcp.svg)](https://pypi.org/project/splunkguard-mcp/)
[![Python versions](https://img.shields.io/pypi/pyversions/splunkguard-mcp.svg)](https://pypi.org/project/splunkguard-mcp/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Splunkbase #7931](https://img.shields.io/badge/Splunkbase-%237931-orange)](https://splunkbase.splunk.com/app/7931)

> A small Gemini-driven agent that drives the **official Splunk MCP Server** ([Splunkbase App #7931](https://splunkbase.splunk.com/app/7931)) to answer natural-language questions about your Splunk data.

Ask *"What CI pipelines failed last night and why?"* or *"Are there auth anomalies in the last 24 hours?"* and get back a typed `SplunkInvestigationReport` with root cause, failure category, time range, affected components, and paste-ready SPL recommendations.

Extracted from the [SplunkGuard hackathon project](https://github.com/64johnlee/hackathon-pipeline-guard) and packaged so other agents can use the same Splunk-MCP-over-Streamable-HTTP plumbing without dragging in the rest of that codebase.

---

## Why this library exists

The Splunk MCP Server App is great but two things tripped us up when integrating it from Python:

1. **Transport mismatch.** App #7931 v1.1.0 uses the **modern MCP Streamable HTTP transport** (per the MCP 2025-06-18 spec), not the older SSE transport. If you reach for `mcp.client.sse.sse_client` (the obvious one), you'll get **HTTP 405 Method Not Allowed** because Splunk's `/services/mcp` only accepts POST. You need `mcp.client.streamable_http.streamablehttp_client`.

2. **Self-signed cert handling.** Local Splunk dev instances use self-signed TLS. The MCP SDK doesn't auto-honor an `ssl.SSLContext` you hand it — you need to inject a custom `httpx_client_factory` into the transport. We wire that for you.

This library handles both correctly out of the box.

---

## Install

```bash
pip install splunkguard-mcp
```

Python ≥ 3.10. Pulls `google-genai`, `mcp`, and `httpx` as deps.

---

## Quick start

### 1. Spin up Splunk + the MCP Server App

```bash
docker run -d --name splunk \
  -p 8000:8000 -p 8088:8088 -p 8089:8089 \
  -e SPLUNK_PASSWORD=changeme \
  -e SPLUNK_GENERAL_TERMS=--accept-sgt-current-at-splunk-com \
  -e SPLUNK_START_ARGS=--accept-license \
  splunk/splunk:latest

# Install Splunkbase App #7931 (download .tgz after logging in at
# https://splunkbase.splunk.com/app/7931, then copy into the container):
docker cp splunk_mcp_server.tgz splunk:/tmp/
docker exec -u splunk splunk /opt/splunk/bin/splunk install app \
  /tmp/splunk_mcp_server.tgz -auth admin:changeme

# IMPORTANT: restart the *container*, not splunkd. `splunk restart` in
# Docker kills splunkd but never re-spawns it; `docker restart` does.
docker restart splunk

# Generate the MCP token:
curl -sk -u admin:changeme -X POST \
  "https://localhost:8089/services/mcp_token?username=admin&action=rotate"
TOKEN=$(curl -sk -u admin:changeme \
  "https://localhost:8089/services/mcp_token?username=admin&action=get" \
  | python3 -c "import json,sys;print(json.load(sys.stdin)['token'])")
echo "$TOKEN"   # use this as SPLUNK_MCP_TOKEN below
```

### 2. Investigate via the CLI

```bash
export GEMINI_API_KEY=...                # https://aistudio.google.com
export SPLUNK_MCP_TOKEN="$TOKEN"

splunkguard-mcp investigate \
  "What CI pipelines failed in the last 30 days?" \
  --earliest -30d \
  --no-verify-ssl
```

### 3. Or use the Python API

```python
import asyncio
from splunkguard_mcp import SplunkInvestigator

agent = SplunkInvestigator(
    gemini_api_key="...",
    splunk_token="...",
    splunk_url="https://localhost:8089/services/mcp",
    verify_ssl=False,                         # local dev with self-signed cert
)
report = asyncio.run(agent.investigate(
    "What CI pipelines failed last night and why?",
    earliest="-24h",
    latest="now",
))
print(report.root_cause)
for a in report.recommended_actions:
    print(f"  - {a.action} (confidence: {a.confidence})")
    print(f"    SPL: {a.spl_query}")
```

### 4. Or just the raw MCP client (BYO LLM)

```python
import asyncio
from splunkguard_mcp import SplunkMCPClient

async def main():
    async with SplunkMCPClient(splunk_token="...", verify_ssl=False) as c:
        tools = await c.list_tools()
        for t in tools:
            print(t.name, "—", t.description[:80])
        out = await c.call_tool(
            "splunk_run_query",
            {"query": "search index=_internal | head 5"},
        )
        print(out)

asyncio.run(main())
```

---

## Benchmark

End-to-end on a local Splunk Enterprise 10.4.0 (Docker `splunk/splunk:latest`) + Splunkbase App #7931 v1.1.0 + Gemini 2.5 Flash (Google AI Studio, free tier):

| Stage | Wall-clock | Notes |
|---|---|---|
| Investigate via MCP (agentic loop, 2 tool calls) | **~38 s** | Gemini autonomously called `get_indexes` then `splunk_run_query`; returned structured report with 3 SPL recommendations |
| Investigate via direct Splunk REST API (1 Gemini call) | ~8.5 s | Available in the [parent project](https://github.com/64johnlee/hackathon-pipeline-guard) as the `--direct` path |

The MCP path is roughly 4× slower than direct REST because it gives Gemini real tool-call latency budget to iterate; the trade-off is deeper, more specific findings (specific failing-job names, `is_ongoing` inference, more SPL recommendations).

---

## What's in the package

```
splunkguard_mcp/
├── __init__.py        — public API: SplunkInvestigator, SplunkMCPClient,
│                        SplunkInvestigationReport, RecommendedAction
├── __main__.py        — `python -m splunkguard_mcp investigate "<question>"`
├── client.py          — SplunkMCPClient: async context manager that
│                        connects via Streamable HTTP + custom httpx factory
├── agent.py           — SplunkInvestigator: Gemini tool-call loop +
│                        FunctionDeclaration translation + structured-output parsing
├── models.py          — dataclasses: SplunkInvestigationReport,
│                        RecommendedAction
└── prompts.py         — system prompt + user-turn template
```

---

## Gotchas (verified the hard way)

| Symptom | Cause | Fix |
|---|---|---|
| `HTTP 405 Method Not Allowed` from `/services/mcp` | Used SSE transport instead of Streamable HTTP | Use `mcp.client.streamable_http.streamablehttp_client` (this library does) |
| `Failed to decode bearer token` | Used `Authorization: Bearer <token>` with a non-encrypted token | Use `Authorization: Splunk <encrypted-token>` (the token returned by `/services/mcp_token?action=get`) |
| splunkd dies and never restarts after `splunk install app` | `splunk restart` inside Docker kills splunkd but doesn't re-spawn it | `docker restart splunk` instead — Docker's entrypoint script handles boot correctly |
| `verify_ssl=False` is ignored, TLS still fails | The MCP SDK doesn't auto-honor a standalone `ssl.SSLContext` | This library injects a custom `httpx_client_factory` — `verify_ssl=False` actually takes effect |

---

## License

MIT — see [LICENSE](LICENSE).

---

## Related

- The full SplunkGuard hackathon project (with the `--direct` REST fallback path + GitLab→Splunk HEC ingester):
  https://github.com/64johnlee/hackathon-pipeline-guard
- The official Splunk MCP Server App on Splunkbase:
  https://splunkbase.splunk.com/app/7931
- The Model Context Protocol spec:
  https://modelcontextprotocol.io
