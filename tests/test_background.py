import uuid
import pytest
from fastapi.testclient import TestClient
from src.main import app
from src.database import SessionLocal, engine, Base
from src.models import Tenant, Plan, Subscription, UsageEvent

client = TestClient(app)

@pytest.fixture(scope="function")
def setup_background_data():
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()

    free_plan = session.query(Plan).filter_by(name="free").first()
    if not free_plan:
        free_plan = Plan(id=uuid.uuid4(), name="free", api_limit=1, token_limit=10)
        session.add(free_plan)
        session.commit()

    tenant = Tenant(id=uuid.uuid4(), name="Background Test Tenant")
    session.add(tenant)
    session.commit()

    sub = Subscription(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        plan_id=free_plan.id,
        stripe_customer_id="cus_bg_test",
        stripe_subscription_id=f"sub_bg_{uuid.uuid4()}",
        status="active"
    )
    session.add(sub)
    session.commit()

    yield tenant.id, free_plan

    session.query(UsageEvent).filter(UsageEvent.tenant_id == tenant.id).delete()
    session.query(Subscription).filter(Subscription.tenant_id == tenant.id).delete()
    session.query(Tenant).filter(Tenant.id == tenant.id).delete()
    session.commit()
    session.close()


def test_background_reconciliation_trigger(setup_background_data):
    tenant_id, plan = setup_background_data

    # Trigger reconciliation endpoint
    response = client.post("/admin/reconcile")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "tenants_inspected" in data["summary"]
    assert "over_quota_tenants" in data["summary"]
