"""
kalytera CLI — invoked as:
    kalytera demo                  # no API key needed
    kalytera check                 # verify your key end-to-end
    kalytera quickstart            # sample agent → failure pattern → rule → guard() blocks
    kalytera rules ...             # create, promote and inspect guard rules
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
    from kalytera.quickstart import agent_name

    api_key = args.api_key or os.getenv("KALYTERA_API_KEY", "")
    kalytera.configure(
        api_key=api_key,
        agent_id=args.agent_id or os.getenv("KALYTERA_AGENT_ID", "") or agent_name("kalytera-check", api_key),
        api_endpoint=args.endpoint,
        verify=False,
    )
    sys.exit(0 if kalytera.check(wait_for_score=not args.no_wait) else 1)


def _configure_quiet(args: argparse.Namespace) -> str:
    """Configure the SDK without printing the banner. Returns the agent_id."""
    import contextlib
    import io

    import kalytera
    api_key = args.api_key or os.getenv("KALYTERA_API_KEY", "")
    agent_id = args.agent_id or os.getenv("KALYTERA_AGENT_ID", "")
    if not api_key:
        print("Error: --api-key is required  (or set KALYTERA_API_KEY)")
        sys.exit(1)
    if not agent_id:
        print("Error: --agent-id is required  (or set KALYTERA_AGENT_ID)")
        sys.exit(1)
    with contextlib.redirect_stdout(io.StringIO()):
        kalytera.configure(api_key=api_key, agent_id=agent_id, api_endpoint=args.endpoint, verify=False)
    return agent_id


def _cmd_rules(args: argparse.Namespace) -> None:
    import json
    from urllib.parse import quote

    from kalytera import tracer

    agent_id = _configure_quiet(args)
    q = f"?agent_id={quote(agent_id)}"
    action = args.rules_command

    if action == "list":
        status, body, err = tracer._http("GET", f"/rules{q}")
    elif action == "add":
        try:
            with open(args.file) as f:
                rule = json.load(f)
        except (OSError, ValueError) as exc:
            print(f"✗ Can't read {args.file}: {exc}")
            sys.exit(1)
        rule.setdefault("agent_id", agent_id)
        status, body, err = tracer._http("POST", "/rules", rule)
    elif action in ("promote", "demote"):
        status, body, err = tracer._http("POST", f"/rules/{quote(args.rule_id)}/{action}{q}")
    elif action == "stats":
        status, body, err = tracer._http("GET", f"/rules/{quote(args.rule_id)}/stats{q}")
    elif action == "show":
        status, body, err = tracer._http("GET", f"/rules/{quote(args.rule_id)}{q}")
    elif action == "delete":
        status, body, err = tracer._http("DELETE", f"/rules/{quote(args.rule_id)}{q}")
    else:
        print("usage: kalytera rules {list,add,show,promote,demote,stats,delete}")
        sys.exit(1)

    if status is None or status >= 400:
        problem = tracer._connection_problem(status, err)
        detail = tracer._detail(body)
        print(f"✗ {detail or (problem[1] if problem else f'HTTP {status}')}")
        sys.exit(1)

    if action == "list":
        rules = body.get("rules", [])
        if not rules:
            print(f"No rules for agent '{agent_id}'. Add one with: kalytera rules add rule.json")
        for r in rules:
            print(f"{r['id']:<28} v{r['version']:<3} {r['mode']:<8} {r['action']:<9} {r['match']['tool']}  — {r.get('reason', '')}")
    elif action == "add":
        print(f"✓ Created {body['id']} (v1) in shadow mode — it logs would-blocks and never changes decisions.")
        print(f"  Promote it when ready: kalytera rules promote {body['id']}")
    elif action == "promote":
        s = body["shadow_summary"]
        print(f"✓ {args.rule_id} is now ENFORCED (v{body['rule']['version']}).")
        print(f"  Shadow summary before promotion: {s['would_block']} would-block(s) across {s['would_block_sessions']} session(s)")
    elif action == "demote":
        print(f"✓ {args.rule_id} is back in shadow mode (v{body['rule']['version']}).")
    else:
        print(json.dumps(body, indent=2, default=str))


def _cmd_guard(args: argparse.Namespace) -> None:
    import json

    import kalytera

    agent_id = _configure_quiet(args)
    try:
        call_args = json.loads(args.args)
    except ValueError as exc:
        print(f"✗ --args must be JSON: {exc}")
        sys.exit(1)
    d = kalytera.guard(args.tool, call_args, session_id=args.session_id, agent_id=agent_id)
    kalytera.flush_guard()
    print(f"{d.decision}" + (f"  rule={d.rule_id} v{d.rule_version}  reason={d.reason!r}" if d.rule_id else ""))
    for h in d.shadow_hits:
        print(f"  shadow: {h.rule_id} v{h.rule_version} would {h.action}")
    if d.error:
        print(f"  ⚠ {d.error}")
    sys.exit(0 if d.allowed else 2)


def _add_key_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--api-key", default="", metavar="KEY", help="Kalytera API key (or KALYTERA_API_KEY env var)")
    p.add_argument("--agent-id", default="", metavar="ID", help="Agent the rules belong to (or KALYTERA_AGENT_ID env var)")
    p.add_argument("--endpoint", default="", metavar="URL", help="Kalytera API endpoint (default: https://api.kalytera.dev)")


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

    qs_p = sub.add_parser("quickstart", help="See the whole loop in ~2 minutes: a sample agent fails, Kalytera "
                                             "finds the pattern, drafts a rule, and guard() blocks the next bad call")
    qs_p.add_argument("--api-key", default="", metavar="KEY", help="Kalytera API key (or KALYTERA_API_KEY env var)")
    qs_p.add_argument("--endpoint", default="", metavar="URL", help="Kalytera API endpoint (default: https://api.kalytera.dev)")
    qs_p.add_argument("--yes", "-y", action="store_true", help="Answer yes to both questions")

    proxy_p = sub.add_parser("proxy", help="Start a transparent LLM proxy for zero-code monitoring")
    proxy_p.add_argument("--port", type=int, default=8787, help="Local port to listen on (default: 8787)")
    proxy_p.add_argument("--api-key", default="", metavar="KEY", help="Kalytera API key (or KALYTERA_API_KEY env var)")
    proxy_p.add_argument("--agent-id", default="", metavar="ID", help="Agent ID for this proxy (or KALYTERA_AGENT_ID env var)")
    proxy_p.add_argument("--endpoint", default="https://api.kalytera.dev", metavar="URL", help="Kalytera API endpoint")
    proxy_p.add_argument("--upstream", default="", metavar="URL", help="Override upstream LLM URL (default: auto-detect from API key)")

    rules_p = sub.add_parser("rules", help="Create, promote and inspect guard rules")
    rules_sub = rules_p.add_subparsers(dest="rules_command")
    _add_key_args(rules_p)
    rules_sub.add_parser("list", help="List current rules for the agent")
    add_p = rules_sub.add_parser("add", help="Create a rule from a JSON file (starts in shadow mode)")
    add_p.add_argument("file")
    for name, help_text in [
        ("show", "Show a rule and its versions"),
        ("promote", "Move a rule from shadow to enforce"),
        ("demote", "Move a rule from enforce back to shadow"),
        ("stats", "Would-block and deny counts for a rule"),
        ("delete", "Deactivate a rule"),
    ]:
        rules_sub.add_parser(name, help=help_text).add_argument("rule_id")

    guard_p = sub.add_parser("guard", help="Check one tool call against your rules")
    guard_p.add_argument("tool")
    guard_p.add_argument("--args", default="{}", help="Tool arguments as JSON")
    guard_p.add_argument("--session-id", default="cli", help="Session ID (for count_in_window rules)")
    _add_key_args(guard_p)

    args = parser.parse_args()

    if args.command == "demo":
        from kalytera.demo import run
        run()
    elif args.command == "quickstart":
        from kalytera.quickstart import run as run_quickstart
        run_quickstart(args.api_key or os.getenv("KALYTERA_API_KEY", ""), args.endpoint, assume_yes=args.yes)
    elif args.command == "check":
        _cmd_check(args)
    elif args.command == "proxy":
        _cmd_proxy(args)
    elif args.command == "rules":
        _cmd_rules(args)
    elif args.command == "guard":
        _cmd_guard(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
