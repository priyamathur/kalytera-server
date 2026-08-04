"""
kalytera CLI — invoked as:
    kalytera proxy ...
    python -m kalytera proxy ...
"""
from __future__ import annotations

import argparse
import os
import sys


def _cmd_proxy(args: argparse.Namespace) -> None:
    api_key = args.api_key or os.getenv("KALYTERA_API_KEY", "")
    agent_id = args.agent_id or os.getenv("KALYTERA_AGENT_ID", "")

    if not api_key:
        print("Error: --api-key is required  (or set KALYTERA_API_KEY)")
        sys.exit(1)
    if not agent_id:
        print("Error: --agent-id is required  (or set KALYTERA_AGENT_ID)")
        sys.exit(1)

    from kalytera.proxy import KalyteraProxy
    KalyteraProxy(
        api_key=api_key,
        agent_id=agent_id,
        port=args.port,
        kalytera_endpoint=args.endpoint,
    ).run()


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="kalytera",
        description="Kalytera CLI",
    )
    sub = parser.add_subparsers(dest="command")

    proxy_p = sub.add_parser("proxy", help="Start a transparent LLM proxy for zero-code monitoring")
    proxy_p.add_argument("--port", type=int, default=8787, help="Local port to listen on (default: 8787)")
    proxy_p.add_argument("--api-key", default="", metavar="KEY", help="Kalytera API key (or KALYTERA_API_KEY env var)")
    proxy_p.add_argument("--agent-id", default="", metavar="ID", help="Agent ID for this proxy (or KALYTERA_AGENT_ID env var)")
    proxy_p.add_argument("--endpoint", default="https://api.kalytera.dev", metavar="URL", help="Kalytera API endpoint")

    args = parser.parse_args()

    if args.command == "proxy":
        _cmd_proxy(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
