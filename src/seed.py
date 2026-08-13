import uuid
from sqlalchemy.orm import Session
from src.database import SessionLocal, Base
from src.models import Plan, Tenant, Subscription

def seed_db():
    db = SessionLocal()
    try:
        print("Seeding plans...")
        # Seed Free Plan
        free_plan = db.query(Plan).filter_by(name="free").first()
        if not free_plan:
            free_plan = Plan(
                id=uuid.uuid4(),
                name="free",
                api_limit=1_000,
                token_limit=100_000
            )
            db.add(free_plan)
            print("Added Free Plan")
        else:
            print("Free Plan already exists")

        # Seed Pro Plan
        pro_plan = db.query(Plan).filter_by(name="pro").first()
        if not pro_plan:
            pro_plan = Plan(
                id=uuid.uuid4(),
                name="pro",
                api_limit=100_000,
                token_limit=10_000_000
            )
            db.add(pro_plan)
            print("Added Pro Plan")
        else:
            print("Pro Plan already exists")

        db.commit()

        # Seed Demo Tenant if not exists
        print("Seeding demo tenant...")
        demo_tenant = db.query(Tenant).filter_by(name="Demo Tenant").first()
        if not demo_tenant:
            demo_tenant = Tenant(
                id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
                name="Demo Tenant"
            )
            db.add(demo_tenant)
            db.commit()
            print(f"Added Demo Tenant (ID: {demo_tenant.id})")
        else:
            print(f"Demo Tenant already exists (ID: {demo_tenant.id})")

        # Seed Demo Subscription to Free Plan
        demo_sub = db.query(Subscription).filter_by(tenant_id=demo_tenant.id).first()
        if not demo_sub:
            demo_sub = Subscription(
                id=uuid.uuid4(),
                tenant_id=demo_tenant.id,
                plan_id=free_plan.id,
                stripe_customer_id="cus_placeholder_demo",
                stripe_subscription_id="sub_placeholder_demo",
                status="active"
            )
            db.add(demo_sub)
            db.commit()
            print("Added Demo Tenant Subscription to Free Plan")
        else:
            print("Demo Tenant Subscription already exists")

        print("Database seeded successfully!")
    except Exception as e:
        db.rollback()
        print(f"Error seeding database: {e}")
        raise e
    finally:
        db.close()

if __name__ == "__main__":
    seed_db()
