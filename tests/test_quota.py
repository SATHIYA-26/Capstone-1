import uuid
import pytest
from sqlalchemy.orm import Session
from src.database import SessionLocal, engine, Base
from src.services import check_quota, record_usage_events
from src.models import Tenant, Plan, Subscription, UsageEvent

@pytest.fixture(scope="function")
def db_session():
    # Setup test tables
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    
    # 1. Create a specific test plan (Limit: 10 API calls, 1000 tokens)
    test_plan = session.query(Plan).filter_by(name="quota_test_plan").first()
    if not test_plan:
        test_plan = Plan(
            id=uuid.uuid4(),
            name="quota_test_plan",
            api_limit=10,
            token_limit=1000
        )
        session.add(test_plan)
        session.commit()
    
    # 2. Create test tenant
    tenant = Tenant(id=uuid.uuid4(), name="Quota Test Tenant")
    session.add(tenant)
    session.commit()
    
    # 3. Create Subscription to the plan
    sub = Subscription(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        plan_id=test_plan.id,
        stripe_customer_id="cus_quota_test",
        stripe_subscription_id=f"sub_quota_test_{uuid.uuid4()}",
        status="active"
    )
    session.add(sub)
    session.commit()
    
    yield session, tenant.id, test_plan
    
    # Cleanup
    session.query(UsageEvent).filter(UsageEvent.tenant_id == tenant.id).delete()
    session.query(Subscription).filter(Subscription.tenant_id == tenant.id).delete()
    session.query(Tenant).filter(Tenant.id == tenant.id).delete()
    session.commit()
    session.close()

def test_quota_limits(db_session):
    session, tenant_id, plan = db_session
    
    # Check initial quota: should be allowed
    allowed, reason, status = check_quota(session, tenant_id, requested_api_calls=5, requested_tokens=500)
    assert allowed is True
    assert status == 200
    
    # Record some usage (5 API calls, 500 tokens)
    record_usage_events(
        db=session,
        tenant_id=tenant_id,
        idempotency_key="key-quota-1",
        api_calls=5,
        token_usage={"input": 300, "output": 200}
    )
    
    # Request exactly up to the limit (Remaining: 5 API calls, 500 tokens) -> Should be allowed
    allowed, reason, status = check_quota(session, tenant_id, requested_api_calls=5, requested_tokens=500)
    assert allowed is True
    
    # Request one over the limit (Requested: 6 API calls) -> Should be blocked (429)
    allowed, reason, status = check_quota(session, tenant_id, requested_api_calls=6, requested_tokens=100)
    assert allowed is False
    assert status == 429
    assert "API call quota exceeded" in reason

    # Request one over the limit (Requested: 501 tokens) -> Should be blocked (429)
    allowed, reason, status = check_quota(session, tenant_id, requested_api_calls=1, requested_tokens=501)
    assert allowed is False
    assert status == 429
    assert "AI token quota exceeded" in reason

def test_no_subscription_returns_402(db_session):
    session, tenant_id, plan = db_session
    
    # Create a tenant with no subscription
    nosub_tenant = Tenant(id=uuid.uuid4(), name="No Sub Tenant")
    session.add(nosub_tenant)
    session.commit()
    
    try:
        allowed, reason, status = check_quota(session, nosub_tenant.id, requested_api_calls=1, requested_tokens=10)
        assert allowed is False
        assert status == 402
        assert "No active subscription" in reason
    finally:
        session.query(Tenant).filter(Tenant.id == nosub_tenant.id).delete()
        session.commit()
