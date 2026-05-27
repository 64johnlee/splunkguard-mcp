"""CLI entry: `python -m splunkguard_mcp investigate "<question>"`.

Also installed as a console script `splunkguard-mcp` via pyproject.toml.
"""
from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import logging
import os
import sys

from . import SplunkInvestigator


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="splunkguard-mcp",
        description="Ask Splunk a question in plain English via the official MCP Server.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    inv = sub.add_parser(
        "investigate", help="Run a single natural-language investigation"
    )
    inv.add_argument("question", help="Natural-language question to investigate")
    inv.add_argument("--earliest", default="-24h", help="SPL time modifier (default -24h)")
    inv.add_argument("--latest", default="now", help="SPL time modifier (default now)")
    inv.add_argument(
        "--splunk-url",
        default=os.environ.get("SPLUNK_MCP_URL", "https://localhost:8089/services/mcp"),
        help="Splunk MCP endpoint ($SPLUNK_MCP_URL)",
    )
    inv.add_argument(
        "--splunk-token",
        default=os.environ.get("SPLUNK_MCP_TOKEN", ""),
        help="Encrypted Splunk MCP token ($SPLUNK_MCP_TOKEN)",
    )
    inv.add_argument(
        "--gemini-key",
        default=os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY", ""),
        help="Google AI Studio key ($GEMINI_API_KEY or $GOOGLE_API_KEY)",
    )
    inv.add_argument("--no-verify-ssl", action="store_true", help="Skip TLS verification")
    inv.add_argument("--model", default="gemini-2.5-flash", help="Gemini model")
    inv.add_argument("--debug", action="store_true", help="Verbose logging")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.debug:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    if args.command == "investigate":
        missing = [
            name
            for name, val in (
                ("--gemini-key / $GEMINI_API_KEY", args.gemini_key),
                ("--splunk-token / $SPLUNK_MCP_TOKEN", args.splunk_token),
            )
            if not val
        ]
        if missing:
            print(f"Error: missing required: {', '.join(missing)}", file=sys.stderr)
            return 2

        agent = SplunkInvestigator(
            gemini_api_key=args.gemini_key,
            splunk_token=args.splunk_token,
            splunk_url=args.splunk_url,
            verify_ssl=not args.no_verify_ssl,
            model=args.model,
        )
        report = asyncio.run(
            agent.investigate(args.question, earliest=args.earliest, latest=args.latest)
        )
        print(report.full_analysis)
        print()
        print("--- Structured report ---")
        print(json.dumps(dataclasses.asdict(report), indent=2, default=str))
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
