import uuid
import pytest
from fastapi.testclient import TestClient
from src.main import app
from src.database import SessionLocal, engine, Base
from src.models import Tenant, Plan, Subscription, ProcessedWebhook

client = TestClient(app)

@pytest.fixture(scope="function")
def setup_stripe_data():
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()

    # 1. Create Free and Pro plans
    free_plan = session.query(Plan).filter_by(name="free").first()
    if not free_plan:
        free_plan = Plan(id=uuid.uuid4(), name="free", api_limit=1000, token_limit=100000)
        session.add(free_plan)
        session.commit()

    pro_plan = session.query(Plan).filter_by(name="pro").first()
    if not pro_plan:
        pro_plan = Plan(id=uuid.uuid4(), name="pro", api_limit=100000, token_limit=10000000)
        session.add(pro_plan)
        session.commit()

    # 2. Create test tenant with Free subscription
    tenant = Tenant(id=uuid.uuid4(), name="Stripe Test Tenant")
    session.add(tenant)
    session.commit()

    sub = Subscription(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        plan_id=free_plan.id,
        stripe_customer_id="cus_stripe_test",
        stripe_subscription_id=f"sub_stripe_test_{uuid.uuid4()}",
        status="active"
    )
    session.add(sub)
    session.commit()

    yield tenant.id, free_plan, pro_plan

    # Cleanup
    session.query(Subscription).filter(Subscription.tenant_id == tenant.id).delete()
    session.query(Tenant).filter(Tenant.id == tenant.id).delete()
    session.query(ProcessedWebhook).delete()
    session.commit()
    session.close()


def test_checkout_session(setup_stripe_data):
    tenant_id, free_plan, pro_plan = setup_stripe_data
    headers = {"X-Tenant-ID": str(tenant_id)}

    response = client.post("/checkout", headers=headers, json={})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "session_id" in data
    assert "checkout_url" in data


def test_webhook_upgrade_and_deduplication(setup_stripe_data):
    tenant_id, free_plan, pro_plan = setup_stripe_data
    event_id = f"evt_test_{uuid.uuid4()}"

    webhook_payload = {
        "id": event_id,
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "customer": "cus_stripe_test",
                "subscription": f"sub_{uuid.uuid4()}",
                "metadata": {
                    "tenant_id": str(tenant_id)
                }
            }
        }
    }

    # First webhook submission (Process)
    response_1 = client.post("/webhooks/stripe", json=webhook_payload)
    assert response_1.status_code == 200
    assert response_1.json()["status"] == "success"

    # Verify tenant subscription upgraded to Pro
    session = SessionLocal()
    updated_sub = session.query(Subscription).filter(Subscription.tenant_id == tenant_id).first()
    assert updated_sub.plan_id == pro_plan.id
    session.close()

    # Second webhook submission (Duplicate -> Ignored)
    response_2 = client.post("/webhooks/stripe", json=webhook_payload)
    assert response_2.status_code == 200
    assert response_2.json()["status"] == "ignored"
    assert response_2.json()["reason"] == "duplicate event"
