# Usage Metering & Billing Engine

A production-grade SaaS Usage Metering and Stripe Billing backend engine built with **FastAPI**, **PostgreSQL**, **SQLAlchemy**, and **Alembic**.

This engine provides high-throughput event ingestion, atomic idempotency guarantees, strict monthly quota boundary enforcement, integer-precision micro-cent cost calculation, background quota reconciliation, and webhook-driven Stripe subscription lifecycle management.

---

## Architecture & Design Principles

```mermaid
flowchart TD
    Client([Client / API Consumer])
    Stripe([Stripe Webhooks & Checkout])

    subgraph FastAPI Engine
        Health["GET /health (Diagnostics)"]
        Generate["POST /generate (Usage Ingestion & Idempotency)"]
        Usage["GET /usage (Monthly Aggregation & Micro-cent Cost)"]
        Checkout["POST /checkout (Stripe Session Creation)"]
        Webhook["POST /webhooks/stripe (Deduplication & Plan Upgrade)"]
        Reconcile["POST /admin/reconcile (Background Audit)"]
    end

    subgraph PostgreSQL Database
        T_Tenants[(tenants)]
        T_Plans[(plans)]
        T_Subs[(subscriptions)]
        T_Usage[(usage_events)]
        T_Webhooks[(processed_webhooks)]
    end

    Client -->|X-Tenant-ID + Idempotency-Key| Generate
    Client -->|X-Tenant-ID| Usage
    Client -->|X-Tenant-ID| Checkout
    Client --> Health
    Stripe --> Webhook

    Generate -->|Pessimistic Row Lock & Check Quota| T_Subs
    Generate -->|Record Usage Event| T_Usage
    Usage -->|Aggregate Month Usage| T_Usage
    Usage -->|Inspect Active Plan Limits| T_Plans
    Webhook -->|Deduplicate & Upgrade Plan| T_Webhooks
    Webhook -->|Update Plan ID| T_Subs
    Reconcile -->|Scan Over-Quota Tenants| T_Usage
```

### Key Business Rules
1. **Integer Money Rule (Micro-cents)**:
   - All cost calculations and storage use integer micro-cents ($1.00 USD = 10,000,000 micro-cents). No floating-point math is used in monetary paths.
   - Pricing rates:
     - API Call: `100,000` micro-cents ($0.01 / call)
     - Input Token: `15` micro-cents ($1.50 / 1M tokens)
     - Cached Input Token: `5` micro-cents ($0.50 / 1M tokens)
     - Output Token: `60` micro-cents ($6.00 / 1M tokens)
     - Reasoning Token: `60` micro-cents ($6.00 / 1M tokens)
2. **Strict Quota Boundary Enforcement**:
   - `current_usage + requested_usage > plan_limit` returns `429 Too Many Requests`.
   - Missing or inactive subscription returns `402 Payment Required`.
3. **Database-Backed Idempotency**:
   - Billable endpoints require `Idempotency-Key` and `X-Tenant-ID`.
   - Unique constraints on `(tenant_id, idempotency_key)` prevent duplicate billing during retries.
4. **Concurrency Safety**:
   - Pessimistic row locking (`with_for_update()`) on tenant subscriptions guarantees quota boundaries cannot be breached during simultaneous concurrent requests.
5. **Webhook Deduplication**:
   - Stripe events are recorded in `processed_webhooks` to prevent replay attacks and duplicate subscription upgrades.

---

## Tech Stack

- **Framework**: FastAPI (Python 3.13)
- **ASGI Server**: Uvicorn
- **Database**: PostgreSQL 16
- **ORM & Migrations**: SQLAlchemy 2.0 & Alembic
- **Billing Provider**: Stripe Python SDK
- **Testing**: Pytest & FastAPI TestClient
- **Containerization**: Docker & Docker Compose

---

## Project Structure

```
├── .env.example              # Environment variables template
├── .env                      # Local environment configuration (gitignored)
├── Dockerfile                # Production container specification
├── docker-compose.yml        # PostgreSQL + FastAPI container orchestration
├── requirements.txt          # Python package dependencies
├── capstone.yaml             # Evaluation entry points
├── DESIGN.md                 # System architecture & schema specifications
├── BUILDLOG.md               # Chronological engineering log
├── EVIDENCE.md               # Test outputs and verification receipts
├── src/
│   ├── alembic/              # Alembic migration scripts and configurations
│   ├── config.py             # App settings, pricing rates, and quota constants
│   ├── database.py           # SQLAlchemy database engine and session dependency
│   ├── models.py             # Database models (Tenant, Plan, Subscription, UsageEvent, ProcessedWebhook)
│   ├── services.py           # Core business logic (idempotency, quota checking, monthly aggregation)
│   ├── background.py         # Monthly reconciliation and tenant quota audit job
│   ├── seed.py               # Seed script for default Free/Pro plans and Demo Tenant
│   └── main.py               # FastAPI application, route handlers, middleware, and health probe
└── tests/
    ├── test_api.py           # Ingestion, usage aggregation, tracing, and health tests
    ├── test_quota.py         # Quota boundary and limit enforcement tests
    ├── test_idempotency.py   # Database idempotency deduplication tests
    ├── test_concurrency.py   # Multi-threaded race condition stress tests
    ├── test_stripe.py        # Stripe checkout and webhook tests
    └── test_background.py   # Background reconciliation tests
```

---

## Setup & Local Installation

### 1. Prerequisites
- Python 3.11+ (or Python 3.13)
- PostgreSQL 15+ running locally (or via Docker)
- Git

### 2. Clone and Setup Virtual Environment
```bash
# Clone the repository
git clone <your-repo-url>
cd Capstone-LLM

# Create and activate virtual environment
python -m venv .venv
# On Windows PowerShell:
.venv\Scripts\Activate.ps1
# On Linux/macOS:
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Configure Environment Variables
Copy `.env.example` to `.env`:
```bash
# On Windows PowerShell:
Copy-Item .env.example .env
# On Linux/macOS:
cp .env.example .env
```
Ensure `DATABASE_URL` matches your local PostgreSQL credentials (default: `postgresql://postgres:postgres@localhost:5432/metering_billing`).

### 4. Apply Database Migrations & Seed Data
```bash
# Apply migrations to PostgreSQL
alembic -c src/alembic.ini upgrade head

# Seed plans (Free, Pro) and Demo Tenant
python -m src.seed
```

---

## How to Run the Application

### Option A: Run Locally with Uvicorn
```bash
python -m uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
```
The server will start at `http://localhost:8000`. Interactive OpenAPI documentation is available at `http://localhost:8000/docs`.

### Option B: Run with Docker Compose
To run both the PostgreSQL database and FastAPI backend inside Docker containers:
```bash
docker-compose up --build
```

---

## API Reference & Curl Examples

### Demo Tenant Details
- **Tenant ID**: `11111111-1111-1111-1111-111111111111`
- **Plan**: `free` (1,000 API calls, 100,000 tokens)

---

### 1. Health Check Probe
```bash
curl -X GET http://localhost:8000/health
```
**Response (200 OK):**
```json
{
  "status": "healthy",
  "service": "metering-billing-engine",
  "database": "connected"
}
```

---

### 2. Billable Generation & Usage Ingestion
Records usage, enforces idempotency, checks plan quotas, and calculates micro-cent cost.

```bash
curl -X POST http://localhost:8000/generate \
  -H "Content-Type: application/json" \
  -H "X-Tenant-ID: 11111111-1111-1111-1111-111111111111" \
  -H "Idempotency-Key: req-001" \
  -d '{
    "prompt": "Explain quantum computing in simple terms",
    "simulate_tokens": {
      "input": 1500,
      "cached_input": 500,
      "output": 800,
      "reasoning": 200
    }
  }'
```
**Response (200 OK):**
```json
{
  "status": "success",
  "usage_recorded": {
    "api_calls": 1,
    "tokens": {
      "input": 1500,
      "cached_input": 500,
      "output": 800,
      "reasoning": 200
    }
  },
  "cost": {
    "amount": 185000,
    "currency": "USD",
    "unit": "microcents"
  }
}
```

---

### 3. Get Monthly Usage Summary
Returns aggregate usage for the current calendar month and total accumulated cost.

```bash
curl -X GET http://localhost:8000/usage \
  -H "X-Tenant-ID: 11111111-1111-1111-1111-111111111111"
```
**Response (200 OK):**
```json
{
  "tenant_id": "11111111-1111-1111-1111-111111111111",
  "plan": "free",
  "usage": {
    "api_calls": {
      "used": 1,
      "limit": 1000
    },
    "ai_tokens": {
      "used": 3000,
      "limit": 100000
    }
  },
  "cost": {
    "amount": 185000,
    "currency": "USD",
    "unit": "microcents"
  }
}
```

---

### 4. Create Stripe Checkout Session
Initiates upgrade to Pro subscription plan.

```bash
curl -X POST http://localhost:8000/checkout \
  -H "Content-Type: application/json" \
  -H "X-Tenant-ID: 11111111-1111-1111-1111-111111111111" \
  -d '{
    "success_url": "http://localhost:8000/success",
    "cancel_url": "http://localhost:8000/cancel"
  }'
```
**Response (200 OK):**
```json
{
  "status": "success",
  "session_id": "cs_test_...",
  "checkout_url": "https://checkout.stripe.com/c/pay/cs_test_..."
}
```

---

### 5. Stripe Webhook Processing (Upgrade & Deduplication)
```bash
curl -X POST http://localhost:8000/webhooks/stripe \
  -H "Content-Type: application/json" \
  -d '{
    "id": "evt_test_webhook_001",
    "type": "checkout.session.completed",
    "data": {
      "object": {
        "customer": "cus_test_123",
        "subscription": "sub_test_123",
        "metadata": {
          "tenant_id": "11111111-1111-1111-1111-111111111111"
        }
      }
    }
  }'
```
**Response (200 OK):**
```json
{
  "status": "success",
  "event_id": "evt_test_webhook_001"
}
```

---

### 6. Trigger Background Quota Reconciliation
Audits all tenants and identifies any over-quota accounts.

```bash
curl -X POST http://localhost:8000/admin/reconcile
```
**Response (200 OK):**
```json
{
  "status": "success",
  "summary": {
    "tenants_inspected": 1,
    "over_quota_tenants": []
  }
}
```

---

## Running the Automated Test Suite

Run all automated unit, integration, and concurrency stress tests with:
```bash
python -m pytest -v
```

### Test Coverage Breakdown
- `tests/test_api.py`: Ingestion pipeline, header validation, monthly usage calculation, health checks, and tracing middleware.
- `tests/test_quota.py`: Quota boundary checking, 429 rate limiting, and 402 missing subscription enforcement.
- `tests/test_idempotency.py`: Database-backed duplicate key filtering and response caching.
- `tests/test_concurrency.py`: Multi-threaded race condition tests (identical keys and quota depletion under load).
- `tests/test_stripe.py`: Checkout session generation and webhook idempotency deduplication.
- `tests/test_background.py`: Monthly usage audit job verification.
