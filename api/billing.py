"""
api/billing.py — organizations, users, API keys, Stripe billing.

Admin endpoints (require master KALYTERA_API_KEY):
  POST /admin/orgs                     — create org + first admin user + first API key
  GET  /admin/orgs                     — list all orgs with usage
  POST /admin/orgs/{org_id}/keys       — generate additional API key for an org
  POST /admin/orgs/{org_id}/users      — add a user to an org
  DELETE /admin/keys/{key_id}          — revoke an API key

Customer endpoints (require org's API key):
  GET  /billing/usage                  — current month usage + tier info
  POST /billing/checkout               — create Stripe Checkout session to upgrade

Stripe webhook (no auth — verified by signature):
  POST /billing/webhook
"""
import hashlib
import logging
import os
import secrets
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.database import get_db
from db.models import Organization
from db.queries import (
    create_api_key,
    create_organization,
    create_user,
    downgrade_org,
    get_apikey_by_hash,
    get_current_usage,
    get_org_by_id,
    get_user_by_email,
    list_keys_for_org,
    list_organizations,
    list_users_for_org,
    revoke_api_key,
    update_org_stripe,
)

logger = logging.getLogger("kalytera.billing")

# ---------------------------------------------------------------------------
# Tier config
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# POST /signup — public self-service (no auth required)
# ---------------------------------------------------------------------------

TIERS: dict[str, dict] = {
    "free":    {"sessions": 10_000,  "price_usd": 0,   "stripe_price_id": ""},
    "starter": {"sessions": 50_000,  "price_usd": 49,  "stripe_price_id": os.getenv("STRIPE_STARTER_PRICE_ID", "")},
    "growth":  {"sessions": 200_000, "price_usd": 149, "stripe_price_id": os.getenv("STRIPE_GROWTH_PRICE_ID", "")},
    "scale":   {"sessions": None,    "price_usd": None, "stripe_price_id": ""},
}

router = APIRouter(tags=["billing"])


class SignupRequest(BaseModel):
    name: str         # person or company name — becomes the org name
    email: str
    plan: str = "free"            # free | starter | growth
    success_url: Optional[str] = None   # where Stripe redirects after payment
    cancel_url: Optional[str] = None


@router.post("/signup")
def signup(req: SignupRequest, db: Session = Depends(get_db)):
    """
    Public self-service signup. No auth required.
    Free plan  → creates org + returns API key immediately.
    Paid plan  → creates org + returns Stripe checkout URL.
                 Org upgrades to paid tier after Stripe webhook fires.
    """
    existing = get_user_by_email(req.email, db)
    if existing:
        raise HTTPException(status_code=409, detail="This email is already registered. Contact support if you need a new key.")

    org = create_organization(name=req.name, db=db)
    user = create_user(email=req.email, org_id=org.id, role="admin", db=db)
    raw_key, key_row = _make_api_key(org_id=org.id, name="production", created_by=user.id, db=db)

    logger.info("Signup: org=%s email=%s plan=%s", org.id, req.email, req.plan)

    base_response = {
        "org_id": org.id,
        "api_key": raw_key,           # shown ONCE — must copy now
        "api_key_prefix": key_row.key_prefix,
        "tier": org.tier,
        "sessions_per_month": TIERS["free"]["sessions"],
    }

    if req.plan == "free":
        return {**base_response, "status": "active"}

    # Paid plan — pre-generate the key (works at free tier immediately),
    # then redirect to Stripe to upgrade the tier.
    stripe = _stripe()
    plan_cfg = TIERS.get(req.plan)
    if not plan_cfg or not plan_cfg.get("stripe_price_id"):
        # Stripe not configured yet — return key at free tier, note upgrade pending
        return {**base_response, "status": "active", "note": f"Stripe not configured for {req.plan} — you're on free tier for now."}

    try:
        checkout = stripe.checkout.Session.create(
            mode="subscription",
            payment_method_types=["card"],
            line_items=[{"price": plan_cfg["stripe_price_id"], "quantity": 1}],
            client_reference_id=org.id,
            customer_email=req.email,
            success_url=req.success_url or "https://kalytera.dev/welcome",
            cancel_url=req.cancel_url or "https://kalytera.dev/pricing",
        )
    except Exception as exc:
        logger.error("Stripe checkout error: %s", exc)
        raise HTTPException(status_code=502, detail=f"Stripe error: {exc}")

    return {
        **base_response,
        "status": "pending_payment",
        "checkout_url": checkout.url,
        "note": "Your API key works on the free tier now. Complete payment to unlock your paid plan.",
    }


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def _is_admin_key(authorization: Optional[str]) -> bool:
    master = os.getenv("KALYTERA_API_KEY", "")
    if not master:
        return True  # dev mode
    if not authorization or not authorization.startswith("Bearer "):
        return False
    return authorization[len("Bearer "):] == master


def _require_admin(authorization: Optional[str] = Header(default=None)) -> None:
    if not _is_admin_key(authorization):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Admin key required")


def _require_apikey(
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
) -> tuple:
    """Resolve a Bearer token to (ApiKey, Organization). Used by customer endpoints."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authorization: Bearer <key> required")
    token = authorization[len("Bearer "):]
    api_key = get_apikey_by_hash(hash_key(token), db)
    if not api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")
    org = get_org_by_id(api_key.org_id, db)
    if not org:
        raise HTTPException(status_code=401, detail="Organization not found or inactive")
    return api_key, org


def _stripe():
    try:
        import stripe as _s
    except ImportError:
        raise HTTPException(status_code=503, detail="Stripe not installed. Run: pip install stripe")
    _s.api_key = os.getenv("STRIPE_SECRET_KEY", "")
    if not _s.api_key:
        raise HTTPException(status_code=503, detail="STRIPE_SECRET_KEY not configured")
    return _s


def _make_api_key(org_id: str, name: str, created_by: Optional[str], db: Session) -> tuple[str, object]:
    """Generate a new API key, store its hash. Returns (raw_key, ApiKey row)."""
    raw = "kly_live_" + secrets.token_urlsafe(32)
    row = create_api_key(
        key_hash=hash_key(raw),
        key_prefix=raw[:16],
        name=name,
        org_id=org_id,
        created_by=created_by,
        db=db,
    )
    return raw, row


# ---------------------------------------------------------------------------
# POST /admin/orgs — create org + admin user + first API key
# ---------------------------------------------------------------------------

class CreateOrgRequest(BaseModel):
    name: str                        # "Acme Corp" or "Jane Smith"
    admin_email: str                 # first user — gets the API key
    key_name: str = "production"     # label for the first key


class CreateOrgResponse(BaseModel):
    org_id: str
    org_name: str
    user_id: str
    admin_email: str
    api_key: str          # shown ONCE — developer must store this
    api_key_prefix: str
    tier: str


@router.post("/admin/orgs", response_model=CreateOrgResponse)
def create_org(
    req: CreateOrgRequest,
    db: Session = Depends(get_db),
    authorization: Optional[str] = Header(default=None),
):
    _require_admin(authorization)

    org = create_organization(name=req.name, db=db)
    user = create_user(email=req.admin_email, org_id=org.id, role="admin", db=db)
    raw_key, key_row = _make_api_key(org_id=org.id, name=req.key_name, created_by=user.id, db=db)

    logger.info("Org created: id=%s name=%s admin=%s", org.id, org.name, req.admin_email)
    return CreateOrgResponse(
        org_id=org.id,
        org_name=org.name,
        user_id=user.id,
        admin_email=req.admin_email,
        api_key=raw_key,
        api_key_prefix=key_row.key_prefix,
        tier=org.tier,
    )


# ---------------------------------------------------------------------------
# GET /admin/orgs — list all orgs with usage summary
# ---------------------------------------------------------------------------

@router.get("/admin/orgs")
def list_orgs(
    db: Session = Depends(get_db),
    authorization: Optional[str] = Header(default=None),
):
    _require_admin(authorization)
    period = datetime.now(timezone.utc).strftime("%Y-%m")
    result = []
    for org in list_organizations(db):
        usage = get_current_usage(org.id, period, db)
        tier_cfg = TIERS.get(org.tier, TIERS["free"])
        users = list_users_for_org(org.id, db)
        keys = list_keys_for_org(org.id, db)
        result.append({
            "org_id": org.id,
            "name": org.name,
            "tier": org.tier,
            "users": [{"email": u.email, "role": u.role} for u in users],
            "api_keys": [{"id": k.id, "name": k.name, "prefix": k.key_prefix} for k in keys],
            "sessions_this_month": usage.session_count if usage else 0,
            "sessions_limit": tier_cfg["sessions"],
            "stripe_customer_id": org.stripe_customer_id,
            "created_at": org.created_at.isoformat(),
        })
    return result


# ---------------------------------------------------------------------------
# POST /admin/orgs/{org_id}/keys — add another API key to an existing org
# ---------------------------------------------------------------------------

class AddKeyRequest(BaseModel):
    name: str = "staging"   # label: "production", "staging", "ci", etc.


@router.post("/admin/orgs/{org_id}/keys")
def add_key(
    org_id: str,
    req: AddKeyRequest,
    db: Session = Depends(get_db),
    authorization: Optional[str] = Header(default=None),
):
    _require_admin(authorization)
    org = get_org_by_id(org_id, db)
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    raw_key, key_row = _make_api_key(org_id=org.id, name=req.name, created_by=None, db=db)
    logger.info("Key added to org %s name=%s", org_id, req.name)
    return {
        "org_id": org.id,
        "api_key": raw_key,          # shown ONCE
        "api_key_prefix": key_row.key_prefix,
        "key_name": req.name,
    }


# ---------------------------------------------------------------------------
# POST /admin/orgs/{org_id}/users — add a user to an existing org
# ---------------------------------------------------------------------------

class AddUserRequest(BaseModel):
    email: str
    role: str = "member"   # admin | member


@router.post("/admin/orgs/{org_id}/users")
def add_user(
    org_id: str,
    req: AddUserRequest,
    db: Session = Depends(get_db),
    authorization: Optional[str] = Header(default=None),
):
    _require_admin(authorization)
    org = get_org_by_id(org_id, db)
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    existing = get_user_by_email(req.email, db)
    if existing:
        raise HTTPException(status_code=409, detail=f"{req.email} already exists")
    user = create_user(email=req.email, org_id=org.id, role=req.role, db=db)
    return {"user_id": user.id, "email": user.email, "role": user.role, "org_id": org.id}


# ---------------------------------------------------------------------------
# DELETE /admin/keys/{key_id} — revoke an API key
# ---------------------------------------------------------------------------

@router.delete("/admin/keys/{key_id}")
def delete_key(
    key_id: str,
    db: Session = Depends(get_db),
    authorization: Optional[str] = Header(default=None),
):
    _require_admin(authorization)
    revoke_api_key(key_id, db)
    return {"status": "revoked", "key_id": key_id}


# ---------------------------------------------------------------------------
# GET /billing/usage — current month usage (customer API key auth)
# ---------------------------------------------------------------------------

@router.get("/billing/usage")
def get_usage(
    auth=Depends(_require_apikey),
    db: Session = Depends(get_db),
):
    _, org = auth
    period = datetime.now(timezone.utc).strftime("%Y-%m")
    usage = get_current_usage(org.id, period, db)
    sessions_used = usage.session_count if usage else 0
    tier_cfg = TIERS.get(org.tier, TIERS["free"])
    limit = tier_cfg["sessions"]
    keys = list_keys_for_org(org.id, db)
    return {
        "org_name": org.name,
        "tier": org.tier,
        "period": period,
        "sessions_used": sessions_used,
        "sessions_limit": limit,
        "sessions_remaining": max(0, limit - sessions_used) if limit else None,
        "pct_used": round(sessions_used / limit * 100, 1) if limit else None,
        "api_keys_count": len(keys),
        "upgrade_url": "/billing/checkout" if org.tier == "free" and sessions_used >= limit * 0.8 else None,
        "plans": {
            t: {"sessions_per_month": cfg["sessions"], "price_usd": cfg["price_usd"]}
            for t, cfg in TIERS.items() if t != "scale"
        },
    }


# ---------------------------------------------------------------------------
# POST /billing/checkout — Stripe Checkout to upgrade
# ---------------------------------------------------------------------------

class CheckoutRequest(BaseModel):
    plan: str          # "starter" | "growth"
    success_url: str
    cancel_url: str


@router.post("/billing/checkout")
def create_checkout(req: CheckoutRequest, auth=Depends(_require_apikey)):
    _, org = auth
    stripe = _stripe()
    plan = TIERS.get(req.plan)
    if not plan or not plan.get("stripe_price_id"):
        raise HTTPException(status_code=400, detail=f"Unknown or unconfigured plan: {req.plan}")
    params: dict = {
        "mode": "subscription",
        "payment_method_types": ["card"],
        "line_items": [{"price": plan["stripe_price_id"], "quantity": 1}],
        "client_reference_id": org.id,
        "success_url": req.success_url,
        "cancel_url": req.cancel_url,
    }
    if org.stripe_customer_id:
        params["customer"] = org.stripe_customer_id
    session = stripe.checkout.Session.create(**params)
    return {"checkout_url": session.url}


# ---------------------------------------------------------------------------
# POST /billing/webhook — Stripe events
# ---------------------------------------------------------------------------

@router.post("/billing/webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    stripe = _stripe()
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    secret = os.getenv("STRIPE_WEBHOOK_SECRET", "")
    try:
        event = stripe.Webhook.construct_event(payload, sig, secret)
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid Stripe signature")

    event_type = event["type"]
    logger.info("Stripe event: %s", event_type)

    if event_type == "checkout.session.completed":
        obj = event["data"]["object"]
        org_id = obj.get("client_reference_id")
        customer_id = obj.get("customer")
        subscription_id = obj.get("subscription")
        tier = _tier_from_subscription(stripe, subscription_id)
        if org_id:
            update_org_stripe(org_id, customer_id, subscription_id, tier, db)
            logger.info("Org %s upgraded to %s", org_id, tier)

    elif event_type in ("customer.subscription.deleted", "customer.subscription.paused"):
        subscription_id = event["data"]["object"]["id"]
        downgrade_org(subscription_id, db)
        logger.info("Subscription %s ended — org downgraded to free", subscription_id)

    return {"status": "ok"}


def _tier_from_subscription(stripe, subscription_id: str) -> str:
    if not subscription_id:
        return "free"
    try:
        sub = stripe.Subscription.retrieve(subscription_id)
        price_id = sub["items"]["data"][0]["price"]["id"]
        for tier, cfg in TIERS.items():
            if cfg.get("stripe_price_id") == price_id:
                return tier
    except Exception as exc:
        logger.error("Could not resolve tier from subscription %s: %s", subscription_id, exc)
    return "starter"
