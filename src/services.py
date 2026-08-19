import uuid
from datetime import datetime, UTC
from typing import List, Optional, Dict, Any, Tuple
from sqlalchemy import func
from sqlalchemy.orm import Session
from src.models import UsageEvent, Subscription, Plan

def get_existing_events(db: Session, tenant_id: uuid.UUID, idempotency_key: str) -> List[UsageEvent]:
    """
    Retrieve any existing usage events recorded under the given idempotency key
    for a specific tenant. We search for events starting with the base key.
    """
    return db.query(UsageEvent).filter(
        UsageEvent.tenant_id == tenant_id,
        UsageEvent.idempotency_key.like(f"{idempotency_key}%")
    ).all()

def record_usage_events(
    db: Session,
    tenant_id: uuid.UUID,
    idempotency_key: str,
    api_calls: int,
    token_usage: Dict[str, int]
) -> List[UsageEvent]:
    """
    Records usage events for a tenant. If events already exist for the idempotency key,
    returns the existing events instead of creating new ones.
    """
    # Check if events already exist (idempotency check)
    existing = get_existing_events(db, tenant_id, idempotency_key)
    if existing:
        return existing

    events_to_create = []

    # Record API call usage if present
    if api_calls > 0:
        events_to_create.append(
            UsageEvent(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                usage_type="api_call",
                quantity=api_calls,
                token_category=None,
                idempotency_key=f"{idempotency_key}:api_call",
                timestamp=datetime.now(UTC).replace(tzinfo=None)
            )
        )

    # Record AI Token usages
    for category, qty in token_usage.items():
        if qty > 0:
            events_to_create.append(
                UsageEvent(
                    id=uuid.uuid4(),
                    tenant_id=tenant_id,
                    usage_type="ai_token",
                    quantity=qty,
                    token_category=category,
                    idempotency_key=f"{idempotency_key}:ai_token:{category}",
                    timestamp=datetime.now(UTC).replace(tzinfo=None)
                )
            )

    try:
        for event in events_to_create:
            db.add(event)
        db.commit()
        return events_to_create
    except Exception as e:
        db.rollback()
        # In case of concurrent request race conditions, try fetching again
        existing = get_existing_events(db, tenant_id, idempotency_key)
        if existing:
            return existing
        raise e

def get_monthly_usage(db: Session, tenant_id: uuid.UUID) -> Dict[str, int]:
    """
    Sum the quantities of all usage events for a tenant in the current calendar month.
    Returns: {"api_calls": int, "ai_tokens": int}
    """
    now = datetime.now(UTC).replace(tzinfo=None)
    start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # Aggregate API Calls
    api_calls_sum = db.query(func.sum(UsageEvent.quantity)).filter(
        UsageEvent.tenant_id == tenant_id,
        UsageEvent.usage_type == "api_call",
        UsageEvent.timestamp >= start_of_month
    ).scalar() or 0

    # Aggregate Tokens
    tokens_sum = db.query(func.sum(UsageEvent.quantity)).filter(
        UsageEvent.tenant_id == tenant_id,
        UsageEvent.usage_type == "ai_token",
        UsageEvent.timestamp >= start_of_month
    ).scalar() or 0

    return {
        "api_calls": int(api_calls_sum),
        "ai_tokens": int(tokens_sum)
    }

def check_quota(
    db: Session,
    tenant_id: uuid.UUID,
    requested_api_calls: int,
    requested_tokens: int,
    lock_for_update: bool = True
) -> Tuple[bool, str, int]:
    """
    Checks if recording the requested usage would exceed the tenant's current plan limits.
    Uses pessimistic row locking (FOR UPDATE) to prevent race conditions during concurrent requests.
    Returns: (is_allowed, error_reason_if_any, recommended_http_status_code)
    """
    # 1. Fetch the tenant's active subscription and plan (with row lock if enabled)
    query = db.query(Subscription).filter(
        Subscription.tenant_id == tenant_id,
        Subscription.status == "active"
    )
    if lock_for_update:
        query = query.with_for_update()

    sub = query.first()

    if not sub:
        return False, "No active subscription found. Upgrade or payment is required.", 402

    plan = db.query(Plan).filter(Plan.id == sub.plan_id).first()
    if not plan:
        return False, "Plan configuration not found for tenant subscription.", 402

    # 2. Get current calendar month usage
    current_usage = get_monthly_usage(db, tenant_id)

    # 3. Check API calls boundary: current + requested > plan_limit
    if current_usage["api_calls"] + requested_api_calls > plan.api_limit:
        return False, f"API call quota exceeded. Limit: {plan.api_limit}, Current: {current_usage['api_calls']}, Requested: {requested_api_calls}", 429

    # 4. Check AI tokens boundary: current + requested > plan_limit
    if current_usage["ai_tokens"] + requested_tokens > plan.token_limit:
        return False, f"AI token quota exceeded. Limit: {plan.token_limit}, Current: {current_usage['ai_tokens']}, Requested: {requested_tokens}", 429

    return True, "", 200
