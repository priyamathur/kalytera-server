"""
Rules view for the Streamlit dashboard — guard rules without writing Python.

One thing at a time: the page lists rules as plain sentences; creating, trying,
editing and promoting each happen in a dialog or popover. Everything goes
through the Kalytera API with the signed-in user's key, so the dashboard sees
exactly what guard() sees.
"""
import html
import inspect
import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

import requests
import streamlit as st

API = os.getenv("KALYTERA_API_ENDPOINT", "https://api.kalytera.dev").rstrip("/")

# Plain-English operator labels for the form; values are the rule operators.
OPS = {"is more than": ">", "is at least": ">=", "is less than": "<", "is at most": "<=",
       "equals": "==", "is not": "!=", "is one of": "in"}
_OP_WORDS = {v: k for k, v in OPS.items()}
_ACTIONS = {"Block it": "DENY", "Flag it for review": "ESCALATE"}
_VERB = {"DENY": "Block", "ESCALATE": "Flag"}
_PAST = {"DENY": "blocked", "ESCALATE": "flagged"}

# Keyed popovers keep their open/closed state with the rule, not the card position.
_POPOVER_TAKES_KEY = "key" in inspect.signature(st.popover).parameters

_TEMPLATE = {
    "id": "refund_cap",
    "match": {"tool": "refund_api", "args": [{"field": "amount", "op": ">", "value": 500}]},
    "action": "DENY",
    "reason": "Refunds over 500 need review",
}

_CSS = """
<style>
.kr-sentence{font-size:16px;color:#0f172a;line-height:1.5;margin:2px 0 4px}
.kr-sentence code{background:#f1f5f9;color:#0f172a;padding:1px 6px;border-radius:5px;font-size:14px}
.kr-meta{font-size:13px;color:#64748b;margin-bottom:2px}
.kr-name{font-size:12px;color:#94a3b8}
.kr-pill{display:inline-block;padding:2px 10px;border-radius:999px;font-size:12px;font-weight:600;margin-left:8px}
.kr-watch{background:#eef2ff;color:#4f46e5}
.kr-block{background:#fef2f2;color:#dc2626}
.kr-empty{text-align:center;padding:28px 12px 12px;color:#475569;font-size:14px;line-height:1.7}
.kr-empty-title{font-size:18px;font-weight:700;color:#0f172a;margin-bottom:6px}
.kr-empty b{color:#0f172a}
</style>
"""


# ── API ──────────────────────────────────────────────────────────────────────

def _api(method: str, path: str, body: Optional[Dict[str, Any]] = None,
         params: Optional[Dict[str, str]] = None) -> Tuple[int, Any]:
    """Returns (status, json). status 0 means the API could not be reached."""
    key = st.session_state.get("api_key", "")
    try:
        r = requests.request(method, f"{API}{path}", json=body, params=params, timeout=15,
                             headers={"Authorization": f"Bearer {key}"} if key else {})
    except Exception as exc:
        return 0, {"detail": f"Can't reach {API}: {exc}"}
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, {"detail": r.text[:200]}


def _detail(body: Any) -> str:
    d = body.get("detail") if isinstance(body, dict) else None
    return d if isinstance(d, str) else json.dumps(d) if d else "Unknown error"


def create_rule(agent_id: str, rule: Dict[str, Any]) -> Tuple[bool, str, Optional[str]]:
    """Create a rule (always in watch mode). Returns (ok, message for the user, rule id)."""
    status, body = _api("POST", "/rules", {**rule, "agent_id": rule.get("agent_id") or agent_id})
    _fetch_suggestions.clear()
    _rule_stats.clear()
    if status == 201:
        return True, (f"Added rule “{body['id']}”. It's watching: it counts matching calls and blocks nothing "
                      f"until you turn on blocking."), body["id"]
    return False, f"Couldn't add the rule: {_detail(body)}", None


def try_rule(agent_id: str, rule: Dict[str, Any]) -> Tuple[str, str]:
    """
    Send the call the rule is meant to catch through POST /guard, the way the agent
    would. Repeat-count rules get as many calls as they need. Returns (kind, message):
    kind is "blocked", "watching" (would have blocked), "allowed" or "error".
    """
    rid, tool = rule["id"], rule["match"]["tool"]
    args = _example_args(rule)
    repeat = max([int(c.get("value", 1)) for c in rule.get("session_conditions", [])] or [1])
    session = f"dashboard-test-{rid}-{os.urandom(3).hex()}"
    body: Dict[str, Any] = {}
    for _ in range(repeat):
        status, body = _api("POST", "/guard", {"agent_id": agent_id, "tool": tool, "args": args,
                                               "session_id": session})
        if status != 200:
            return "error", _detail(body)
    call = f"{tool}({', '.join(f'{k}={json.dumps(v)}' for k, v in args.items())})"
    if repeat > 1:
        call = f"{call} × {repeat}"
    if body.get("rule_id") == rid:
        verb = "Flagged for review" if body["decision"] == "ESCALATE" else "Blocked"
        reason = (body.get("reason") or "").rstrip(". ")
        return "blocked", f"{verb}: {call} — “{reason}”. The tool never ran."
    if any(h["rule_id"] == rid for h in body.get("shadow_hits", [])):
        return "watching", f"Allowed: {call} — but the rule would have blocked it. It's only watching."
    return "allowed", f"Allowed: {call} — the rule doesn't match it."


def promote_rule(agent_id: str, rid: str) -> Tuple[bool, str]:
    status, body = _api("POST", f"/rules/{rid}/promote", params={"agent_id": agent_id})
    _fetch_suggestions.clear()
    _rule_stats.clear()
    if status in (200, 409):
        return True, "Blocking is on. Running agents pick it up within 30 seconds."
    return False, _detail(body)


def fetch_suggestion_data(agent_id: str) -> Dict[str, Any]:
    """{"suggestions": [...], "by_pattern": {pattern_id: {...}}} — cached for two minutes."""
    return _fetch_suggestions(st.session_state.get("api_key", ""), agent_id)


# ── Wording ──────────────────────────────────────────────────────────────────

def _e(v: Any) -> str:
    return html.escape(str(v))


def _value_text(v: Any) -> str:
    if isinstance(v, list):
        return ", ".join(_e(x) for x in v)
    return _e(v)


def _ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def sentence(rule: Dict[str, Any]) -> str:
    """'Block <code>refund_api</code> when amount is more than 500'."""
    m = rule.get("match", {})
    parts = [f"{_e(p['field'])} {_OP_WORDS.get(p['op'], _e(p['op']))} {_value_text(p['value'])}"
             for p in m.get("args", [])]
    for c in rule.get("session_conditions", []):
        mins = c["window_seconds"] / 60
        window = f"{mins:g} minutes" if mins >= 1 else f"{c['window_seconds']} seconds"
        if c["op"] == ">=":
            parts.append(f"it's the {_ordinal(int(c['value']))} call or more within {window}")
        else:
            parts.append(f"it's called {_e(c['op'])} {_e(c['value'])} times within {window}")
    verb = _VERB.get(rule.get("action"), _e(rule.get("action")))
    when = f"when {' and '.join(parts)}" if parts else "on every call"
    return f"{verb} <code>{_e(m.get('tool'))}</code> {when}"


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _stats_line(stats: Dict[str, Any], rule: Dict[str, Any]) -> str:
    if rule.get("mode") == "enforce":
        n = stats.get("denied", 0) + stats.get("escalated", 0)
        return f"{_PAST.get(rule.get('action'), 'blocked').capitalize()} {_plural(n, 'call')} so far."
    wb = stats.get("would_block", 0)
    if not wb:
        return "No matching calls yet."
    failed = stats.get("would_block_sessions_that_failed", 0)
    tail = f" · {failed} of those sessions failed" if failed else ""
    return (f"Would have {_PAST.get(rule.get('action'), 'blocked')} {_plural(wb, 'call')} "
            f"in {_plural(stats.get('would_block_sessions', 0), 'session')}{tail}.")


def _slug(*parts: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", "_".join(p for p in parts if p).lower()).strip("_")[:48] or "rule"


def _parse_value(raw: str, op: str) -> Any:
    """Form input -> JSON value: numbers stay numbers, 'in' takes a comma list."""
    raw = raw.strip()
    if op == "in":
        return [_parse_value(x, "==") for x in raw.split(",") if x.strip()]
    try:
        return json.loads(raw)
    except ValueError:
        return raw


def _clearly_above(v: float) -> float:
    """A round value well over the limit (450 -> 900) so a test call is obviously one to stop."""
    if v <= 0:
        return v + 1
    nice = float(f"{v * 2:.2g}")
    nice = nice if nice > v else v + 1
    return int(nice) if float(nice).is_integer() else nice


def _example_args(rule: Dict[str, Any]) -> Dict[str, Any]:
    """Arguments that would match the rule, to prefill 'Try it'."""
    out: Dict[str, Any] = {}
    for p in rule.get("match", {}).get("args", []):
        v = p["value"]
        if p["op"] == ">" and isinstance(v, (int, float)):
            v = _clearly_above(v)
        elif p["op"] == "<" and isinstance(v, (int, float)):
            v = v - 1
        elif p["op"] == "in" and isinstance(v, list) and v:
            v = v[0]
        node = out
        *path, last = p["field"].split(".")
        for key in path:
            node = node.setdefault(key, {})
        node[last] = v
    return out


# ── Page ─────────────────────────────────────────────────────────────────────

def show_rules(agent_id: str) -> None:
    st.markdown(_CSS, unsafe_allow_html=True)
    head, btn = st.columns([5, 1.2], vertical_alignment="center")
    head.markdown(
        '<h1 style="margin-bottom:2px">Rules</h1>'
        '<p style="font-size:14px;color:#64748b;margin:0">Stop known failures before your agent repeats them.</p>',
        unsafe_allow_html=True,
    )
    st.markdown('<div style="height:12px"></div>', unsafe_allow_html=True)
    if btn.button("＋ New rule", type="primary", use_container_width=True, key="new_rule"):
        _new_rule_dialog(agent_id)

    flash = st.session_state.pop("rule_flash", None)
    if flash:
        getattr(st, flash[0])(flash[1])

    status, body = _api("GET", "/rules", params={"agent_id": agent_id})
    if status != 200:
        st.error(f"Couldn't load rules: {_detail(body)}")
        return
    rules: List[Dict[str, Any]] = body.get("rules", [])

    suggestions = fetch_suggestion_data(agent_id).get("suggestions", [])
    hidden = st.session_state.setdefault("hidden_suggestions", set())
    suggestions = [x for x in suggestions if not x.get("rule") or (
        _rule_sig(x["rule"]) not in hidden and not any(_same_rule(x["rule"], r) for r in rules))]

    if suggestions:
        _section("Suggested for you", "Based on failures Kalytera already detected for this agent.")
        for i, sug in enumerate(suggestions):
            _suggestion_card(agent_id, sug, i)

    if rules:
        _section("Your rules")
        for rule in rules:
            _rule_card(agent_id, rule)
    else:
        _empty_state(agent_id, has_suggestions=bool(suggestions))


def _section(title: str, sub: str = "") -> None:
    sub_html = f'<div class="kr-meta" style="margin-top:2px">{_e(sub)}</div>' if sub else ""
    st.markdown(f'<div style="margin:18px 0 8px"><div style="font-size:15px;font-weight:700;color:#0f172a">'
                f'{_e(title)}</div>{sub_html}</div>', unsafe_allow_html=True)


@st.cache_data(ttl=120, show_spinner="Looking for rules that would have prevented recent failures…")
def _fetch_suggestions(api_key: str, agent_id: str) -> Dict[str, Any]:
    try:
        r = requests.get(f"{API}/rules/suggestions", params={"agent_id": agent_id}, timeout=30,
                         headers={"Authorization": f"Bearer {api_key}"} if api_key else {})
        body = r.json() if r.status_code == 200 else {}
    except Exception:
        body = {}
    return {"suggestions": body.get("suggestions", []), "by_pattern": body.get("by_pattern", {})}


@st.cache_data(ttl=30, show_spinner=False)
def _rule_stats(api_key: str, agent_id: str, rule_id: str, version: Any) -> Dict[str, Any]:
    """Cached so moving between pages doesn't make one API call per rule each time."""
    try:
        r = requests.get(f"{API}/rules/{rule_id}/stats", params={"agent_id": agent_id}, timeout=15,
                         headers={"Authorization": f"Bearer {api_key}"} if api_key else {})
        return r.json() if r.status_code == 200 else {}
    except Exception:
        return {}


def _rule_sig(rule: Dict[str, Any]) -> str:
    return json.dumps({k: rule.get(k) or None for k in ("match", "session_conditions", "action")}, sort_keys=True)


def _empty_state(agent_id: str, has_suggestions: bool) -> None:
    with st.container(border=True):
        hint = ("Add a suggestion above, or write your own." if has_suggestions else
                "Suggestions appear here once Kalytera sees the same failure repeat in traces that "
                "include <code>tool_calls</code>.")
        st.markdown(
            '<div class="kr-empty"><div class="kr-empty-title">No rules yet</div>'
            'A rule checks a tool call before your agent makes it — for example, '
            f'<i>block refunds over 500</i>. New rules only <b>watch</b> at first, so trying one is safe.<br/>'
            f'<span style="color:#94a3b8">{hint}</span></div>',
            unsafe_allow_html=True,
        )
        _, c1, _ = st.columns([2, 1.2, 2])
        if c1.button("＋ Create a rule", use_container_width=True, key="empty_new",
                     type="secondary" if has_suggestions else "primary"):
            _new_rule_dialog(agent_id)


def _same_rule(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    keys = ("match", "session_conditions", "action")
    return a.get("id") == b.get("id") or all((a.get(k) or None) == (b.get(k) or None) for k in keys)


def _citation(sug: Dict[str, Any]) -> str:
    """'Would have caught 10 of 10 failed sessions · 0 of 20 successful ones'."""
    cov = sug.get("coverage") or {}
    if not cov.get("failing_total"):
        return ""
    fm, ft = cov["failing_matched"], cov["failing_total"]
    pm, pt = cov.get("passing_matched", 0), cov.get("passing_total", 0)
    good = '<span style="color:#16a34a;font-weight:600">' if pm == 0 else '<span style="color:#b45309;font-weight:600">'
    passing = f" · {good}{pm} of {pt} successful ones</span>" if pt else ""
    return (f'Would have caught <b>{fm} of {_plural(ft, "failed session")}</b>{passing}')


def _suggestion_card(agent_id: str, sug: Dict[str, Any], i: int) -> None:
    rule = sug.get("rule")
    with st.container(border=True):
        if not rule:
            st.markdown('<div class="kr-name">NO RULE SUGGESTED</div>', unsafe_allow_html=True)
            for w in sug.get("warnings", []):
                st.markdown(f'<div class="kr-meta">{w}</div>', unsafe_allow_html=True)
            return
        text, actions = st.columns([4, 2.4], vertical_alignment="center")
        causes = [p.get("root_cause") for p in sug.get("patterns", []) if p.get("root_cause")]
        cause = f'<div class="kr-meta">Failure seen: {_e(causes[0])}</div>' if causes else ""
        text.markdown(
            f'<div class="kr-sentence">{sentence(rule)}</div>'
            f'<div class="kr-meta">{_citation(sug)}</div>{cause}',
            unsafe_allow_html=True,
        )
        a1, a2, a3 = actions.columns([1.6, 1, 0.55])
        if a1.button("Add rule", type="primary", key=f"add_sug_{i}", use_container_width=True,
                     help="Adds it in watch mode: it counts matches but never blocks"):
            _create(agent_id, rule)
        if a2.button("Not now", key=f"hide_sug_{i}", use_container_width=True):
            st.session_state.setdefault("hidden_suggestions", set()).add(_rule_sig(rule))
            st.rerun()
        with a3.popover("⋯", use_container_width=True):
            if st.button("Edit before adding", key=f"edit_sug_{i}", use_container_width=True):
                _json_dialog(agent_id, rule, mode="create")
            st.markdown("**Why this rule?**")
            for line in sug.get("evidence", []):
                st.markdown(f"- {line}")
            for w in sug.get("warnings", []):
                st.caption(w)


def _rule_card(agent_id: str, rule: Dict[str, Any]) -> None:
    rid, mode = rule["id"], rule.get("mode", "shadow")
    stats = _rule_stats(st.session_state.get("api_key", ""), agent_id, rid, rule.get("version"))
    pill = ('<span class="kr-pill kr-block" title="Enforce mode">Blocking</span>' if mode == "enforce"
            else '<span class="kr-pill kr-watch" title="Shadow mode: counts matches, never blocks">Watching</span>')
    with st.container(border=True):
        text, actions = st.columns([4, 2.4], vertical_alignment="center")
        reason = f' · {_e(rule["reason"])}' if rule.get("reason") else ""
        text.markdown(
            f'<div class="kr-name">{_e(rid)}{pill}</div>'
            f'<div class="kr-sentence">{sentence(rule)}</div>'
            f'<div class="kr-meta">{_stats_line(stats, rule)}{reason}</div>',
            unsafe_allow_html=True,
        )
        a1, a2, a3 = actions.columns([1.6, 1, 0.55])
        if mode == "shadow":
            if a1.button("Start blocking", key=f"promote_{rid}", type="primary", use_container_width=True):
                _promote_dialog(agent_id, rule, stats)
        elif a1.button("Stop blocking", key=f"demote_{rid}", use_container_width=True,
                       help="Back to watching: counts matches, never blocks"):
            _act("POST", f"/rules/{rid}/demote", agent_id, f"“{rid}” is watching again — it won't block anything.")
        if a2.button("Try it", key=f"tryopen_{rid}", use_container_width=True):
            _try_dialog(agent_id, rule)
        menu_kwargs = {"key": f"menu_{rid}_{rule.get('version')}"} if _POPOVER_TAKES_KEY else {}
        with a3.popover("⋯", use_container_width=True, **menu_kwargs):
            if st.button("Edit", key=f"edit_{rid}", use_container_width=True):
                _json_dialog(agent_id, rule, mode="edit")
            if st.button("Delete", key=f"delete_{rid}", use_container_width=True):
                _delete_dialog(agent_id, rid)


# ── Dialogs ──────────────────────────────────────────────────────────────────

@st.dialog("New rule")
def _new_rule_dialog(agent_id: str) -> None:
    st.caption("New rules only watch: they count matching calls and never block until you say so.")
    tool = st.text_input("When the agent calls", placeholder="refund_api",
                         help="The tool name your code passes to guard()")
    c1, c2, c3 = st.columns([1.3, 1.2, 1])
    field = c1.text_input("with", placeholder="amount",
                          help="An argument of the call. Leave empty to match every call. Nested: customer.tier")
    op_word = c2.selectbox("that", list(OPS), index=0)
    value = c3.text_input("value", placeholder="500", help="For “is one of”, separate values with commas")
    action_word = st.radio("then", list(_ACTIONS), horizontal=True)

    with st.expander("More options"):
        reason = st.text_input("Reason (returned to your code)", placeholder="Refunds over 500 need review")
        repeat = st.number_input("Only from the Nth call in one session (0 = off)", min_value=0, value=0, step=1,
                                 help="Catches loops: 3 = the 3rd call or more within the window")
        window = st.number_input("…within minutes", min_value=1, value=10, step=1)
        name = st.text_input("Rule name", placeholder=_slug(tool, field) if tool else "refund_cap")

    if st.button("Create rule", type="primary", use_container_width=True, key="dlg_create"):
        if not tool.strip():
            st.error("Which tool should this rule check?")
            return
        op = OPS[op_word]
        rule: Dict[str, Any] = {
            "id": name.strip() or _slug(tool, field),
            "match": {"tool": tool.strip(), "args": []},
            "action": _ACTIONS[action_word],
            "reason": reason.strip(),
        }
        if field.strip():
            if not value.strip():
                st.error(f"What should {field.strip()} be compared to?")
                return
            rule["match"]["args"].append({"field": field.strip(), "op": op, "value": _parse_value(value, op)})
        if repeat:
            rule["session_conditions"] = [{"type": "count_in_window", "tool": tool.strip(), "op": ">=",
                                           "value": int(repeat), "window_seconds": int(window) * 60}]
        _create(agent_id, rule)
    with st.expander("Write it as JSON instead"):
        _json_editor(agent_id, {**_TEMPLATE, "agent_id": agent_id}, mode="create", key="dlg_json")


@st.dialog("Edit rule")
def _json_dialog(agent_id: str, rule: Dict[str, Any], mode: str) -> None:
    if mode == "edit":
        st.caption("Saving creates a new version. Watching or blocking stays as it is.")
    _json_editor(agent_id, rule, mode, key=f"json_{mode}_{rule.get('id')}")


def _json_editor(agent_id: str, rule: Dict[str, Any], mode: str, key: str) -> None:
    editable = {k: v for k, v in rule.items() if k not in ("version", "mode", "agent_id")}
    text = st.text_area("Rule", value=json.dumps(editable, indent=2), height=240, key=key,
                        label_visibility="collapsed")
    if st.button("Save" if mode == "edit" else "Create rule", type="primary", key=f"{key}_save"):
        try:
            new = json.loads(text)
        except ValueError as exc:
            st.error(f"That isn't valid JSON: {exc}")
            return
        if mode != "edit":
            _create(agent_id, new)
            return
        new["agent_id"] = agent_id
        status, body = _api("PUT", f"/rules/{rule['id']}", new)
        if status == 200:
            st.session_state["rule_flash"] = ("success", f"Saved “{rule['id']}” (version {body['version']}).")
            st.rerun()
        st.error(_detail(body))


@st.dialog("Start blocking?")
def _promote_dialog(agent_id: str, rule: Dict[str, Any], stats: Dict[str, Any]) -> None:
    rid = rule["id"]
    st.markdown(f'<div class="kr-sentence">{sentence(rule)}</div>', unsafe_allow_html=True)
    wb = stats.get("would_block", 0)
    if wb:
        failed = stats.get("would_block_sessions_that_failed", 0)
        st.write(f"While watching, it matched **{_plural(wb, 'call')}** in "
                 f"**{_plural(stats.get('would_block_sessions', 0), 'session')}**"
                 + (f", and **{failed}** of those sessions failed." if failed else "."))
    else:
        st.write("It hasn't matched any calls yet, so there's no evidence yet that it targets real failures.")
    st.write(f"From now on, `guard()` returns **{rule.get('action')}** for matching calls. "
             "Running agents pick this up within 30 seconds.")
    c1, c2 = st.columns(2)
    if c1.button("Start blocking", type="primary", use_container_width=True, key=f"yes_promote_{rid}"):
        _act("POST", f"/rules/{rid}/promote", agent_id, f"“{rid}” is now blocking.")
    if c2.button("Cancel", use_container_width=True, key=f"no_promote_{rid}"):
        st.rerun()


@st.dialog("Delete rule?")
def _delete_dialog(agent_id: str, rid: str) -> None:
    st.write(f"**{rid}** stops applying right away (within 30 seconds in running agents). Its history is kept.")
    c1, c2 = st.columns(2)
    if c1.button("Delete", type="primary", use_container_width=True, key=f"yes_delete_{rid}"):
        _act("DELETE", f"/rules/{rid}", agent_id, f"Deleted “{rid}”.")
    if c2.button("Cancel", use_container_width=True, key=f"no_delete_{rid}"):
        st.rerun()


# ── Actions ──────────────────────────────────────────────────────────────────

def _create(agent_id: str, rule: Dict[str, Any]) -> None:
    ok, msg, _ = create_rule(agent_id, rule)
    if ok:
        st.session_state["rule_flash"] = ("success", msg + " Use **Try it** to see what it would do.")
        st.rerun()
    st.error(msg)


def _act(method: str, path: str, agent_id: str, ok: str) -> None:
    status, body = _api(method, path, params={"agent_id": agent_id})
    _fetch_suggestions.clear()
    _rule_stats.clear()
    st.session_state["rule_flash"] = ("success", ok) if status == 200 else ("error", _detail(body))
    st.rerun()


@st.dialog("Try it")
def _try_dialog(agent_id: str, rule: Dict[str, Any]) -> None:
    rid, tool = rule["id"], rule["match"]["tool"]
    st.markdown(f'<div class="kr-sentence">{sentence(rule)}</div>', unsafe_allow_html=True)
    st.caption(f"What would happen if your agent called `{tool}` with these arguments?")
    args_text = st.text_area("Arguments", value=json.dumps(_example_args(rule)), height=80,
                             key=f"try_args_{rid}", help="JSON — the same arguments your agent would pass")
    if not st.button("Check", type="primary", key=f"try_{rid}"):
        return
    try:
        args = json.loads(args_text or "{}")
        assert isinstance(args, dict)
    except (ValueError, AssertionError):
        st.error('Arguments must be a JSON object, like {"amount": 900}')
        return
    # One session per rule, so repeat-call rules count the calls you try here.
    status, body = _api("POST", "/guard", {"agent_id": agent_id, "tool": tool, "args": args,
                                           "session_id": f"dashboard-try-{rid}"})
    if status != 200:
        st.error(_detail(body))
        return
    hit = next((h for h in body.get("shadow_hits", []) if h["rule_id"] == rid), None)
    if body["rule_id"] == rid:
        st.error(f"**{_PAST.get(body['decision'], 'blocked').capitalize()}.** {body['reason']}")
    elif hit:
        st.info(f"**Allowed** — but this rule **would have {_PAST.get(hit['action'], 'blocked')}** it. "
                "It's only watching.")
    else:
        st.success("**Allowed** — this rule doesn't match these arguments.")
    with st.expander("Same check with curl"):
        payload = json.dumps({"agent_id": agent_id, "tool": tool, "args": args, "session_id": "s1"})
        st.code(f"curl -s -X POST {API}/guard \\\n  -H \"Authorization: Bearer $KALYTERA_API_KEY\" \\\n"
                f"  -H 'Content-Type: application/json' \\\n  -d '{payload}'", language="bash")
