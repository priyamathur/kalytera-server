"""Payments: signup, checkout, webhooks (real signature check), plan changes, cancel, billing portal.

Stripe's API calls are replaced with fakes that return real StripeObjects; webhook
payloads are signed with the real algorithm and verified by the real stripe library.
"""
import hashlib
import hmac
import json
import time
from types import SimpleNamespace
from typing import Any, Dict, Generator, List

import pytest
import stripe
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api import billing
from api.database import get_db
from api.main import app
from db.models import Base, Organization

SECRET = "whsec_test_secret"
STARTER, GROWTH = "price_starter_test", "price_growth_test"


def _obj(data: Dict[str, Any]) -> Any:
    return stripe.StripeObject.construct_from(data, "sk_test_x")


@pytest.fixture()
def pay(monkeypatch: pytest.MonkeyPatch) -> Generator[SimpleNamespace, None, None]:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)

    def _db() -> Generator[Any, None, None]:
        db = Session()
        try:
            yield db
        finally:
            db.close()

    calls: Dict[str, List[Dict[str, Any]]] = {"checkout": [], "portal": []}
    subscriptions: Dict[str, str] = {}  # subscription id -> price id

    def checkout_create(**params: Any) -> Any:
        calls["checkout"].append(params)
        return _obj({"id": "cs_1", "url": "https://checkout.stripe.com/c/cs_1"})

    def portal_create(**params: Any) -> Any:
        calls["portal"].append(params)
        return _obj({"id": "bps_1", "url": "https://billing.stripe.com/p/session/bps_1"})

    def sub_retrieve(sub_id: str, *a: Any, **k: Any) -> Any:
        return _obj({"id": sub_id, "object": "subscription",
                     "items": {"object": "list", "data": [{"id": "si_1", "price": {"id": subscriptions[sub_id]}}]}})

    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", SECRET)
    monkeypatch.setitem(billing.TIERS["starter"], "stripe_price_id", STARTER)
    monkeypatch.setitem(billing.TIERS["growth"], "stripe_price_id", GROWTH)
    monkeypatch.setattr(stripe.checkout.Session, "create", staticmethod(checkout_create))
    monkeypatch.setattr(stripe.billing_portal.Session, "create", staticmethod(portal_create))
    monkeypatch.setattr(stripe.Subscription, "retrieve", staticmethod(sub_retrieve))
    app.dependency_overrides[get_db] = _db
    yield SimpleNamespace(client=TestClient(app), calls=calls, subs=subscriptions, session=Session)
    app.dependency_overrides.clear()


def _signup(pay: SimpleNamespace, plan: str = "free", email: str = "jane@acme.com") -> Dict[str, Any]:
    r = pay.client.post("/signup", json={"name": "Acme", "email": email, "plan": plan})
    assert r.status_code == 200, r.text
    return r.json()


def _webhook(pay: SimpleNamespace, event_type: str, obj: Dict[str, Any], secret: str = SECRET) -> Any:
    payload = json.dumps({"id": "evt_1", "object": "event", "type": event_type, "data": {"object": obj}})
    t = int(time.time())
    sig = hmac.new(secret.encode(), f"{t}.{payload}".encode(), hashlib.sha256).hexdigest()
    return pay.client.post("/billing/webhook", content=payload,
                           headers={"stripe-signature": f"t={t},v1={sig}", "content-type": "application/json"})


def _org(pay: SimpleNamespace, org_id: str) -> Organization:
    db = pay.session()
    try:
        return db.query(Organization).filter(Organization.id == org_id).one()
    finally:
        db.close()


def _usage(pay: SimpleNamespace, key: str) -> Dict[str, Any]:
    return pay.client.get("/billing/usage", headers={"Authorization": f"Bearer {key}"}).json()


def _paid(pay: SimpleNamespace, org_id: str, sub_id: str = "sub_1", price: str = STARTER) -> Any:
    pay.subs[sub_id] = price
    return _webhook(pay, "checkout.session.completed", {
        "id": "cs_1", "object": "checkout.session", "client_reference_id": org_id, "customer": "cus_1",
        "subscription": sub_id, "payment_status": "paid"})


def test_free_signup_gives_a_working_key_and_current_next_steps(pay: SimpleNamespace) -> None:
    body = _signup(pay)
    assert body["status"] == "active" and body["tier"] == "free"
    assert "kalytera.init()" in body["next_steps"] and "configure" not in body["next_steps"]
    assert _usage(pay, body["api_key"])["sessions_limit"] == 5_000


def test_paid_signup_sends_to_checkout_and_upgrades_only_after_payment(pay: SimpleNamespace) -> None:
    body = _signup(pay, "starter")
    assert body["status"] == "pending_payment" and body["checkout_url"].startswith("https://checkout.stripe.com/")
    params = pay.calls["checkout"][0]
    assert params["line_items"] == [{"price": STARTER, "quantity": 1}]
    assert params["client_reference_id"] == body["org_id"] and params["customer_email"] == "jane@acme.com"
    assert "payment_method_types" not in params  # Stripe picks the methods (dashboard setting)
    assert params["cancel_url"] == "https://kalytera.dev/#pricing"
    assert _usage(pay, body["api_key"])["tier"] == "free"  # key works, not upgraded yet
    assert _paid(pay, body["org_id"]).status_code == 200
    org = _org(pay, body["org_id"])
    assert (org.tier, org.stripe_customer_id, org.stripe_subscription_id) == ("starter", "cus_1", "sub_1")
    assert _usage(pay, body["api_key"])["sessions_limit"] == 25_000


def test_unpaid_checkout_waits_for_the_async_payment(pay: SimpleNamespace) -> None:
    body = _signup(pay, "growth")
    pay.subs["sub_9"] = GROWTH
    pending = {"id": "cs_9", "object": "checkout.session", "client_reference_id": body["org_id"],
               "customer": "cus_9", "subscription": "sub_9", "payment_status": "unpaid"}
    assert _webhook(pay, "checkout.session.completed", pending).status_code == 200
    assert _org(pay, body["org_id"]).tier == "free"
    assert _webhook(pay, "checkout.session.async_payment_succeeded",
                    {**pending, "payment_status": "paid"}).status_code == 200
    assert _org(pay, body["org_id"]).tier == "growth"


def test_free_user_upgrades_later_and_can_retry_an_abandoned_checkout(pay: SimpleNamespace) -> None:
    body = _signup(pay)
    h = {"Authorization": f"Bearer {body['api_key']}"}
    for _ in range(2):  # abandoned the first checkout, came back
        r = pay.client.post("/billing/checkout", json={"plan": "growth"}, headers=h)
        assert r.status_code == 200 and r.json()["checkout_url"].startswith("https://checkout.stripe.com/")
    assert pay.calls["checkout"][-1]["line_items"] == [{"price": GROWTH, "quantity": 1}]
    assert pay.calls["checkout"][-1]["success_url"] == "https://api.kalytera.dev/welcome"
    _paid(pay, body["org_id"], price=GROWTH)
    assert _usage(pay, body["api_key"])["tier"] == "growth"
    assert pay.client.post("/billing/checkout", json={"plan": "scale"}, headers=h).status_code == 400


def test_plan_change_cancel_and_failed_card(pay: SimpleNamespace) -> None:
    body = _signup(pay)
    _paid(pay, body["org_id"])
    pay.subs["sub_1"] = GROWTH  # changed plan in the billing portal
    _webhook(pay, "customer.subscription.updated", {"id": "sub_1", "object": "subscription", "status": "active"})
    assert _org(pay, body["org_id"]).tier == "growth"
    _webhook(pay, "customer.subscription.updated", {"id": "sub_1", "object": "subscription", "status": "past_due"})
    assert _org(pay, body["org_id"]).tier == "growth"  # Stripe is still retrying the card
    _webhook(pay, "customer.subscription.updated", {"id": "sub_1", "object": "subscription", "status": "unpaid"})
    assert _org(pay, body["org_id"]).tier == "free"


def test_cancelled_subscription_goes_back_to_free(pay: SimpleNamespace) -> None:
    body = _signup(pay)
    _paid(pay, body["org_id"])
    assert _webhook(pay, "customer.subscription.deleted", {"id": "sub_1", "object": "subscription"}).status_code == 200
    org = _org(pay, body["org_id"])
    assert (org.tier, org.stripe_subscription_id) == ("free", None)
    assert _usage(pay, body["api_key"])["sessions_limit"] == 5_000


def test_billing_portal_for_paying_customers_only(pay: SimpleNamespace) -> None:
    body = _signup(pay)
    h = {"Authorization": f"Bearer {body['api_key']}"}
    assert pay.client.post("/billing/portal", json={}, headers=h).status_code == 400  # nothing to manage yet
    _paid(pay, body["org_id"])
    r = pay.client.post("/billing/portal", json={}, headers=h)
    assert r.status_code == 200 and r.json()["portal_url"].startswith("https://billing.stripe.com/")
    assert pay.calls["portal"][0] == {"customer": "cus_1", "return_url": "https://app.kalytera.dev"}
    assert pay.client.post("/billing/portal", json={}).status_code == 401


def test_forged_or_unsigned_webhooks_are_rejected(pay: SimpleNamespace) -> None:
    body = _signup(pay)
    pay.subs["sub_x"] = GROWTH
    forged = _webhook(pay, "checkout.session.completed", {
        "id": "cs_x", "object": "checkout.session", "client_reference_id": body["org_id"], "customer": "cus_x",
        "subscription": "sub_x", "payment_status": "paid"}, secret="whsec_attacker")
    assert forged.status_code == 400
    unsigned = pay.client.post("/billing/webhook", content="{}", headers={"content-type": "application/json"})
    assert unsigned.status_code == 400
    assert _org(pay, body["org_id"]).tier == "free"


def test_same_email_cannot_sign_up_twice(pay: SimpleNamespace) -> None:
    _signup(pay, "starter")
    r = pay.client.post("/signup", json={"name": "Acme", "email": "jane@acme.com", "plan": "starter"})
    assert r.status_code == 409  # they resume payment from the dashboard's Upgrade instead
