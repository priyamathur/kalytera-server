"""
Starter rules: protect risky actions before anything has gone wrong.

From the actions an agent has taken, pick the ones behind the worst agent
incidents so far: running commands that wipe data (a production database
deleted in 9 seconds, a whole drive, a home folder), turning off monitoring
or security, deleting things, moving money, and changing accounts. Suggest
that a person approves them first (ESCALATE). Commands are held only when
they contain something destructive; money only above a limit, so everyday
amounts still run; the rest on every call. Suggestions start in watch mode
like any rule. Pure: no I/O.
"""
import math
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

MONEY = ("refund", "payment", "pay", "payout", "charge", "transfer", "withdraw", "withdrawal", "reimburse",
         "compensate", "compensation", "credit", "wire", "disburse", "send_money", "issue_credit")
DELETE = ("delete", "remove", "destroy", "drop", "purge", "wipe", "erase", "truncate", "rm", "rmdir")
ACCOUNT_ALWAYS = ("password", "permission", "permissions", "role", "roles", "grant", "revoke", "admin", "ban",
                  "suspend", "deactivate", "impersonate", "mfa", "2fa")
ACCOUNT_THING = ("account", "user", "profile", "email", "owner", "ownership", "subscription", "membership")
ACCOUNT_CHANGE = ("update", "change", "edit", "set", "close", "reset", "modify", "transfer", "cancel", "merge")
READ_ONLY = ("get", "list", "check", "lookup", "find", "search", "fetch", "read", "view", "show", "query",
             "status", "history", "estimate", "preview", "calculate", "validate", "verify")
COMMAND_WORDS = ("bash", "shell", "terminal", "powershell", "cmd", "command", "commands", "exec", "subprocess",
                 "sql", "psql", "mysql")
COMMAND_NAMES = ("run_command", "execute_command", "run_sql", "execute_sql", "run_query", "execute_query",
                 "run_script", "execute_script", "run_code", "execute_code", "execute", "run")
COMMAND_FIELDS = ("command", "cmd", "query", "sql", "script", "code", "statement", "input", "args")
# Text that makes a command destructive: wiping files, databases, disks, history or cloud resources.
DESTRUCTIVE = ["rm -rf", "drop table", "delete from", "rm -fr", "rm -r ", "rmdir /s", "del /s", "del /q",
               "remove-item", "format c:", "mkfs", "dd if=", "drop database", "drop schema", "truncate table", "truncate ",
               "git push --force", "git push -f", "git reset --hard", "git clean -f", "terraform destroy",
               "kubectl delete", "aws s3 rm", "gsutil rm", "shutdown", "chmod -r 777", "> /dev/sd"]
SAFETY_THING = ("monitor", "monitoring", "logging", "log", "logs", "audit", "alert", "alerts", "alarm", "firewall",
                "security", "guard", "guardrail", "guardrails", "oversight", "tracking", "telemetry", "antivirus",
                "backup", "backups", "kalytera")
SAFETY_CHANGE = ("disable", "stop", "off", "pause", "kill", "delete", "remove", "update", "change", "set", "mute",
                 "silence", "bypass", "override", "edit", "modify", "configure", "config", "turn", "uninstall")
AMOUNT_FIELDS = ("amount", "total", "price", "sum", "value", "cost", "refund", "credit", "payment")

KIND_WHY = {
    "command": "it runs commands, and some wipe files or databases",
    "safety": "it can turn off monitoring or security",
    "money": "it moves money",
    "delete": "it deletes things",
    "account": "it changes accounts or access",
}


def _words(name: str) -> List[str]:
    """'refundOrder' / 'refund-api' / 'refund_api' -> ['refund', 'order'] / ['refund', 'api']."""
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name)
    return [w for w in re.split(r"[^a-zA-Z0-9]+", spaced.lower()) if w]


def kind_of(action: str) -> Optional[str]:
    """command | safety | delete | money | account | None, from the action's name."""
    words = _words(action)
    joined = "_".join(words)
    if any(w in COMMAND_WORDS for w in words) or joined in COMMAND_NAMES:
        return "command"
    if any(w in SAFETY_THING for w in words) and any(w in SAFETY_CHANGE for w in words):
        return "safety"
    if any(w in READ_ONLY for w in words):  # get_refund_status only looks
        return None
    if any(w in DELETE for w in words):
        return "delete"
    if any(w in MONEY for w in words) or "send_money" in joined:
        return "money"
    if any(w in ACCOUNT_ALWAYS for w in words) or (
            any(w in ACCOUNT_THING for w in words) and any(w in ACCOUNT_CHANGE for w in words)):
        return "account"
    return None


def _number(v: Any) -> Optional[float]:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)) and math.isfinite(v):
        return float(v)
    return None


def _amount_field(calls: List[Dict[str, Any]]) -> Optional[Tuple[str, List[float]]]:
    """The numeric argument that looks like an amount, with the values seen."""
    seen: Dict[str, List[float]] = {}
    for args in calls:
        for k, v in args.items():
            n = _number(v)
            if n is not None and any(f in k.lower() for f in AMOUNT_FIELDS):
                seen.setdefault(k, []).append(n)
    if not seen:
        return None
    field = max(seen, key=lambda k: (len(seen[k]), k.lower() == "amount"))
    return field, seen[field]


def _command_field(calls: List[Dict[str, Any]]) -> Optional[str]:
    """The text argument that holds the command: by name, else the longest text."""
    texts: Dict[str, int] = {}
    for args in calls:
        for k, v in args.items():
            if isinstance(v, str):
                texts[k] = max(texts.get(k, 0), len(v))
    if not texts:
        return None
    named = [k for k in texts if k.lower() in COMMAND_FIELDS]
    return named[0] if named else max(texts, key=lambda k: texts[k])


def nice_limit(values: List[float]) -> float:
    """A round number at or above most amounts seen (the 90th percentile), so everyday ones still run."""
    vals = sorted(v for v in values if v > 0)
    if not vals:
        return 500
    p90 = vals[min(len(vals) - 1, int(math.ceil(0.9 * len(vals))) - 1)]
    exp = 10 ** math.floor(math.log10(p90))
    for step in (1, 2, 2.5, 5, 10):
        if step * exp >= p90:
            limit = step * exp
            return int(limit) if float(limit).is_integer() else limit
    return int(10 * exp)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:48] or "action"


def starter_rules(agent_id: str, actions: Iterable[Tuple[str, Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """
    actions: (name, arguments) of calls the agent made. Returns
    [{"rule": {...}, "kind": "money", "why": "...", "calls": 12}], the most dangerous kinds first.
    """
    by_name: Dict[str, List[Dict[str, Any]]] = {}
    for name, args in actions:
        if isinstance(name, str) and name:
            by_name.setdefault(name, []).append(args if isinstance(args, dict) else {})
    out: List[Dict[str, Any]] = []
    for name, calls in by_name.items():
        kind = kind_of(name)
        if kind is None:
            continue
        args: List[Dict[str, Any]] = []
        reason = f"{name} needs a person to approve it, because {KIND_WHY[kind]}."
        amount = _amount_field(calls) if kind == "money" else None
        if kind == "command":
            field = _command_field(calls)
            if field is None:
                continue
            args = [{"field": field, "op": "contains", "value": list(DESTRUCTIVE)}]
            reason = (f"{name} with a command that can wipe files, databases or disks needs a person to "
                      f"approve it.")
        elif amount:
            field, values = amount
            limit = nice_limit(values)
            args = [{"field": field, "op": ">", "value": limit}]
            reason = f"{name} over {limit:,} needs a person to approve it, because it moves money."
        out.append({
            "rule": {"id": f"approve_{_slug(name)}", "agent_id": agent_id,
                     "match": {"tool": name, "args": args}, "action": "ESCALATE", "reason": reason},
            "kind": kind, "why": KIND_WHY[kind], "calls": len(calls),
        })
    order = {"command": 0, "safety": 1, "delete": 2, "money": 3, "account": 4}
    return sorted(out, key=lambda s: (order[s["kind"]], -s["calls"], s["rule"]["match"]["tool"]))
