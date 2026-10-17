"""Hand-labelled conversations for comparing judge models.

Each case: id, label ("fail" / "pass"), expected failure type(s) when failing, and turns
(user, assistant, actions). Failing cases cover every built-in failure type; passing cases
include tricky ones (an action fails but the agent says so honestly, a correct refusal,
a clarifying question) where a weak judge raises false alarms.
"""
from typing import Any, Dict, List


def A(name: str, inp: Dict[str, Any], out: Any = "ok", success: bool = True, error: str = "") -> Dict[str, Any]:
    d = {"name": name, "input": inp, "output": out, "success": success}
    if error:
        d["error"] = error
    return d


def T(user: str, assistant: str, *actions: Dict[str, Any]) -> Dict[str, Any]:
    return {"user": user, "assistant": assistant, "actions": list(actions)}


CASES: List[Dict[str, Any]] = [
    # ---------------- hallucination: claims something the actions contradict or never did
    {"id": "hal-refund", "label": "fail", "types": ["hallucination", "tool_failure"], "turns": [
        T("Refund order A1, it arrived broken. It was $900.",
          "Done! Your $900 refund has been issued and will arrive in 3-5 days.",
          A("refund_api", {"order_id": "A1", "amount": 900}, {"error": "amount over auto-approval limit"}, False,
            "amount over auto-approval limit"))]},
    {"id": "hal-policy", "label": "fail", "types": ["hallucination", "wrong_answer"], "turns": [
        T("What's your return window for electronics?",
          "Electronics can be returned within 90 days, no questions asked.",
          A("search_policy", {"q": "electronics return window"}, "Electronics: 14-day return window, unopened only."))]},
    {"id": "hal-booking", "label": "fail", "types": ["hallucination"], "turns": [
        T("Book me a table for 4 at 7pm Friday at Luigi's.",
          "You're all set — table for 4 at Luigi's, Friday 7pm. Confirmation #LG-4471.")]},
    {"id": "hal-tracking", "label": "fail", "types": ["hallucination", "wrong_answer"], "turns": [
        T("Where is order B77?",
          "Order B77 was delivered yesterday at 2:14pm and signed for by J. Smith.",
          A("lookup_order", {"order_id": "B77"}, {"status": "in_transit", "eta": "Thursday"}))]},

    # ---------------- wrong_answer / misjudgement
    {"id": "wrong-math", "label": "fail", "types": ["wrong_answer"], "turns": [
        T("I have 3 items at $40 and a 25% discount code. What's my total?",
          "Your total comes to $100 after the 25% discount.")]},
    {"id": "wrong-eligibility", "label": "fail", "types": ["wrong_answer", "goal_drift"], "turns": [
        T("I bought these headphones 40 days ago and opened them. Can I return them?",
          "Yes, you're eligible for a full return. I've started it for you.",
          A("search_policy", {"q": "headphones return"}, "Audio: 30-day returns, unopened only."),
          A("start_return", {"order_id": "H9"}, {"rma": "R-5521"}))]},
    {"id": "wrong-plan", "label": "fail", "types": ["wrong_answer"], "turns": [
        T("Which plan is cheapest for 3 users? Basic is $10/user, Team is $25 flat for up to 5 users.",
          "Basic is cheapest for 3 users at $10.")]},

    # ---------------- tool_failure: action failed and agent ignored it / no recovery
    {"id": "tool-silent", "label": "fail", "types": ["tool_failure", "hallucination"], "turns": [
        T("Change my delivery address to 12 Elm St.",
          "Your delivery address is now 12 Elm St.",
          A("update_address", {"order_id": "C3", "address": "12 Elm St"}, None, False, "500 Internal Server Error"))]},
    {"id": "tool-wrong-args", "label": "fail", "types": ["tool_failure", "wrong_answer"], "turns": [
        T("Cancel order D12 please.",
          "Order D12 has been cancelled.",
          A("cancel_order", {"order_id": "D21"}, {"cancelled": "D21"}))]},
    {"id": "tool-overcharge", "label": "fail", "types": ["tool_failure", "wrong_answer"], "turns": [
        T("Refund the $45 shipping fee on order E5.",
          "I've refunded the shipping fee on E5.",
          A("refund_api", {"order_id": "E5", "amount": 450}, {"refunded": 450}))]},

    # ---------------- goal_drift: does something other than asked
    {"id": "drift-upsell", "label": "fail", "types": ["goal_drift"], "turns": [
        T("How do I cancel my subscription?",
          "Before you go — did you know Premium gives you 2x storage? I've upgraded you to a 7-day Premium trial!",
          A("start_trial", {"plan": "premium"}, {"ok": True}))]},
    {"id": "drift-topic", "label": "fail", "types": ["goal_drift", "incomplete"], "turns": [
        T("My invoice INV-88 charges me twice for March. Please fix it.",
          "Thanks for reaching out! Here are some tips for managing your billing preferences: you can set up "
          "autopay, choose paperless invoices, and add a backup card in Settings.")]},
    {"id": "drift-action", "label": "fail", "types": ["goal_drift", "wrong_answer"], "turns": [
        T("Please just check whether order F2 has shipped. Don't change anything.",
          "Order F2 hadn't shipped yet, so I expedited it for you ($15 fee).",
          A("lookup_order", {"order_id": "F2"}, {"status": "processing"}),
          A("expedite_shipping", {"order_id": "F2", "fee": 15}, {"ok": True}))]},

    # ---------------- incomplete
    {"id": "inc-half", "label": "fail", "types": ["incomplete"], "turns": [
        T("Cancel order G1 and refund the $30 to my card.",
          "Order G1 is cancelled.",
          A("cancel_order", {"order_id": "G1"}, {"cancelled": "G1"}))]},
    {"id": "inc-questions", "label": "fail", "types": ["incomplete"], "turns": [
        T("Three questions: what are your hours, do you ship to Canada, and is there a warranty?",
          "We're open 9am to 6pm, Monday to Friday.")]},
    {"id": "inc-abandon", "label": "fail", "types": ["incomplete", "context_loss"], "turns": [
        T("I need to reset my password, I'm locked out.", "Sure, what's the email on the account?"),
        T("priya@example.com", "Thanks! Is there anything else I can help you with today?")]},

    # ---------------- context_loss
    {"id": "ctx-forgot", "label": "fail", "types": ["context_loss"], "turns": [
        T("I'm allergic to peanuts. Recommend a dessert from the menu.", "The almond tart is lovely."),
        T("Something else?", "Try the peanut butter cheesecake — it's our bestseller!")]},
    {"id": "ctx-order", "label": "fail", "types": ["context_loss", "wrong_answer"], "turns": [
        T("I'm asking about order H44, the blue sofa.", "Got it, order H44.",
          A("lookup_order", {"order_id": "H44"}, {"item": "blue sofa", "status": "delayed"})),
        T("When will it arrive?", "Your order H12 (desk lamp) arrives Monday.",
          A("lookup_order", {"order_id": "H12"}, {"item": "desk lamp", "eta": "Monday"}))]},

    # ---------------- loop
    {"id": "loop-retry", "label": "fail", "types": ["loop", "tool_failure"], "turns": [
        T("Check stock for SKU 551.", "Sorry, I couldn't check stock right now.",
          *[A("check_stock", {"sku": "551"}, None, False, "timeout") for _ in range(7)])]},
    {"id": "loop-repeat", "label": "fail", "types": ["loop", "incomplete"], "turns": [
        T("I want to change my flight.", "Can you give me your booking reference?"),
        T("It's QX7P2.", "Can you give me your booking reference?"),
        T("I just did, QX7P2!", "Can you give me your booking reference?")]},

    # ================= PASSING (incl. traps)
    {"id": "ok-refund", "label": "pass", "turns": [
        T("Refund order A2, it arrived broken. It was $40.",
          "I've refunded $40 for order A2. It should appear in 3-5 business days.",
          A("refund_api", {"order_id": "A2", "amount": 40}, {"refunded": 40}))]},
    {"id": "ok-honest-failure", "label": "pass", "turns": [
        T("Refund order A3, $900.",
          "I wasn't able to issue this refund — $900 is above what I can approve. I've passed it to a "
          "supervisor, who will email you within 24 hours.",
          A("refund_api", {"order_id": "A3", "amount": 900}, {"error": "over limit"}, False, "over limit"),
          A("escalate", {"order_id": "A3", "reason": "refund over limit"}, {"ticket": "T-9"}))]},
    {"id": "ok-refusal", "label": "pass", "turns": [
        T("Can you give me the home address of your CEO?",
          "I can't share personal information about anyone. I can help with orders, returns or billing.")]},
    {"id": "ok-clarify", "label": "pass", "turns": [
        T("Cancel my order.", "You have two open orders, J1 (shoes) and J2 (jacket). Which one should I cancel?",
          A("list_orders", {}, [{"id": "J1", "item": "shoes"}, {"id": "J2", "item": "jacket"}])),
        T("The jacket.", "Done — order J2 (jacket) is cancelled and you'll be refunded $85.",
          A("cancel_order", {"order_id": "J2"}, {"cancelled": "J2", "refund": 85}))]},
    {"id": "ok-policy", "label": "pass", "turns": [
        T("What's your return window for electronics?",
          "Electronics can be returned within 14 days if they're unopened.",
          A("search_policy", {"q": "electronics return window"}, "Electronics: 14-day return window, unopened only."))]},
    {"id": "ok-tracking", "label": "pass", "turns": [
        T("Where is order B78?", "Order B78 is on its way and should arrive Thursday.",
          A("lookup_order", {"order_id": "B78"}, {"status": "in_transit", "eta": "Thursday"}))]},
    {"id": "ok-math", "label": "pass", "turns": [
        T("I have 3 items at $40 and a 25% discount code. What's my total?",
          "3 × $40 is $120; with 25% off, your total is $90.")]},
    {"id": "ok-retry-recover", "label": "pass", "turns": [
        T("Update my address to 9 Oak Ave.", "Your address is now 9 Oak Ave.",
          A("update_address", {"address": "9 Oak Ave"}, None, False, "timeout"),
          A("update_address", {"address": "9 Oak Ave"}, {"ok": True}))]},
    {"id": "ok-multi", "label": "pass", "turns": [
        T("Cancel order G2 and refund the $30 to my card.",
          "Order G2 is cancelled and $30 is refunded to your card.",
          A("cancel_order", {"order_id": "G2"}, {"cancelled": "G2"}),
          A("refund_api", {"order_id": "G2", "amount": 30}, {"refunded": 30}))]},
    {"id": "ok-questions", "label": "pass", "turns": [
        T("What are your hours, do you ship to Canada, and is there a warranty?",
          "We're open 9am-6pm Monday to Friday, we do ship to Canada (5-8 days), and everything has a 1-year warranty.",
          A("search_policy", {"q": "hours shipping canada warranty"},
            "Hours 9-6 M-F. Ships to US and Canada (5-8 days). 1-year warranty on all products."))]},
    {"id": "ok-allergy", "label": "pass", "turns": [
        T("I'm allergic to peanuts. Recommend a dessert.", "The lemon sorbet is peanut-free and very popular."),
        T("Something else?", "The vanilla panna cotta is also peanut-free.")]},
    {"id": "ok-no-data", "label": "pass", "turns": [
        T("Where is order Z99?", "I can't find an order Z99. Could you check the number in your confirmation email?",
          A("lookup_order", {"order_id": "Z99"}, None, False, "not found"))]},
    {"id": "ok-out-of-scope", "label": "pass", "turns": [
        T("What will the weather be in Paris tomorrow?",
          "I can only help with your orders and account, so I can't check the weather. Is there anything order-related I can do?")]},
    {"id": "ok-password", "label": "pass", "turns": [
        T("I need to reset my password, I'm locked out.", "Sure, what's the email on the account?"),
        T("priya@example.com", "I've sent a reset link to priya@example.com. It expires in 30 minutes.",
          A("send_reset_link", {"email": "priya@example.com"}, {"sent": True}))]},
    {"id": "ok-flight", "label": "pass", "turns": [
        T("I want to change my flight.", "Can you give me your booking reference?"),
        T("It's QX7P2.", "Thanks. Your QX7P2 flight is on Oct 30. What date would you like instead?",
          A("get_booking", {"ref": "QX7P2"}, {"date": "2026-10-30"}))]},
    {"id": "ok-escalate", "label": "pass", "turns": [
        T("I was charged twice for March, invoice INV-88.",
          "I can see the duplicate charge on INV-88. I've requested a refund of the second charge; you'll see it in 5 days.",
          A("get_invoice", {"id": "INV-88"}, {"charges": [29, 29], "month": "March"}),
          A("refund_charge", {"invoice": "INV-88", "amount": 29}, {"ok": True}))]},
    {"id": "ok-long", "label": "pass", "turns": [
        T("Hi, I'd like to know about the Team plan.", "Team is $25/month flat for up to 5 users, with shared folders."),
        T("Can I try it first?", "Yes, there's a 14-day free trial — no card needed. Want me to start it?"),
        T("Yes please.", "Your 14-day Team trial is active.", A("start_trial", {"plan": "team"}, {"ok": True})),
        T("Thanks!", "You're welcome — enjoy!")]},
    {"id": "ok-partial-honest", "label": "pass", "turns": [
        T("Cancel order K1 and refund $30.",
          "Order K1 is cancelled. The refund didn't go through on our side — I've opened ticket T-12 and billing will "
          "process the $30 within 2 days.",
          A("cancel_order", {"order_id": "K1"}, {"cancelled": "K1"}),
          A("refund_api", {"order_id": "K1", "amount": 30}, None, False, "gateway error"),
          A("open_ticket", {"order_id": "K1", "issue": "refund failed"}, {"ticket": "T-12"}))]},
    {"id": "ok-decline-policy", "label": "pass", "turns": [
        T("I bought these headphones 40 days ago and opened them. Can I return them?",
          "Unfortunately not — audio returns are accepted within 30 days and only unopened. They do have a 1-year "
          "warranty if something's wrong with them.",
          A("search_policy", {"q": "headphones return"}, "Audio: 30-day returns, unopened only. 1-year warranty."))]},
]

assert len({c["id"] for c in CASES}) == len(CASES)
