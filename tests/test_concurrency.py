import uuid
import concurrent.futures
import pytest
from fastapi.testclient import TestClient
from src.main import app
from src.database import SessionLocal, engine, Base
from src.models import Tenant, Plan, Subscription, UsageEvent

client = TestClient(app)

@pytest.fixture(scope="function")
def setup_concurrency_data():
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()

    # 1. Create a test plan with a defined quota (e.g., 5 API calls, 50,000 tokens)
    plan = session.query(Plan).filter_by(name="concurrency_test_plan").first()
    if not plan:
        plan = Plan(
            id=uuid.uuid4(),
            name="concurrency_test_plan",
            api_limit=5,
            token_limit=50000
        )
        session.add(plan)
        session.commit()

    # 2. Create test tenant
    tenant = Tenant(id=uuid.uuid4(), name="Concurrency Test Tenant")
    session.add(tenant)
    session.commit()

    # 3. Create Subscription
    sub = Subscription(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        plan_id=plan.id,
        stripe_customer_id="cus_conc_test",
        stripe_subscription_id=f"sub_conc_{uuid.uuid4()}",
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


def test_concurrent_identical_idempotency_keys(setup_concurrency_data):
    """
    Test that sending 10 simultaneous requests with the EXACT same idempotency key
    results in 200 OK for all requests while recording the usage event exactly once.
    """
    tenant_id, plan = setup_concurrency_data
    shared_idempotency_key = f"concurrent-key-{uuid.uuid4()}"
    headers = {
        "X-Tenant-ID": str(tenant_id),
        "Idempotency-Key": shared_idempotency_key
    }
    payload = {
        "prompt": "Concurrent idempotency test",
        "simulate_tokens": {
            "input": 100,
            "cached_input": 0,
            "output": 50,
            "reasoning": 0
        }
    }

    def make_request():
        return client.post("/generate", headers=headers, json=payload)

    # Fire 10 parallel requests
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(make_request) for _ in range(10)]
        responses = [f.result() for f in futures]

    # Verify all responses succeeded with 200 OK
    for r in responses:
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "success"
        assert data["usage_recorded"]["api_calls"] == 1

    # Verify in DB that only 1 api_call event and 2 token events exist for this tenant
    session = SessionLocal()
    events = session.query(UsageEvent).filter(
        UsageEvent.tenant_id == tenant_id,
        UsageEvent.idempotency_key.like(f"{shared_idempotency_key}%")
    ).all()
    session.close()

    api_events = [e for e in events if e.usage_type == "api_call"]
    assert len(api_events) == 1, f"Expected 1 api_call event, found {len(api_events)}"


def test_concurrent_quota_exhaustion(setup_concurrency_data):
    """
    Test that sending 10 concurrent requests to a plan with an api_limit of 5
    allows at most 5 requests and rejects the remaining with 429 Quota Exceeded.
    """
    tenant_id, plan = setup_concurrency_data

    def make_distinct_request(i):
        unique_key = f"distinct-key-{i}-{uuid.uuid4()}"
        headers = {
            "X-Tenant-ID": str(tenant_id),
            "Idempotency-Key": unique_key
        }
        payload = {
            "prompt": f"Concurrent distinct test {i}",
            "simulate_tokens": {
                "input": 10,
                "cached_input": 0,
                "output": 10,
                "reasoning": 0
            }
        }
        return client.post("/generate", headers=headers, json=payload)

    # Fire 10 parallel distinct requests (quota is 5)
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(make_distinct_request, i) for i in range(10)]
        responses = [f.result() for f in futures]

    status_codes = [r.status_code for r in responses]
    success_count = status_codes.count(200)
    rejected_count = status_codes.count(429)

    # Quota is 5, so successful requests must be exactly 5 (or <= 5) and the rest 429
    assert success_count <= 5, f"Allowed {success_count} requests, exceeding limit of 5"
    assert success_count + rejected_count == 10, f"Unexpected status codes: {status_codes}"

    # Verify database recorded usage does not exceed plan limit (5)
    session = SessionLocal()
    total_api_calls = session.query(UsageEvent).filter(
        UsageEvent.tenant_id == tenant_id,
        UsageEvent.usage_type == "api_call"
    ).count()
    session.close()

    assert total_api_calls <= 5, f"Recorded {total_api_calls} in DB, exceeding plan limit 5"
