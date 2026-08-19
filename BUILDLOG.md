# Build Log

## [2026-08-13] Phase 1: Design & Project Foundation
- Reviewed specifications and authored [DESIGN.md](file:///d:/Internship-FlyRank-AI/Capstone-LLM/DESIGN.md) covering ER schema, money rules, boundary checking, and idempotency strategy.
- Created environment configuration structure in [.env.example](file:///d:/Internship-FlyRank-AI/Capstone-LLM/.env.example) and [.env](file:///d:/Internship-FlyRank-AI/Capstone-LLM/.env).
- Created [src/config.py](file:///d:/Internship-FlyRank-AI/Capstone-LLM/src/config.py) defining pricing constants in micro-cents and Free/Pro quota thresholds.

## [2026-08-13] Phase 2: Database & Core Setup
- Configured PostgreSQL connection and session management in [src/database.py](file:///d:/Internship-FlyRank-AI/Capstone-LLM/src/database.py).
- Defined SQLAlchemy ORM models in [src/models.py](file:///d:/Internship-FlyRank-AI/Capstone-LLM/src/models.py) (`Tenant`, `Plan`, `Subscription`, `UsageEvent`, `ProcessedWebhook`).
- Initialized Alembic migrations and applied initial schema migration.
- Created [src/seed.py](file:///d:/Internship-FlyRank-AI/Capstone-LLM/src/seed.py) to seed `free` and `pro` plans and default Demo Tenant (`11111111-1111-1111-1111-111111111111`).

## [2026-08-14] Phase 3: Ingestion & Idempotency Pipeline
- Implemented `POST /generate` endpoint in [src/main.py](file:///d:/Internship-FlyRank-AI/Capstone-LLM/src/main.py) with `X-Tenant-ID` and `Idempotency-Key` header enforcement.
- Created `record_usage_events()` and `get_existing_events()` in [src/services.py](file:///d:/Internship-FlyRank-AI/Capstone-LLM/src/services.py).
- Added unique constraint `(tenant_id, idempotency_key)` to guarantee atomic deduplication.
- Verified with [tests/test_idempotency.py](file:///d:/Internship-FlyRank-AI/Capstone-LLM/tests/test_idempotency.py).

## [2026-08-14] Phase 4: Quota Management & Boundary Enforcement
- Implemented `check_quota()` in [src/services.py](file:///d:/Internship-FlyRank-AI/Capstone-LLM/src/services.py) with strictly over the limit (`>`) boundary logic.
- Implemented `429 Too Many Requests` for quota breaches and `402 Payment Required` for missing subscriptions.
- Verified with [tests/test_quota.py](file:///d:/Internship-FlyRank-AI/Capstone-LLM/tests/test_quota.py).

## [2026-08-14] Phase 5: Usage & Billing Aggregation
- Implemented `get_monthly_usage()` calendar-month aggregation query in [src/services.py](file:///d:/Internship-FlyRank-AI/Capstone-LLM/src/services.py).
- Implemented `GET /usage` endpoint returning current month breakdown and micro-cent cost calculation.
- Verified with [tests/test_api.py](file:///d:/Internship-FlyRank-AI/Capstone-LLM/tests/test_api.py).

## [2026-08-14] Phase 6: Background Processing & Async Jobs
- Implemented `run_monthly_reconciliation()` in [src/background.py](file:///d:/Internship-FlyRank-AI/Capstone-LLM/src/background.py) to audit tenants against plan limits.
- Exposed `POST /admin/reconcile` trigger endpoint in [src/main.py](file:///d:/Internship-FlyRank-AI/Capstone-LLM/src/main.py).
- Verified with [tests/test_background.py](file:///d:/Internship-FlyRank-AI/Capstone-LLM/tests/test_background.py).

## [2026-08-14] Phase 7: Stripe Integration
- Implemented `POST /checkout` to generate Stripe Checkout Sessions.
- Implemented `POST /webhooks/stripe` with signature verification and deduplication via `ProcessedWebhook` table.
- Upgraded tenant subscription plan to `pro` upon `checkout.session.completed`.
- Verified with [tests/test_stripe.py](file:///d:/Internship-FlyRank-AI/Capstone-LLM/tests/test_stripe.py).

## [2026-08-14] Phase 8: Comprehensive End-to-End Testing
- Built and verified automated test suite covering all API endpoints, edge cases, and error codes.

## [2026-08-14] Phase 9: Containerization & Deployment
- Authored production [Dockerfile](file:///d:/Internship-FlyRank-AI/Capstone-LLM/Dockerfile) with Python 3.13 and Uvicorn runtime.
- Created [docker-compose.yml](file:///d:/Internship-FlyRank-AI/Capstone-LLM/docker-compose.yml) orchestrating PostgreSQL 16 service with healthcheck and FastAPI backend.

## [2026-08-19] Phase 10: Concurrency & Stress Testing
- Built multi-threaded stress tests in [tests/test_concurrency.py](file:///d:/Internship-FlyRank-AI/Capstone-LLM/tests/test_concurrency.py).
- Added pessimistic row locking (`with_for_update()`) on `Subscription` table in `check_quota()` to prevent race conditions during parallel quota consumption.

## [2026-08-19] Phase 11: Observability & Health Probing
- Added request tracing middleware in [src/main.py](file:///d:/Internship-FlyRank-AI/Capstone-LLM/src/main.py) with `X-Request-ID` and latency calculation `X-Process-Time-Ms`.
- Configured structured standard logging.
- Enhanced `GET /health` with live PostgreSQL database connection verification.

## [2026-08-19] Phase 12: Documentation, Evidence Collection & Finalization
- Updated [README.md](file:///d:/Internship-FlyRank-AI/Capstone-LLM/README.md) with complete architecture, setup guide, curl examples, and operational run instructions.
- Generated full verification evidence in [EVIDENCE.md](file:///d:/Internship-FlyRank-AI/Capstone-LLM/EVIDENCE.md).
- Validated [capstone.yaml](file:///d:/Internship-FlyRank-AI/Capstone-LLM/capstone.yaml) evaluation entry points.
