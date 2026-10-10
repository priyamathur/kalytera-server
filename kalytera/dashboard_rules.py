"""
Rules view for the Streamlit dashboard — guard rules without writing Python.

Create a rule (form or JSON, or from a failure pattern's draft), watch its
shadow would-blocks, promote/demote it, and test a call against it. Everything
goes through the Kalytera API with the signed-in user's key, so the dashboard
sees exactly what guard() sees.
"""
import html
import json
import os
from typing import Any, Dict, List, Optional, Tuple

import requests
import streamlit as st

API = os.getenv("KALYTERA_API_ENDPOINT", "https://api.kalytera.dev").rstrip("/")
OPS = ["==", "!=", ">", ">=", "<", "<=", "in"]

_TEMPLATE = {
    "id": "refund_cap",
    "match": {"tool": "refund_api", "args": [{"field": "amount", "op": ">", "value": 500}]},
    "action": "DENY",
    "reason": "Refunds over 500 need review",
}


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


def request_draft(pattern_id: str) -> None:
    """on_click callback for a pattern card's button: fetch a draft and open the Rules view.

    Runs before the page reruns, so it may set the navigation widget's state.
    """
    status, body = _api("POST", "/rules/draft", {"pattern_id": pattern_id})
    if status != 200:
        st.session_state["rule_flash"] = ("error", f"Couldn't draft a rule: {_detail(body)}")
    else:
        st.session_state["rule_draft"] = body
    st.session_state["view"] = "🛡  Rules"


# ── Formatting ───────────────────────────────────────────────────────────────

def _e(v: Any) -> str:
    return html.escape(str(v))


def _summary(rule: Dict[str, Any]) -> str:
    """'DENY refund_api when amount > 500 and on the 3rd+ call in 10 min'."""
    m = rule.get("match", {})
    parts = [f"{_e(p['field'])} {_e(p['op'])} {_e(json.dumps(p['value']))}" for p in m.get("args", [])]
    for c in rule.get("session_conditions", []):
        mins = c["window_seconds"] / 60
        window = f"{mins:g} min" if mins >= 1 else f"{c['window_seconds']}s"
        parts.append(f"{_e(c['tool'])} called {_e(c['op'])} {_e(c['value'])}× in {window}")
    cond = " and ".join(parts) if parts else "every call"
    return f"<b>{_e(rule.get('action'))}</b> <code>{_e(m.get('tool'))}</code> when {cond}"


def _mode_badge(mode: str) -> str:
    if mode == "enforce":
        return ('<span style="background:#fef2f2;color:#dc2626;padding:2px 9px;border-radius:5px;'
                'font-size:11px;font-weight:800;letter-spacing:.04em">ENFORCED</span>')
    return ('<span style="background:#eef2ff;color:#4f46e5;padding:2px 9px;border-radius:5px;'
            'font-size:11px;font-weight:800;letter-spacing:.04em">SHADOW</span>')


def _parse_value(raw: str, op: str) -> Any:
    """Form input -> JSON value: numbers stay numbers, 'in' takes a comma list."""
    raw = raw.strip()
    if op == "in":
        items = [x.strip() for x in raw.split(",") if x.strip()]
        return [_parse_value(x, "==") for x in items]
    try:
        return json.loads(raw)
    except ValueError:
        return raw


# ── Page ─────────────────────────────────────────────────────────────────────

def show_rules(agent_id: str) -> None:
    st.markdown(
        '<div style="margin-bottom:20px"><h1>Rules</h1>'
        '<p style="font-size:13px;color:#64748b;margin-top:4px">'
        f'Block known failures for <b>{_e(agent_id)}</b> before they happen. New rules start in '
        '<b>shadow</b>: they count what they would have blocked and never change your agent\'s behavior. '
        'Promote a rule when its numbers look right.</p></div>',
        unsafe_allow_html=True,
    )
    flash = st.session_state.pop("rule_flash", None)
    if flash:
        getattr(st, flash[0])(flash[1])

    status, body = _api("GET", "/rules", params={"agent_id": agent_id})
    if status != 200:
        st.error(f"Couldn't load rules: {_detail(body)}", icon="🔴")
        return
    rules: List[Dict[str, Any]] = body.get("rules", [])

    _create_section(agent_id, has_rules=bool(rules))
    st.markdown('<h2 style="margin:24px 0 8px">Your rules</h2>', unsafe_allow_html=True)
    if not rules:
        st.info("No rules yet. Create one above, or open the Failure Feed and click "
                "**Draft a rule** on a pattern.")
    for rule in rules:
        _rule_card(agent_id, rule)

    st.markdown('<h2 style="margin:28px 0 8px">Test a call</h2>', unsafe_allow_html=True)
    _test_section(agent_id, rules)


def _create_section(agent_id: str, has_rules: bool) -> None:
    draft = st.session_state.get("rule_draft")
    with st.expander("➕  Create a rule" if not draft else "✏️  Review the drafted rule",
                     expanded=bool(draft) or not has_rules):
        if draft:
            st.markdown("**Drafted from a failure pattern. Nothing is saved until you click Create.**")
            for line in draft.get("evidence", []):
                st.markdown(f"- {line}")
            for w in draft.get("warnings", []):
                st.warning(w)
            if not draft.get("rule"):
                if st.button("Dismiss draft", key="dismiss_draft"):
                    st.session_state.pop("rule_draft", None)
                    st.rerun()
                return

        tab_form, tab_json = st.tabs(["Form", "JSON"])
        with tab_form:
            if draft:
                st.caption("This draft was generated as JSON — review and edit it in the JSON tab.")
            else:
                _create_form(agent_id)
        with tab_json:
            start = (draft or {}).get("rule") or {**_TEMPLATE, "agent_id": agent_id}
            text = st.text_area("Rule JSON", value=json.dumps(start, indent=2), height=260,
                                key=f"rule_json_{hash(json.dumps(start, sort_keys=True))}")
            c1, c2 = st.columns([1, 1])
            if c1.button("Create in shadow mode", key="create_json", type="primary"):
                try:
                    rule = json.loads(text)
                except ValueError as exc:
                    st.error(f"That isn't valid JSON: {exc}")
                    return
                _create(agent_id, rule)
            if draft and c2.button("Discard draft", key="discard_draft"):
                st.session_state.pop("rule_draft", None)
                st.rerun()


def _create_form(agent_id: str) -> None:
    with st.form("rule_form", clear_on_submit=False):
        c1, c2 = st.columns(2)
        rule_id = c1.text_input("Rule name", placeholder="refund_cap")
        tool = c2.text_input("Tool", placeholder="refund_api", help="The tool name your agent passes to guard()")
        st.markdown("**When an argument…** (leave the field empty to match every call to the tool)")
        a1, a2, a3 = st.columns([2, 1, 2])
        field = a1.text_input("Argument", placeholder="amount", help="Nested fields: customer.tier")
        op = a2.selectbox("is", OPS, index=2)
        value = a3.text_input("Value", placeholder="500", help="For 'in', separate values with commas")
        st.markdown("**…and/or the tool is called repeatedly** (0 = off)")
        r1, r2 = st.columns(2)
        repeat = r1.number_input("Times in one session", min_value=0, value=0, step=1)
        window = r2.number_input("Within minutes", min_value=1, value=10, step=1)
        b1, b2 = st.columns([1, 2])
        action = b1.selectbox("Then", ["DENY", "ESCALATE"])
        reason = b2.text_input("Reason shown to your code", placeholder="Refunds over 500 need review")
        submitted = st.form_submit_button("Create in shadow mode", type="primary")
    if not submitted:
        return
    if not rule_id.strip() or not tool.strip():
        st.error("Rule name and tool are required.")
        return
    rule: Dict[str, Any] = {
        "id": rule_id.strip(), "agent_id": agent_id,
        "match": {"tool": tool.strip(), "args": []},
        "action": action, "reason": reason.strip(),
    }
    if field.strip():
        if not value.strip():
            st.error("Give the argument a value to compare against.")
            return
        rule["match"]["args"].append({"field": field.strip(), "op": op, "value": _parse_value(value, op)})
    if repeat:
        rule["session_conditions"] = [{"type": "count_in_window", "tool": tool.strip(), "op": ">=",
                                       "value": int(repeat), "window_seconds": int(window) * 60}]
    _create(agent_id, rule)


def _create(agent_id: str, rule: Dict[str, Any]) -> None:
    rule.setdefault("agent_id", agent_id)
    status, body = _api("POST", "/rules", rule)
    if status == 201:
        st.session_state.pop("rule_draft", None)
        st.session_state["rule_flash"] = ("success", f"Created **{body['id']}** in shadow mode. "
                                          "Its would-blocks will show up below as your agent runs.")
        st.rerun()
    else:
        st.error(_detail(body))


def _rule_card(agent_id: str, rule: Dict[str, Any]) -> None:
    rid = rule["id"]
    _, stats = _api("GET", f"/rules/{rid}/stats", params={"agent_id": agent_id})
    stats = stats if isinstance(stats, dict) else {}
    with st.container(border=True):
        st.markdown(
            f'<div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:6px">'
            f'<span style="font-size:15px;font-weight:800;color:#0f172a">{_e(rid)}</span>'
            f'{_mode_badge(rule.get("mode", "shadow"))}'
            f'<span style="font-size:12px;color:#94a3b8">v{_e(rule.get("version"))}</span></div>'
            f'<div style="font-size:14px;color:#1e293b;margin-bottom:4px">{_summary(rule)}</div>'
            f'<div style="font-size:12px;color:#64748b;margin-bottom:10px">{_e(rule.get("reason", ""))}</div>',
            unsafe_allow_html=True,
        )
        wb, wbs, failed = stats.get("would_block", 0), stats.get("would_block_sessions", 0), \
            stats.get("would_block_sessions_that_failed", 0)
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Would have blocked", wb, help="Shadow-mode matches. The agent was allowed to proceed.")
        k2.metric("Sessions", wbs)
        k3.metric("…that failed anyway", failed,
                  help="Of those sessions, how many the judge scored as failed. High = the rule targets real failures.")
        k4.metric("Blocked (enforced)", stats.get("denied", 0) + stats.get("escalated", 0))

        b1, b2, b3, _ = st.columns([1.3, 1, 1, 2])
        if rule.get("mode") == "shadow":
            if b1.button("Promote to enforce", key=f"promote_{rid}", type="primary"):
                st.session_state[f"confirm_promote_{rid}"] = True
        elif b1.button("Demote to shadow", key=f"demote_{rid}"):
            _act("POST", f"/rules/{rid}/demote", agent_id, f"**{rid}** is back in shadow mode.")
        edit_open = b2.button("Edit", key=f"edit_{rid}")
        if b3.button("Delete", key=f"delete_{rid}"):
            st.session_state[f"confirm_delete_{rid}"] = True

        if st.session_state.get(f"confirm_promote_{rid}"):
            st.warning(f"Enforcing **{rid}** means guard() returns {rule.get('action')} for matching calls. "
                       f"In shadow mode it matched **{wb}** call(s) across **{wbs}** session(s); "
                       f"**{failed}** of those sessions failed anyway.")
            c1, c2, _ = st.columns([1, 1, 3])
            if c1.button("Yes, enforce", key=f"yes_promote_{rid}", type="primary"):
                st.session_state.pop(f"confirm_promote_{rid}", None)
                _act("POST", f"/rules/{rid}/promote", agent_id, f"**{rid}** is now enforced.")
            if c2.button("Cancel", key=f"no_promote_{rid}"):
                st.session_state.pop(f"confirm_promote_{rid}", None)
                st.rerun()

        if st.session_state.get(f"confirm_delete_{rid}"):
            st.error(f"Delete **{rid}**? guard() stops applying it immediately (within 30s in running agents).")
            c1, c2, _ = st.columns([1, 1, 3])
            if c1.button("Yes, delete", key=f"yes_delete_{rid}"):
                st.session_state.pop(f"confirm_delete_{rid}", None)
                _act("DELETE", f"/rules/{rid}", agent_id, f"Deleted **{rid}**.")
            if c2.button("Cancel", key=f"no_delete_{rid}"):
                st.session_state.pop(f"confirm_delete_{rid}", None)
                st.rerun()

        if edit_open:
            st.session_state[f"editing_{rid}"] = True
        if st.session_state.get(f"editing_{rid}"):
            editable = {k: v for k, v in rule.items() if k not in ("version", "mode", "agent_id")}
            text = st.text_area("Edit rule (saves a new version; mode stays the same)",
                                value=json.dumps(editable, indent=2), height=220, key=f"edit_text_{rid}")
            c1, c2, _ = st.columns([1, 1, 3])
            if c1.button("Save new version", key=f"save_{rid}", type="primary"):
                try:
                    new = json.loads(text)
                except ValueError as exc:
                    st.error(f"That isn't valid JSON: {exc}")
                    return
                new["agent_id"] = agent_id
                status, body = _api("PUT", f"/rules/{rid}", new)
                if status == 200:
                    st.session_state.pop(f"editing_{rid}", None)
                    st.session_state["rule_flash"] = ("success", f"Saved **{rid}** v{body['version']}.")
                    st.rerun()
                st.error(_detail(body))
            if c2.button("Cancel", key=f"cancel_edit_{rid}"):
                st.session_state.pop(f"editing_{rid}", None)
                st.rerun()


def _act(method: str, path: str, agent_id: str, ok: str) -> None:
    status, body = _api(method, path, params={"agent_id": agent_id})
    st.session_state["rule_flash"] = ("success", ok) if status == 200 else ("error", _detail(body))
    st.rerun()


def _test_section(agent_id: str, rules: List[Dict[str, Any]]) -> None:
    st.caption("Runs the call through POST /guard — the same rules and the same decision your agent gets. "
               "Shadow results count toward the rule's would-blocks.")
    default_tool = rules[0]["match"]["tool"] if rules else "refund_api"
    with st.form("guard_test"):
        c1, c2 = st.columns([1, 1])
        tool = c1.text_input("Tool", value=default_tool)
        session_id = c2.text_input("Session ID", value="dashboard-test",
                                   help="Use the same ID several times to test repeated-call rules")
        args_text = st.text_area("Arguments (JSON)", value='{"amount": 900}', height=90)
        submitted = st.form_submit_button("Check this call", type="primary")
    if not submitted:
        return
    try:
        args = json.loads(args_text or "{}")
        assert isinstance(args, dict)
    except (ValueError, AssertionError):
        st.error('Arguments must be a JSON object, like {"amount": 900}')
        return
    status, body = _api("POST", "/guard", {"agent_id": agent_id, "tool": tool, "args": args,
                                           "session_id": session_id})
    if status != 200:
        st.error(_detail(body))
        return
    decision = body["decision"]
    if decision == "ALLOW":
        st.success(f"**ALLOW** — no enforced rule matched `{tool}`.")
    elif decision == "DENY":
        st.error(f"**DENY** by `{body['rule_id']}` v{body['rule_version']}: {body['reason']}")
    else:
        st.warning(f"**ESCALATE** by `{body['rule_id']}` v{body['rule_version']}: {body['reason']}")
    for h in body.get("shadow_hits", []):
        st.info(f"Shadow: `{h['rule_id']}` v{h['rule_version']} would have returned **{h['action']}** "
                f"(not applied — promote it to enforce).")
    curl_body = json.dumps({"agent_id": agent_id, "tool": tool, "args": args, "session_id": session_id})
    with st.expander("Same check with curl"):
        st.code(f"curl -s -X POST {API}/guard \\\n  -H 'Authorization: Bearer $KALYTERA_API_KEY' \\\n"
                f"  -H 'Content-Type: application/json' \\\n  -d '{curl_body}'", language="bash")
