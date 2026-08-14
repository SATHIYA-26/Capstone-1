import os
from dotenv import load_dotenv

# Load variables from .env file if it exists
load_dotenv()

class Settings:
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL", 
        "postgresql://postgres:postgres@localhost:5432/metering_billing"
    )
    STRIPE_API_KEY: str = os.getenv("STRIPE_API_KEY", "sk_test_placeholder")
    STRIPE_WEBHOOK_SECRET: str = os.getenv("STRIPE_WEBHOOK_SECRET", "whsec_placeholder")
    STRIPE_PRO_PRICE_ID: str = os.getenv("STRIPE_PRO_PRICE_ID", "price_pro_placeholder")
    PORT: int = int(os.getenv("PORT", "8000"))
    HOST: str = os.getenv("HOST", "0.0.0.0")

    # Pricing constants in micro-cents
    # $1.00 USD = 10,000,000 micro-cents
    API_CALL_PRICE: int = 100_000         # $0.01 per call
    INPUT_TOKEN_PRICE: int = 15           # $1.50 per 1M tokens
    CACHED_INPUT_TOKEN_PRICE: int = 5     # $0.50 per 1M tokens
    OUTPUT_TOKEN_PRICE: int = 60          # $6.00 per 1M tokens
    REASONING_TOKEN_PRICE: int = 60       # Follows output token price

    # Quotas for Free Plan
    FREE_API_LIMIT: int = 1_000
    FREE_TOKEN_LIMIT: int = 100_000

    # Quotas for Pro Plan (configured limits)
    PRO_API_LIMIT: int = 100_000
    PRO_TOKEN_LIMIT: int = 10_000_000

settings = Settings()
