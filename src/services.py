import uuid
from datetime import datetime
from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from src.models import UsageEvent

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
                timestamp=datetime.utcnow()
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
                    timestamp=datetime.utcnow()
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
