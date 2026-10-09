"""
kalytera CLI — invoked as:
    kalytera demo                  # no API key needed
    kalytera check                 # verify your key end-to-end
    kalytera proxy ...
    python -m kalytera <command> ...
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
        upstream=args.upstream or None,
    ).run()


def _cmd_check(args: argparse.Namespace) -> None:
    import kalytera
    kalytera.configure(
        api_key=args.api_key or os.getenv("KALYTERA_API_KEY", ""),
        agent_id=args.agent_id or os.getenv("KALYTERA_AGENT_ID", "kalytera-check"),
        api_endpoint=args.endpoint,
        verify=False,
    )
    sys.exit(0 if kalytera.check(wait_for_score=not args.no_wait) else 1)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="kalytera",
        description="Kalytera CLI",
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("demo", help="Run a bundled agent session through Kalytera's checks (no API key needed)")

    check_p = sub.add_parser("check", help="Verify your API key, record a test step and wait for its score")
    check_p.add_argument("--api-key", default="", metavar="KEY", help="Kalytera API key (or KALYTERA_API_KEY env var)")
    check_p.add_argument("--agent-id", default="", metavar="ID", help="Agent ID for the test step (or KALYTERA_AGENT_ID env var)")
    check_p.add_argument("--endpoint", default="", metavar="URL", help="Kalytera API endpoint (default: https://api.kalytera.dev)")
    check_p.add_argument("--no-wait", action="store_true", help="Don't wait for the server to score the test step")

    proxy_p = sub.add_parser("proxy", help="Start a transparent LLM proxy for zero-code monitoring")
    proxy_p.add_argument("--port", type=int, default=8787, help="Local port to listen on (default: 8787)")
    proxy_p.add_argument("--api-key", default="", metavar="KEY", help="Kalytera API key (or KALYTERA_API_KEY env var)")
    proxy_p.add_argument("--agent-id", default="", metavar="ID", help="Agent ID for this proxy (or KALYTERA_AGENT_ID env var)")
    proxy_p.add_argument("--endpoint", default="https://api.kalytera.dev", metavar="URL", help="Kalytera API endpoint")
    proxy_p.add_argument("--upstream", default="", metavar="URL", help="Override upstream LLM URL (default: auto-detect from API key)")

    args = parser.parse_args()

    if args.command == "demo":
        from kalytera.demo import run
        run()
    elif args.command == "check":
        _cmd_check(args)
    elif args.command == "proxy":
        _cmd_proxy(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
