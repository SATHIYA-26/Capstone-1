from fastapi import FastAPI

app = FastAPI(
    title="Usage Metering & Billing Engine",
    version="1.0.0",
    description="A SaaS usage metering and Stripe billing backend engine."
)

@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "service": "metering-billing-engine"
    }

if __name__ == "__main__":
    import uvicorn
    from src.config import settings
    uvicorn.run("src.main:app", host=settings.HOST, port=settings.PORT, reload=True)
