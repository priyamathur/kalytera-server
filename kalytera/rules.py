"""
Kalytera rules — schema validation and in-process evaluation for guard().

Pure stdlib, no I/O, no LLM. Used by the SDK's guard() and by POST /guard so
both make the same decision for the same rules. See docs/specs/failure-to-rule.md.

Rule shape (v0):
    {
      "id": "rule_refund_cap", "agent_id": "billing-agent", "version": 1,
      "match": {"tool": "refund_api",
                "args": [{"field": "amount", "op": ">", "value": 500}]},
      "session_conditions": [{"type": "count_in_window", "tool": "refund_api",
                              "op": ">=", "value": 3, "window_seconds": 600}],
      "action": "DENY", "mode": "shadow", "reason": "...", "fail_closed": false
    }

All arg predicates and session conditions must hold for a rule to match.
"""
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any, Deque, Dict, List, Optional, Tuple

ALLOW = "ALLOW"
DENY = "DENY"
ESCALATE = "ESCALATE"

SHADOW = "shadow"
ENFORCE = "enforce"

OPS = ("==", "!=", ">", ">=", "<", "<=", "in")
ACTIONS = (DENY, ESCALATE)
MODES = (SHADOW, ENFORCE)
SESSION_CONDITION_TYPES = ("count_in_window",)

# Higher wins when several enforce-mode rules match the same call.
_SEVERITY = {ALLOW: 0, ESCALATE: 1, DENY: 2}

_MISSING = object()


class RuleError(ValueError):
    """A rule failed schema validation."""


@dataclass(frozen=True)
class Rule:
    id: str
    agent_id: str
    version: int
    tool: str
    args: Tuple[Dict[str, Any], ...]
    session_conditions: Tuple[Dict[str, Any], ...]
    action: str
    mode: str
    reason: str
    fail_closed: bool = False


@dataclass(frozen=True)
class RuleHit:
    rule_id: str
    rule_version: int
    mode: str
    action: str
    reason: str


@dataclass(frozen=True)
class Decision:
    """
    What guard() returns. `decision` is what the agent must act on.

    `rule_id`/`rule_version`/`reason` name the enforce-mode rule that decided,
    or are empty on ALLOW. `shadow_hits` lists shadow-mode rules that would
    have blocked — they never change `decision`.
    """
    decision: str
    rule_id: str = ""
    rule_version: int = 0
    reason: str = ""
    shadow_hits: Tuple[RuleHit, ...] = ()
    error: str = ""

    @property
    def allowed(self) -> bool:
        return self.decision == ALLOW


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _check_op(op: Any, value: Any, where: str) -> None:
    if op not in OPS:
        raise RuleError(f"{where}: op must be one of {', '.join(OPS)} (got {op!r})")
    if op == "in" and not isinstance(value, list):
        raise RuleError(f"{where}: 'in' needs a list value")


def parse_rule(raw: Dict[str, Any]) -> Rule:
    """Validate a rule dict and return a Rule. Raises RuleError with a clear message."""
    if not isinstance(raw, dict):
        raise RuleError("rule must be a JSON object")
    rule_id = raw.get("id")
    if not isinstance(rule_id, str) or not rule_id:
        raise RuleError("id is required")
    where = f"rule {rule_id}"

    version = raw.get("version", 1)
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise RuleError(f"{where}: version must be a positive integer")

    match = raw.get("match")
    if not isinstance(match, dict) or not isinstance(match.get("tool"), str) or not match["tool"]:
        raise RuleError(f"{where}: match.tool is required")

    args = match.get("args", [])
    if not isinstance(args, list):
        raise RuleError(f"{where}: match.args must be a list")
    for i, pred in enumerate(args):
        pw = f"{where}: match.args[{i}]"
        if not isinstance(pred, dict) or not isinstance(pred.get("field"), str) or not pred["field"]:
            raise RuleError(f"{pw}: field is required")
        if "value" not in pred:
            raise RuleError(f"{pw}: value is required")
        _check_op(pred.get("op"), pred["value"], pw)

    conds = raw.get("session_conditions", [])
    if not isinstance(conds, list):
        raise RuleError(f"{where}: session_conditions must be a list")
    for i, cond in enumerate(conds):
        cw = f"{where}: session_conditions[{i}]"
        if not isinstance(cond, dict) or cond.get("type") not in SESSION_CONDITION_TYPES:
            raise RuleError(f"{cw}: type must be one of {', '.join(SESSION_CONDITION_TYPES)}")
        if not isinstance(cond.get("tool"), str) or not cond["tool"]:
            raise RuleError(f"{cw}: tool is required")
        if cond.get("op") not in OPS or cond.get("op") == "in":
            raise RuleError(f"{cw}: op must be a comparison operator")
        value = cond.get("value")
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise RuleError(f"{cw}: value must be a non-negative integer")
        window = cond.get("window_seconds")
        if not isinstance(window, (int, float)) or isinstance(window, bool) or window <= 0:
            raise RuleError(f"{cw}: window_seconds must be a positive number")

    action = raw.get("action")
    if action not in ACTIONS:
        raise RuleError(f"{where}: action must be one of {', '.join(ACTIONS)}")
    mode = raw.get("mode", SHADOW)
    if mode not in MODES:
        raise RuleError(f"{where}: mode must be one of {', '.join(MODES)}")
    fail_closed = raw.get("fail_closed", False)
    if not isinstance(fail_closed, bool):
        raise RuleError(f"{where}: fail_closed must be true or false")

    return Rule(
        id=rule_id,
        agent_id=str(raw.get("agent_id", "")),
        version=version,
        tool=match["tool"],
        args=tuple(args),
        session_conditions=tuple(conds),
        action=action,
        mode=mode,
        reason=str(raw.get("reason", "")),
        fail_closed=fail_closed,
    )


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

def _lookup(args: Dict[str, Any], path: str) -> Any:
    """Resolve a dotted path ('customer.tier') in nested dicts. _MISSING if absent."""
    cur: Any = args
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return _MISSING
        cur = cur[part]
    return cur


def _compare(actual: Any, op: str, expected: Any) -> bool:
    """Apply op. A missing field or a type mismatch is a non-match, never an error."""
    if actual is _MISSING:
        return False
    try:
        if op == "==":
            return bool(actual == expected)
        if op == "!=":
            return bool(actual != expected)
        if op == "in":
            return actual in expected
        # Ordering: never compare bools as numbers or numbers with strings.
        if isinstance(actual, bool) or isinstance(expected, bool):
            return False
        if op == ">":
            return bool(actual > expected)
        if op == ">=":
            return bool(actual >= expected)
        if op == "<":
            return bool(actual < expected)
        if op == "<=":
            return bool(actual <= expected)
    except TypeError:
        return False
    return False


class SessionHistory:
    """
    Per-session record of tool calls that were allowed to run, for count_in_window.

    Bounded: keeps at most `max_sessions` sessions (oldest dropped) and
    `max_calls` calls per session.
    """

    def __init__(self, max_sessions: int = 1000, max_calls: int = 500) -> None:
        self._calls: Dict[str, Deque[Tuple[str, float]]] = defaultdict(lambda: deque(maxlen=max_calls))
        self._max_sessions = max_sessions

    def record(self, session_id: str, tool: str, at: Optional[float] = None) -> None:
        if session_id not in self._calls and len(self._calls) >= self._max_sessions:
            del self._calls[next(iter(self._calls))]
        self._calls[session_id].append((tool, time.time() if at is None else at))

    def count(self, session_id: str, tool: str, window_seconds: float, now: float) -> int:
        calls = self._calls.get(session_id)
        if not calls:
            return 0
        cutoff = now - window_seconds
        return sum(1 for t, ts in calls if t == tool and ts >= cutoff)


def _matches(rule: Rule, tool: str, args: Dict[str, Any], session_id: str,
             history: Optional[SessionHistory], now: float) -> bool:
    if rule.tool != tool:
        return False
    for pred in rule.args:
        if not _compare(_lookup(args, pred["field"]), pred["op"], pred["value"]):
            return False
    for cond in rule.session_conditions:
        # Count includes the call being checked: ">= 3" means "this is the 3rd call or later".
        prior = history.count(session_id, cond["tool"], cond["window_seconds"], now) if history else 0
        current = 1 if cond["tool"] == tool else 0
        if not _compare(prior + current, cond["op"], cond["value"]):
            return False
    return True


def evaluate(
    rules: List[Rule],
    tool: str,
    args: Optional[Dict[str, Any]] = None,
    session_id: str = "",
    history: Optional[SessionHistory] = None,
    now: Optional[float] = None,
) -> Decision:
    """
    Decide whether `tool(args)` may run. Pure: does not record the call in history.

    Shadow-mode matches are reported in `shadow_hits` and never change the decision.
    Among enforce-mode matches, DENY beats ESCALATE; ties go to the first rule listed.
    """
    args = args or {}
    now = time.time() if now is None else now
    winner: Optional[Rule] = None
    shadow: List[RuleHit] = []
    for rule in rules:
        if not _matches(rule, tool, args, session_id, history, now):
            continue
        if rule.mode == SHADOW:
            shadow.append(RuleHit(rule.id, rule.version, rule.mode, rule.action, rule.reason))
        elif winner is None or _SEVERITY[rule.action] > _SEVERITY[winner.action]:
            winner = rule
    if winner is None:
        return Decision(ALLOW, shadow_hits=tuple(shadow))
    return Decision(winner.action, winner.id, winner.version, winner.reason, tuple(shadow))
