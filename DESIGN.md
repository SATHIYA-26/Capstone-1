# Design Specification: Usage Metering & Billing Engine

This document defines the architectural patterns, database schemas, and business rules for the Usage Metering & Billing Engine.

---

## 1. Non-Goals
* **No Real AI Model Calls**: AI token usage is simulated by endpoint parameters or pre-calculated parameters.
* **No Complex Authentication**: A simple custom header (e.g., `X-Tenant-ID`) is used to identify tenants for multi-tenancy.
* **No Session-based Auth / OAuth**: Out of scope for this backend metering service.
* **No Redis/Celery**: Use standard background threads or lightweight solutions inside Python/FastAPI for async tasks to minimize infrastructure complexity.

---

## 2. Money Rule & Cost Strategy
* **Money Unit**: **Micro-cents** ($1 USD = 100 cents = 10,000,000 micro-cents). 1 micro-cent = $0.0000001 USD.
* **Storage & Calculations**: All calculations use Python/PostgreSQL integer types. No floating-point values are permitted in monetary paths to prevent floating-point rounding errors.
* **Pricing Configuration** (in micro-cents):
  * `API_CALL_PRICE` = 100,000 micro-cents ($0.01 per API call)
  * `INPUT_TOKEN_PRICE` = 15 micro-cents ($1.50 per 1M tokens)
  * `CACHED_INPUT_TOKEN_PRICE` = 5 micro-cents ($0.50 per 1M tokens)
  * `OUTPUT_TOKEN_PRICE` = 60 micro-cents ($6.00 per 1M tokens)
  * `REASONING_TOKEN_PRICE` = 60 micro-cents (follows output token price)

---

## 3. Database Schema

```mermaid
erDiagram
    TENANTS ||--o{ SUBSCRIPTIONS : has
    PLANS ||--o{ SUBSCRIPTIONS : governs
    TENANTS ||--o{ USAGE_EVENTS : generates
    TENANTS ||--o{ PROCESSED_WEBHOOKS : deduplicates

    TENANTS {
        uuid id PK
        string name
        timestamp created_at
    }

    PLANS {
        uuid id PK
        string name
        integer api_limit
        integer token_limit
        timestamp created_at
    }

    SUBSCRIPTIONS {
        uuid id PK
        uuid tenant_id FK
        uuid plan_id FK
        string stripe_customer_id
        string stripe_subscription_id
        string status
        timestamp created_at
        timestamp updated_at
    }

    USAGE_EVENTS {
        uuid id PK
        uuid tenant_id FK
        string usage_type
        integer quantity
        string token_category
        string idempotency_key UNIQUE
        timestamp timestamp
    }

    PROCESSED_WEBHOOKS {
        string event_id PK
        timestamp processed_at
    }
```

### Table Definitions & Indexes

1. **`tenants`**
   * Primary Key: `id` (UUID)
   * Fields: `name` (VARCHAR), `created_at` (TIMESTAMP)

2. **`plans`**
   * Primary Key: `id` (UUID)
   * Fields: `name` (VARCHAR), `api_limit` (INT), `token_limit` (INT), `created_at` (TIMESTAMP)

3. **`subscriptions`**
   * Primary Key: `id` (UUID)
   * Fields: `tenant_id` (UUID FK), `plan_id` (UUID FK), `stripe_customer_id` (VARCHAR), `stripe_subscription_id` (VARCHAR), `status` (VARCHAR), `created_at` (TIMESTAMP), `updated_at` (TIMESTAMP)
   * Constraints & Indexes:
     * Unique index on `stripe_subscription_id`
     * Index on `tenant_id`

4. **`usage_events`**
   * Primary Key: `id` (UUID)
   * Fields: `tenant_id` (UUID FK), `usage_type` (VARCHAR: `api_call`, `ai_token`), `quantity` (INT), `token_category` (VARCHAR: `input`, `cached_input`, `output`, `reasoning` or NULL), `idempotency_key` (VARCHAR), `timestamp` (TIMESTAMP)
   * Constraints & Indexes:
     * Unique constraint on `(tenant_id, idempotency_key)` to prevent duplicate events for the same tenant.
     * Index on `(tenant_id, usage_type, timestamp)` for rapid monthly aggregation queries.

5. **`processed_webhooks`**
   * Primary Key: `event_id` (VARCHAR) - Stores Stripe webhook event IDs to guarantee event deduplication.
   * Fields: `processed_at` (TIMESTAMP)

---

## 4. Idempotency Strategy
* Clients must send a header: `Idempotency-Key`.
* When a request arrives at a billable endpoint:
  1. We check if a usage event with the same `(tenant_id, idempotency_key)` already exists in the database.
  2. If it **exists**, we do not record new usage. We fetch the previous event details and return the cached or calculated response for that action (safely returning HTTP 200).
  3. If it **does not exist**, we proceed to validate quota, perform the action, record the event, and return the response.
* Database uniqueness constraints protect against race conditions under concurrent retries.

---

## 5. Quota Boundary Rule
* **Rule**: Usage checks are evaluated using **strictly over the limit** logic.
  * `current_usage + requested_usage > plan_limit` => Quota Exceeded.
  * If `current_usage + requested_usage <= plan_limit` => Allowed.
* **HTTP Responses**:
  * **Quota Limit Exceeded**: Returns `429 Too Many Requests` with a body describing which resource limit (API calls or tokens) was hit.
  * **No Subscription or Upgrade Required**: Returns `402 Payment Required` if a tenant on a Free plan has run out of units and needs to upgrade to Pro.

---

## 6. API Surface Design

### 1. `POST /generate` (Billable Endpoint)
* **Headers**:
  * `X-Tenant-ID` (UUID)
  * `Idempotency-Key` (String)
* **Payload**:
  ```json
  {
    "prompt": "Hello world",
    "simulate_tokens": {
      "input": 1500,
      "cached_input": 500,
      "output": 800,
      "reasoning": 200
    }
  }
  ```
* **Response (HTTP 200)**:
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
      "amount": 221000,
      "currency": "USD",
      "unit": "microcents"
    }
  }
  ```

### 2. `GET /usage` (Monthly Summary)
* **Headers**:
  * `X-Tenant-ID` (UUID)
* **Response (HTTP 200)**:
  ```json
  {
    "tenant_id": "uuid",
    "plan": "free",
    "usage": {
      "api_calls": {
        "used": 450,
        "limit": 1000
      },
      "ai_tokens": {
        "used": 45000,
        "limit": 100000
      }
    },
    "cost": {
      "amount": 2345000,
      "currency": "USD",
      "unit": "microcents"
    }
  }
  ```
