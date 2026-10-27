"""
kalytera.check_reply() — check the agent's reply before the customer sees it.

    reply = run_agent(message)
    reply = kalytera.check_reply(reply).reply      # inside `with kalytera.session(...)`

1. Always, in code (no AI, no delay): a reply that says something was done —
   "your refund has been processed", "I've cancelled your order" — when the
   action for it failed, was blocked, or never ran in this conversation.
2. With review=True, replies about money, policy, accounts or legal matters
   are also read by Kalytera's AI reviewer before they're sent (adds about 1–3
   seconds to those replies only; review="always" checks every reply).

A held reply is replaced by a safe message and reported to Kalytera, which
alerts you in Slack. Never raises: if the reviewer can't be reached in time,
the reply goes out as it is and `.error` says why.
"""
import re
import threading
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Union

SAFE_REPLY = ("Sorry, I couldn't complete that just now. Someone from our team will follow up with you "
              "shortly.")
REVIEW_TIMEOUT = 8.0  # seconds; past this the reply is sent unchecked by the AI (the code check still ran)
REPLY_CHARS = 4000

# What a claimed action is about, and the action names that would do it.
_CATEGORY_STEMS: Dict[str, Sequence[str]] = {
    "refund": ("refund", "reimburs", "return"),
    "cancel": ("cancel", "terminat", "void"),
    "delete": ("delet", "remov", "eras", "wipe", "purge", "destroy"),
    "book": ("book", "reserv", "schedul", "appoint"),
    "send": ("send", "email", "mail", "notify", "message", "sms"),
    "update": ("updat", "chang", "reset", "modif", "edit", "set", "upgrad", "downgrad"),
    "pay": ("pay", "charg", "transfer", "credit", "refund", "wire", "payout"),
    "order": ("order", "checkout", "purchase"),
}
_VERB_CATEGORY = {
    "refunded": "refund", "reimbursed": "refund",
    "cancelled": "cancel", "canceled": "cancel", "terminated": "cancel", "voided": "cancel",
    "deleted": "delete", "removed": "delete", "erased": "delete", "wiped": "delete",
    "booked": "book", "reserved": "book", "rescheduled": "book",
    "sent": "send", "emailed": "send",
    "updated": "update", "changed": "update", "reset": "update", "modified": "update",
    "upgraded": "update", "downgraded": "update",
    "paid": "pay", "charged": "pay", "transferred": "pay", "credited": "pay",
}
_GENERIC = ("processed", "completed", "submitted", "placed", "approved", "issued", "applied", "done", "confirmed")
_NOUN_CATEGORY = (
    ("refund", "refund"), ("reimburse", "refund"), ("cancel", "cancel"), ("booking", "book"),
    ("reservation", "book"), ("appointment", "book"), ("payment", "pay"), ("charge", "pay"),
    ("transfer", "pay"), ("credit", "pay"), ("password", "update"), ("email address", "update"),
    ("account", "update"), ("order", "order"),
)
_VERBS = "|".join(sorted(list(_VERB_CATEGORY) + list(_GENERIC), key=len, reverse=True))
_CLAIMS = [
    # "I've refunded", "we have cancelled", "I just sent"
    re.compile(rf"\b(?:i|we)(?:'ve|\s+have)?(?:\s+(?:just|now|already|successfully))*\s+({_VERBS})\b", re.I),
    # "has been refunded", "have now been processed"
    re.compile(rf"\b(?:has|have|had)(?:\s+(?:now|already|just))*\s+been(?:\s+successfully)?\s+({_VERBS})\b", re.I),
    # "is now cancelled", "was successfully processed"
    re.compile(rf"\b(?:is|are|was|were)\s+(?:now|just|successfully)(?:\s+(?:been|successfully))*\s+({_VERBS})\b",
               re.I),
    # "successfully refunded", "processed successfully"
    re.compile(rf"\bsuccessfully\s+({_VERBS})\b", re.I),
    re.compile(rf"\b({_VERBS})\s+successfully\b", re.I),
]
# Words before a claim that make it not a claim: "once your refund has been processed", "if it was cancelled".
_NOT_A_CLAIM = re.compile(r"\b(?:not|never|unable|cannot|can't|couldn't|won't|wasn't|isn't|haven't|hasn't|once|if|"
                          r"when|after|until|before|will|would|should|could|can|may|might|pending|whether)\b|n't\b",
                          re.I)
_HIGH_STAKES = re.compile(
    r"[$€£¥₹]\s?\d|\b\d[\d,.]*\s?(?:dollars|usd|eur|euros|pounds|gbp)\b|\b(?:refund|reimburs|compensat|charge|"
    r"fee|price|discount|credit|payment|invoice|policy|policies|guarantee|warrant|entitled|eligible|waive|"
    r"exception|free of charge|legal|lawsuit|liab|contract|terms|cancel|delete|close your account|password|"
    r"medical|diagnos|medication|dosage|prescri)", re.I)


@dataclass(frozen=True)
class ReplyCheck:
    """What check_reply() decided. Send `.reply`: the original, or the safe message if it was held."""
    held: bool
    reply: str
    reason: str = ""
    original: str = ""
    checked_by: str = ""   # "code" | "ai" when held
    error: str = ""


def _sentences(text: str) -> List[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]


def _category(verb: str, sentence: str) -> Optional[str]:
    v = verb.lower()
    if v in _VERB_CATEGORY:
        return _VERB_CATEGORY[v]
    low = sentence.lower()
    for noun, cat in _NOUN_CATEGORY:
        if noun in low:
            return cat
    return None


def claims(reply: str) -> List[Dict[str, Any]]:
    """Statements that something was done: [{"text": "has been refunded", "category": "refund"}]."""
    found: List[Dict[str, Any]] = []
    for sentence in _sentences(reply or ""):
        for pattern in _CLAIMS:
            for m in pattern.finditer(sentence):
                before = sentence[:m.start()]
                if _NOT_A_CLAIM.search(before) or _NOT_A_CLAIM.search(m.group(0)):
                    continue
                found.append({"text": m.group(0).strip(), "category": _category(m.group(1), sentence),
                              "sentence": sentence.strip()})
    return found


def _ok(call: Dict[str, Any]) -> bool:
    return bool(call.get("success", True)) and not call.get("blocked") and not call.get("error")


def false_claim(reply: str, actions: List[Dict[str, Any]], tracked: bool) -> Optional[str]:
    """Why the reply claims something the actions don't back up, or None.

    tracked: whether this conversation's actions are being recorded at all (if not, a claim with no
    matching action can't be judged, so it isn't held)."""
    for c in claims(reply):
        stems = _CATEGORY_STEMS.get(c["category"] or "", ())
        relevant = [a for a in actions if not stems or any(s in str(a.get("name", "")).lower() for s in stems)]
        if any(_ok(a) for a in relevant):
            continue
        # A lookup that says so ("status: refunded") backs the reply up too.
        words = [c["text"].split()[-1].lower()[:6], *stems]
        if any(_ok(a) and any(w in str(a.get("output", "")).lower() for w in words) for a in actions):
            continue
        quote = c["sentence"] if len(c["sentence"]) <= 120 else c["sentence"][:117] + "…"
        said = f'The reply says "{quote}"'
        if relevant:
            bad = relevant[-1]
            what = "was blocked by a rule" if bad.get("blocked") else "failed"
            return f"{said}, but {bad.get('name')} {what}."
        if tracked:
            return f"{said}, but no action that does that ran in this conversation."
    return None


def high_stakes(reply: str) -> bool:
    """Money, policy, accounts, legal or medical: worth the AI reviewer's time."""
    return bool(_HIGH_STAKES.search(reply or ""))


def check_reply(
    reply: Any,
    *,
    actions: Optional[List[Dict[str, Any]]] = None,
    review: Union[bool, str] = False,
    message: Optional[str] = None,
    policy: Optional[str] = None,
    safe_reply: Optional[str] = None,
    session_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    timeout: float = REVIEW_TIMEOUT,
) -> ReplyCheck:
    """
    Check a reply before it's sent. Returns a ReplyCheck; send `.reply`.

    actions: this conversation's actions as [{"name", "success", "output"/"error"}]; inside
      kalytera.session() the ones made through @kalytera.tool are used.
    review: True = AI review for replies about money, policy, accounts or legal matters;
      "always" = every reply. policy: your rules in plain text (refund window, what agents may
      promise) so the reviewer can catch promises you don't make.
    safe_reply: what the customer gets instead of a held reply.
    """
    from .session import current_session
    from . import tracer

    text = "" if reply is None else str(reply)
    try:
        s = current_session()
        calls = list(actions) if actions is not None else (list(s.calls) if s is not None else [])
        tracked = actions is not None or bool(calls)
        sid = session_id or (s.session_id if s is not None else "")
        aid = agent_id or (s.agent_id if s is not None and s.agent_id else None) or tracer._agent_id
        msg = message if message is not None else (s.input if s is not None else "")

        reason = false_claim(text, calls, tracked)
        if reason:
            _report(aid, sid, text, reason, "code")
            return _held(text, reason, "code", safe_reply)

        if review and (review == "always" or high_stakes(text)):
            verdict, error = _review(aid, sid, msg, text, calls, policy, timeout)
            if verdict and verdict.get("hold"):
                return _held(text, str(verdict.get("reason") or "Kalytera's reviewer held this reply."), "ai",
                             safe_reply)
            if error:
                return ReplyCheck(False, text, original=text, error=error)
        return ReplyCheck(False, text, original=text)
    except Exception as exc:  # never break the agent because of Kalytera
        tracer._log_error(f"check_reply error: {exc}")
        return ReplyCheck(False, text, original=text, error=f"check_reply internal error: {exc}")


def _held(text: str, reason: str, by: str, safe_reply: Optional[str]) -> ReplyCheck:
    s = _current()
    if s is not None:
        s.held_reply = {"reason": reason, "checked_by": by}
    return ReplyCheck(True, safe_reply or SAFE_REPLY, reason=reason, original=text, checked_by=by)


def _current() -> Any:
    from .session import current_session

    return current_session()


def _masked(text: str) -> str:
    from . import tracer

    if tracer._redact:
        from .redact import mask
        return mask(text)
    return text


def _payload(agent_id: str, session_id: str, reply: str) -> Dict[str, Any]:
    return {"agent_id": agent_id, "session_id": session_id, "reply": _masked(reply)[:REPLY_CHARS]}


def _report(agent_id: str, session_id: str, reply: str, reason: str, by: str) -> None:
    """Tell Kalytera (which tells Slack) in the background; the customer isn't kept waiting."""
    from . import tracer

    body = {**_payload(agent_id, session_id, reply), "reason": reason, "checked_by": by}

    def send() -> None:
        status, _b, err = tracer._http("POST", "/replies/held", body)
        if status != 201:
            tracer._notify("replies_held", f"✗ Kalytera: a held reply wasn't reported (HTTP {status} {err or ''})")

    _in_background(send)


def _in_background(fn: Any) -> None:
    threading.Thread(target=fn, daemon=True).start()


def _review(agent_id: str, session_id: str, message: str, reply: str, actions: List[Dict[str, Any]],
            policy: Optional[str], timeout: float) -> "tuple[Optional[Dict[str, Any]], str]":
    from . import tracer

    body = {**_payload(agent_id, session_id, reply), "message": _masked(message or "")[:REPLY_CHARS],
            "actions": [{k: a.get(k) for k in ("name", "input", "success", "output", "error", "blocked")}
                        for a in actions][-20:],
            "policy": (policy or "")[:REPLY_CHARS]}
    if tracer._redact:
        body["actions"] = [{**a, "input": None} for a in body["actions"]]
    status, data, err = tracer._http("POST", "/replies/review", body, timeout=timeout)
    if status == 200 and isinstance(data, dict):
        return data, ""
    return None, f"AI review unavailable (HTTP {status or err}); the reply was sent unchanged"
