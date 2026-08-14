import uuid
from typing import Dict
from fastapi import FastAPI, Header, HTTPException, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from src.database import get_db
from src.config import settings
from src.models import Tenant, Subscription, Plan, UsageEvent
from src.services import (
    get_existing_events,
    record_usage_events,
    check_quota,
    get_monthly_usage
)

app = FastAPI(
    title="Usage Metering & Billing Engine",
    version="1.0.0",
    description="A SaaS usage metering and Stripe billing backend engine."
)

# Pydantic schemas for request validation
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.main:app", host=settings.HOST, port=settings.PORT, reload=True)
