import uuid
from datetime import datetime
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, UniqueConstraint, Index, Uuid
from src.database import Base

class Tenant(Base):
    __tablename__ = "tenants"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class Plan(Base):
    __tablename__ = "plans"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False, unique=True)
    api_limit = Column(Integer, nullable=False)  # Max API calls per month
    token_limit = Column(Integer, nullable=False)  # Max AI tokens per month
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class Subscription(Base):
    __tablename__ = "subscriptions"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id = Column(Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    plan_id = Column(Uuid, ForeignKey("plans.id", ondelete="RESTRICT"), nullable=False)
    stripe_customer_id = Column(String, nullable=True)
    stripe_subscription_id = Column(String, nullable=True, unique=True)
    status = Column(String, nullable=False)  # active, trialing, canceled, etc.
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_subscriptions_tenant_id", "tenant_id"),
    )


class UsageEvent(Base):
    __tablename__ = "usage_events"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id = Column(Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    usage_type = Column(String, nullable=False)  # "api_call" or "ai_token"
    quantity = Column(Integer, nullable=False)
    token_category = Column(String, nullable=True)  # "input", "cached_input", "output", "reasoning"
    idempotency_key = Column(String, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_tenant_idempotency_key"),
        Index("ix_usage_events_tenant_type_time", "tenant_id", "usage_type", "timestamp"),
    )


class ProcessedWebhook(Base):
    __tablename__ = "processed_webhooks"

    event_id = Column(String, primary_key=True)
    processed_at = Column(DateTime, default=datetime.utcnow, nullable=False)
