import logging
from typing import Dict, Any
from sqlalchemy.orm import Session
from src.models import Tenant, Subscription, Plan
from src.services import get_monthly_usage

logger = logging.getLogger("background_reconciler")

def run_monthly_reconciliation(db: Session) -> Dict[str, Any]:
    """
    Background job function to inspect all active tenants, calculate their monthly usage,
    and verify whether any tenant has crossed quota limits without active flags.
    """
    tenants = db.query(Tenant).all()
    results = {
        "tenants_inspected": len(tenants),
        "over_quota_tenants": []
    }

    for tenant in tenants:
        sub = db.query(Subscription).filter(
            Subscription.tenant_id == tenant.id,
            Subscription.status == "active"
        ).first()

        if not sub:
            continue

        plan = db.query(Plan).filter(Plan.id == sub.plan_id).first()
        if not plan:
            continue

        usage = get_monthly_usage(db, tenant.id)
        
        is_over_api = usage["api_calls"] > plan.api_limit
        is_over_tokens = usage["ai_tokens"] > plan.token_limit

        if is_over_api or is_over_tokens:
            results["over_quota_tenants"].append({
                "tenant_id": str(tenant.id),
                "tenant_name": tenant.name,
                "plan_name": plan.name,
                "api_calls": usage["api_calls"],
                "api_limit": plan.api_limit,
                "ai_tokens": usage["ai_tokens"],
                "token_limit": plan.token_limit
            })

    return results
