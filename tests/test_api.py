import uuid
import pytest
from fastapi.testclient import TestClient
from src.main import app
from src.database import SessionLocal, engine, Base
from src.models import Tenant, Plan, Subscription, UsageEvent

client = TestClient(app)

@pytest.fixture(scope="function")
def setup_api_data():
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()

    # 1. Create a test plan with small limits (5 API, 500 tokens)
    plan = session.query(Plan).filter_by(name="api_test_plan").first()
    if not plan:
        plan = Plan(
            id=uuid.uuid4(),
            name="api_test_plan",
            api_limit=5,
            token_limit=500
        )
        session.add(plan)
        session.commit()

    # 2. Create test tenant
    tenant = Tenant(id=uuid.uuid4(), name="API Test Tenant")
    session.add(tenant)
    session.commit()

    # 3. Create Subscription
    sub = Subscription(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        plan_id=plan.id,
        stripe_customer_id="cus_api_test",
        stripe_subscription_id=f"sub_api_test_{uuid.uuid4()}",
        status="active"
    )
    session.add(sub)
    session.commit()

    yield tenant.id, plan

    # Cleanup
    session.query(UsageEvent).filter(UsageEvent.tenant_id == tenant.id).delete()
    session.query(Subscription).filter(Subscription.tenant_id == tenant.id).delete()
    session.query(Tenant).filter(Tenant.id == tenant.id).delete()
    session.commit()
    session.close()


def test_missing_headers():
    response = client.post("/generate", json={"prompt": "hello", "simulate_tokens": {}})
    assert response.status_code == 400
    assert "Missing X-Tenant-ID header" in response.json()["detail"]

    response = client.post(
        "/generate",
        headers={"X-Tenant-ID": str(uuid.uuid4())},
        json={"prompt": "hello", "simulate_tokens": {}}
    )
    assert response.status_code == 400
    assert "Missing Idempotency-Key header" in response.json()["detail"]


def test_generate_happy_path_and_idempotency(setup_api_data):
    tenant_id, plan = setup_api_data
    idempotency_key = f"api-key-{uuid.uuid4()}"
    headers = {
        "X-Tenant-ID": str(tenant_id),
        "Idempotency-Key": idempotency_key
    }
    payload = {
        "prompt": "Test prompt",
        "simulate_tokens": {
            "input": 100,
            "cached_input": 50,
            "output": 40,
            "reasoning": 10
        }
    }

    # First request
    response_1 = client.post("/generate", headers=headers, json=payload)
    assert response_1.status_code == 200
    data_1 = response_1.json()
    assert data_1["status"] == "success"
    assert data_1["usage_recorded"]["api_calls"] == 1
    assert data_1["usage_recorded"]["tokens"]["input"] == 100
    assert data_1["usage_recorded"]["tokens"]["cached_input"] == 50
    # Cost = 1*100000 + 100*15 + 50*5 + 40*60 + 10*60
    #      = 100000 + 1500 + 250 + 2400 + 600 = 104750
    assert data_1["cost"]["amount"] == 104750

    # Second request (retry)
    response_2 = client.post("/generate", headers=headers, json=payload)
    assert response_2.status_code == 200
    data_2 = response_2.json()
    assert data_2 == data_1


def test_generate_quota_rejection(setup_api_data):
    tenant_id, plan = setup_api_data
    headers = {
        "X-Tenant-ID": str(tenant_id),
        "Idempotency-Key": f"api-key-{uuid.uuid4()}"
    }

    # Request exceeding token limit (plan limit is 500)
    payload = {
        "prompt": "Test prompt",
        "simulate_tokens": {
            "input": 600,
            "cached_input": 0,
            "output": 0,
            "reasoning": 0
        }
    }

    response = client.post("/generate", headers=headers, json=payload)
    assert response.status_code == 429
    assert "AI token quota exceeded" in response.json()["detail"]


def test_get_usage_endpoint(setup_api_data):
    tenant_id, plan = setup_api_data
    idempotency_key = f"usage-test-key-{uuid.uuid4()}"
    headers = {
        "X-Tenant-ID": str(tenant_id),
        "Idempotency-Key": idempotency_key
    }
    payload = {
        "prompt": "Usage test prompt",
        "simulate_tokens": {
            "input": 100,
            "cached_input": 50,
            "output": 40,
            "reasoning": 10
        }
    }

    # 1. Record initial usage via /generate
    gen_response = client.post("/generate", headers=headers, json=payload)
    assert gen_response.status_code == 200

    # 2. Query /usage endpoint
    usage_response = client.get("/usage", headers={"X-Tenant-ID": str(tenant_id)})
    assert usage_response.status_code == 200

    data = usage_response.json()
    assert data["tenant_id"] == str(tenant_id)
    assert data["plan"] == "api_test_plan"
    assert data["usage"]["api_calls"]["used"] == 1
    assert data["usage"]["api_calls"]["limit"] == 5
    assert data["usage"]["ai_tokens"]["used"] == 200
    assert data["usage"]["ai_tokens"]["limit"] == 500
    assert data["cost"]["amount"] == 104750
    assert data["cost"]["unit"] == "microcents"


def test_health_check_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "metering-billing-engine"
    assert data["database"] == "connected"


def test_request_tracing_middleware():
    custom_req_id = f"custom-req-{uuid.uuid4()}"
    response = client.get("/health", headers={"X-Request-ID": custom_req_id})
    assert response.status_code == 200
    assert response.headers.get("X-Request-ID") == custom_req_id
    assert "X-Process-Time-Ms" in response.headers


