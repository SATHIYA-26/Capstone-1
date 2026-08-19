import uuid
import stripe
import json
from datetime import datetime, UTC
from typing import Dict
from fastapi import FastAPI, Header, HTTPException, Depends, status, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from src.database import get_db
from src.config import settings
from src.models import Tenant, Subscription, Plan, UsageEvent, ProcessedWebhook
from src.services import (
    get_existing_events,
    record_usage_events,
    check_quota,
    get_monthly_usage
)
from src.background import run_monthly_reconciliation

stripe.api_key = settings.STRIPE_API_KEY

app = FastAPI(
    title="Usage Metering & Billing Engine",
    version="1.0.0",
    description="A SaaS usage metering and Stripe billing backend engine."
)

# Pydantic schemas for request validation
class CheckoutRequest(BaseModel):
    success_url: str = "http://localhost:8000/success"
    cancel_url: str = "http://localhost:8000/cancel"

class TokenUsageSimulate(BaseModel):
    input: int = Field(default=0, ge=0)
    cached_input: int = Field(default=0, ge=0)
    output: int = Field(default=0, ge=0)
    reasoning: int = Field(default=0, ge=0)

class GenerateRequest(BaseModel):
    prompt: str
    simulate_tokens: TokenUsageSimulate


def calculate_cost(api_calls: int, input_tokens: int, cached_input_tokens: int, output_tokens: int, reasoning_tokens: int) -> int:
    """
    Calculate cost in micro-cents based on configured prices.
    """
    return (
        api_calls * settings.API_CALL_PRICE +
        input_tokens * settings.INPUT_TOKEN_PRICE +
        cached_input_tokens * settings.CACHED_INPUT_TOKEN_PRICE +
        output_tokens * settings.OUTPUT_TOKEN_PRICE +
        reasoning_tokens * settings.REASONING_TOKEN_PRICE
    )


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "service": "metering-billing-engine"
    }


@app.post("/generate", status_code=status.HTTP_200_OK)
def generate(
    payload: GenerateRequest,
    x_tenant_id: uuid.UUID = Header(None, alias="X-Tenant-ID"),
    idempotency_key: str = Header(None, alias="Idempotency-Key"),
    db: Session = Depends(get_db)
):
    # 1. Header Validation
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="Missing X-Tenant-ID header")
    if not idempotency_key:
        raise HTTPException(status_code=400, detail="Missing Idempotency-Key header")

    # 2. Check if Tenant exists
    tenant = db.query(Tenant).filter(Tenant.id == x_tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    # 3. Idempotency Check (Check if already processed)
    existing_events = get_existing_events(db, x_tenant_id, idempotency_key)
    if existing_events:
        # Reconstruct response from previously recorded events
        api_calls = 0
        tokens = {"input": 0, "cached_input": 0, "output": 0, "reasoning": 0}
        
        for event in existing_events:
            if event.usage_type == "api_call":
                api_calls += event.quantity
            elif event.usage_type == "ai_token":
                if event.token_category in tokens:
                    tokens[event.token_category] += event.quantity

        cost_amount = calculate_cost(
            api_calls=api_calls,
            input_tokens=tokens["input"],
            cached_input_tokens=tokens["cached_input"],
            output_tokens=tokens["output"],
            reasoning_tokens=tokens["reasoning"]
        )

        return {
            "status": "success",
            "usage_recorded": {
                "api_calls": api_calls,
                "tokens": tokens
            },
            "cost": {
                "amount": cost_amount,
                "currency": "USD",
                "unit": "microcents"
            }
        }

    # 4. Quota Check
    requested_api_calls = 1
    requested_tokens = (
        payload.simulate_tokens.input +
        payload.simulate_tokens.cached_input +
        payload.simulate_tokens.output +
        payload.simulate_tokens.reasoning
    )

    allowed, reason, status_code = check_quota(
        db=db,
        tenant_id=x_tenant_id,
        requested_api_calls=requested_api_calls,
        requested_tokens=requested_tokens
    )

    if not allowed:
        db.rollback()
        raise HTTPException(status_code=status_code, detail=reason)

    # 5. Record Usage Events
    token_usage_dict = {
        "input": payload.simulate_tokens.input,
        "cached_input": payload.simulate_tokens.cached_input,
        "output": payload.simulate_tokens.output,
        "reasoning": payload.simulate_tokens.reasoning
    }

    record_usage_events(
        db=db,
        tenant_id=x_tenant_id,
        idempotency_key=idempotency_key,
        api_calls=requested_api_calls,
        token_usage=token_usage_dict
    )

    # 6. Calculate Cost and Return Response
    cost_amount = calculate_cost(
        api_calls=requested_api_calls,
        input_tokens=payload.simulate_tokens.input,
        cached_input_tokens=payload.simulate_tokens.cached_input,
        output_tokens=payload.simulate_tokens.output,
        reasoning_tokens=payload.simulate_tokens.reasoning
    )

    return {
        "status": "success",
        "usage_recorded": {
            "api_calls": requested_api_calls,
            "tokens": token_usage_dict
        },
        "cost": {
            "amount": cost_amount,
            "currency": "USD",
            "unit": "microcents"
        }
    }


@app.post("/checkout", status_code=status.HTTP_200_OK)
def create_checkout_session(
    payload: CheckoutRequest,
    x_tenant_id: uuid.UUID = Header(None, alias="X-Tenant-ID"),
    db: Session = Depends(get_db)
):
    # 1. Header Validation
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="Missing X-Tenant-ID header")

    # 2. Check if Tenant exists
    tenant = db.query(Tenant).filter(Tenant.id == x_tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    # 3. Create Stripe Checkout Session (or return simulated session URL if using placeholder test keys)
    try:
        if settings.STRIPE_API_KEY.startswith("sk_test_placeholder"):
            session_id = f"cs_test_{uuid.uuid4()}"
            checkout_url = f"https://checkout.stripe.com/c/pay/{session_id}"
        else:
            session = stripe.checkout.Session.create(
                payment_method_types=["card"],
                mode="subscription",
                line_items=[{
                    "price": settings.STRIPE_PRO_PRICE_ID,
                    "quantity": 1,
                }],
                metadata={
                    "tenant_id": str(x_tenant_id)
                },
                success_url=payload.success_url,
                cancel_url=payload.cancel_url,
            )
            session_id = session.id
            checkout_url = session.url

        return {
            "status": "success",
            "session_id": session_id,
            "checkout_url": checkout_url
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Stripe Session creation error: {str(e)}")


@app.post("/webhooks/stripe", status_code=status.HTTP_200_OK)
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    event = None
    if settings.STRIPE_WEBHOOK_SECRET.startswith("whsec_placeholder") and not sig_header:
        try:
            event = json.loads(payload.decode("utf-8"))
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid payload")
    else:
        if not sig_header:
            raise HTTPException(status_code=400, detail="Missing Stripe-Signature header")
        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
            )
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid payload")
        except stripe.error.SignatureVerificationError:
            raise HTTPException(status_code=400, detail="Invalid signature")

    event_id = event.get("id") if isinstance(event, dict) else getattr(event, "id", None)
    event_type = event.get("type") if isinstance(event, dict) else getattr(event, "type", None)
    
    if isinstance(event, dict):
        event_data = event.get("data", {}).get("object", {})
    else:
        event_data = getattr(event, "data", {}).object if hasattr(event, "data") else {}

    # Deduplication check
    existing_webhook = db.query(ProcessedWebhook).filter(ProcessedWebhook.event_id == event_id).first()
    if existing_webhook:
        return {"status": "ignored", "reason": "duplicate event"}

    # Process events
    if event_type in ["checkout.session.completed", "customer.subscription.updated", "customer.subscription.created"]:
        if isinstance(event_data, dict):
            metadata = event_data.get("metadata", {})
            customer_id = event_data.get("customer")
            sub_id = event_data.get("subscription") or event_id
        else:
            metadata = getattr(event_data, "metadata", {}) or {}
            customer_id = getattr(event_data, "customer", None)
            sub_id = getattr(event_data, "subscription", None) or event_id

        tenant_id_str = metadata.get("tenant_id") if isinstance(metadata, dict) else getattr(metadata, "tenant_id", None)

        if tenant_id_str:
            try:
                t_id = uuid.UUID(tenant_id_str)
                pro_plan = db.query(Plan).filter(Plan.name == "pro").first()
                if pro_plan:
                    sub = db.query(Subscription).filter(Subscription.tenant_id == t_id).first()
                    if sub:
                        sub.plan_id = pro_plan.id
                        sub.status = "active"
                    else:
                        sub = Subscription(
                            id=uuid.uuid4(),
                            tenant_id=t_id,
                            plan_id=pro_plan.id,
                            stripe_customer_id=customer_id,
                            stripe_subscription_id=sub_id,
                            status="active"
                        )
                        db.add(sub)
            except ValueError:
                pass

    # Save event deduplication record
    processed = ProcessedWebhook(
        event_id=event_id,
        processed_at=datetime.now(UTC).replace(tzinfo=None)
    )
    db.add(processed)
    db.commit()

    return {"status": "success", "event_id": event_id}


@app.get("/usage", status_code=status.HTTP_200_OK)
def get_usage_summary(
    x_tenant_id: uuid.UUID = Header(None, alias="X-Tenant-ID"),
    db: Session = Depends(get_db)
):
    # 1. Header Validation
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="Missing X-Tenant-ID header")

    # 2. Verify Tenant existence
    tenant = db.query(Tenant).filter(Tenant.id == x_tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    # 3. Retrieve Subscription & Plan
    sub = db.query(Subscription).filter(
        Subscription.tenant_id == x_tenant_id,
        Subscription.status == "active"
    ).first()
    if not sub:
        raise HTTPException(status_code=402, detail="No active subscription found")

    plan = db.query(Plan).filter(Plan.id == sub.plan_id).first()
    if not plan:
        raise HTTPException(status_code=402, detail="Plan configuration not found")

    # 4. Fetch Monthly Usage
    usage = get_monthly_usage(db, x_tenant_id)

    # 5. Calculate Cost for all recorded events this month
    events = db.query(UsageEvent).filter(UsageEvent.tenant_id == x_tenant_id).all()
    api_calls_count = 0
    input_tokens = 0
    cached_input_tokens = 0
    output_tokens = 0
    reasoning_tokens = 0

    for event in events:
        if event.usage_type == "api_call":
            api_calls_count += event.quantity
        elif event.usage_type == "ai_token":
            if event.token_category == "input":
                input_tokens += event.quantity
            elif event.token_category == "cached_input":
                cached_input_tokens += event.quantity
            elif event.token_category == "output":
                output_tokens += event.quantity
            elif event.token_category == "reasoning":
                reasoning_tokens += event.quantity

    total_cost = calculate_cost(
        api_calls=api_calls_count,
        input_tokens=input_tokens,
        cached_input_tokens=cached_input_tokens,
        output_tokens=output_tokens,
        reasoning_tokens=reasoning_tokens
    )

    return {
        "tenant_id": str(x_tenant_id),
        "plan": plan.name,
        "usage": {
            "api_calls": {
                "used": usage["api_calls"],
                "limit": plan.api_limit
            },
            "ai_tokens": {
                "used": usage["ai_tokens"],
                "limit": plan.token_limit
            }
        },
        "cost": {
            "amount": total_cost,
            "currency": "USD",
            "unit": "microcents"
        }
    }


@app.post("/admin/reconcile", status_code=status.HTTP_200_OK)
def trigger_usage_reconciliation(db: Session = Depends(get_db)):
    """
    Background job endpoint for triggerable tenant usage reconciliation.
    """
    reconciliation_summary = run_monthly_reconciliation(db)
    return {
        "status": "success",
        "summary": reconciliation_summary
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.main:app", host=settings.HOST, port=settings.PORT, reload=True)
