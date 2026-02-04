"""Example FastAPI app for local SDK testing.

Usage:
    # From the tracely-sdk directory:
    pip install -e ".[dev]"
    pip install fastapi uvicorn

    # Run with your local ingestion API:
    TRACELY_API_KEY=trly_test123 TRACELY_ENDPOINT=http://localhost:8000 python examples/fastapi_app.py

    # Then hit the endpoints:
    curl http://localhost:9000/
    curl http://localhost:9000/users
    curl http://localhost:9000/users/42
    curl -X POST http://localhost:9000/orders -H "Content-Type: application/json" -d '{"item": "widget", "qty": 3}'
    curl http://localhost:9000/slow
    curl http://localhost:9000/error
"""

from __future__ import annotations

import asyncio
import logging

import tracely
from tracely.instrumentation.fastapi_inst import TracelyASGIMiddleware

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

# Enable tracely debug logging to see what the SDK is doing
logging.basicConfig(level=logging.DEBUG)
logging.getLogger("tracely").setLevel(logging.DEBUG)

# Initialize the SDK -- reads TRACELY_API_KEY and TRACELY_ENDPOINT from env
tracely.init(
    environment="dev",
    service_name="api",
    service_version="1.0.0",
)

app = FastAPI(title="Tracely SDK Test App")

# Add the middleware -- this auto-instruments all routes
app.add_middleware(TracelyASGIMiddleware)


@app.get("/")
async def root():
    tracely.info("Root endpoint hit")
    return {"status": "ok", "message": "Tracely SDK test app"}


@app.get("/users")
async def list_users():
    # Custom child span for a simulated DB query
    with tracely.span("db.query", kind="CLIENT") as s:
        s.set_attribute("db.system", "postgres")
        s.set_attribute("db.statement", "SELECT * FROM users LIMIT 10")
        await asyncio.sleep(0.05)  # simulate DB latency

    tracely.info("Listed users", count="10")
    return {"users": [{"id": i, "name": f"User {i}"} for i in range(10)]}


@app.get("/users/{user_id}")
async def get_user(user_id: int):
    with tracely.span("db.query", kind="CLIENT") as s:
        s.set_attribute("db.system", "postgres")
        s.set_attribute("db.statement", f"SELECT * FROM users WHERE id = $1")
        await asyncio.sleep(0.02)

    if user_id == 0:
        raise HTTPException(status_code=404, detail="User not found")

    return {"id": user_id, "name": f"User {user_id}", "email": f"user{user_id}@example.com"}


@app.post("/orders")
async def create_order(order: dict):
    tracely.info("Creating order", item=str(order.get("item", "unknown")))

    # Simulate multiple child spans
    with tracely.span("validate-order", kind="INTERNAL") as s:
        s.set_attribute("order.item", str(order.get("item", "")))
        await asyncio.sleep(0.01)

    with tracely.span("db.insert", kind="CLIENT") as s:
        s.set_attribute("db.system", "postgres")
        s.set_attribute("db.statement", "INSERT INTO orders ...")
        await asyncio.sleep(0.03)

    with tracely.span("send-notification", kind="PRODUCER") as s:
        s.set_attribute("messaging.system", "redis")
        await asyncio.sleep(0.01)

    tracely.info("Order created successfully")
    return {"order_id": 12345, "status": "created"}


@app.get("/slow")
async def slow_endpoint():
    """Simulates a slow request -- good for testing pending_span visibility."""
    tracely.info("Starting slow operation")

    with tracely.span("heavy-computation", kind="INTERNAL"):
        await asyncio.sleep(3.0)

    tracely.info("Slow operation complete")
    return {"status": "done", "duration": "3s"}


@app.get("/error")
async def error_endpoint():
    """Triggers an unhandled exception -- tests error capture."""
    tracely.warning("About to fail")
    raise ValueError("Something went wrong!")


@app.on_event("shutdown")
async def shutdown():
    tracely.shutdown()


if __name__ == "__main__":
    import uvicorn

    print("\n  Tracely SDK Test App")
    print("  ====================")
    print("  Endpoints:")
    print("    GET  http://localhost:9000/")
    print("    GET  http://localhost:9000/users")
    print("    GET  http://localhost:9000/users/42")
    print("    POST http://localhost:9000/orders")
    print("    GET  http://localhost:9000/slow      (3s delay - test pending spans)")
    print("    GET  http://localhost:9000/error     (triggers error capture)")
    print()

    uvicorn.run(app, host="0.0.0.0", port=9002)
