import uuid
import pytest
from sqlalchemy.orm import Session
from src.database import SessionLocal, engine, Base
from src.services import record_usage_events, get_existing_events
from src.models import Tenant, Plan, Subscription, UsageEvent

@pytest.fixture(scope="module")
def db_session():
    # Bind to the database for testing
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    
    # Ensure our seed demo tenant is present
    tenant_id = uuid.UUID("11111111-1111-1111-1111-111111111111")
    tenant = session.query(Tenant).filter_by(id=tenant_id).first()
    if not tenant:
        tenant = Tenant(id=tenant_id, name="Test Tenant")
        session.add(tenant)
        session.commit()
        
    yield session
    
    # Cleanup test usage events
    session.query(UsageEvent).filter(UsageEvent.tenant_id == tenant_id).delete()
    session.commit()
    session.close()

def test_idempotency_prevents_duplicates(db_session: Session):
    tenant_id = uuid.UUID("11111111-1111-1111-1111-111111111111")
    idempotency_key = f"test-key-{uuid.uuid4()}"
    
    # First request
    events_1 = record_usage_events(
        db=db_session,
        tenant_id=tenant_id,
        idempotency_key=idempotency_key,
        api_calls=1,
        token_usage={"input": 1000, "output": 500}
    )
    
    assert len(events_1) == 3  # 1 API call + 2 token categories
    
    # Count usage events in DB for this key
    db_events_1 = get_existing_events(db_session, tenant_id, idempotency_key)
    assert len(db_events_1) == 3

    # Second request (retry with same key)
    events_2 = record_usage_events(
        db=db_session,
        tenant_id=tenant_id,
        idempotency_key=idempotency_key,
        api_calls=1,
        token_usage={"input": 1000, "output": 500}
    )
    
    # Should return the exact same event IDs and NOT create new rows
    assert len(events_2) == 3
    assert {e.id for e in events_1} == {e.id for e in events_2}
    
    # Count usage events in DB again to ensure no new rows were added
    db_events_2 = get_existing_events(db_session, tenant_id, idempotency_key)
    assert len(db_events_2) == 3
